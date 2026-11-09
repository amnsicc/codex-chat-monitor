"""Opt-in classic-export provenance/dedup policy for the isolated material trial.

This consumes already-classified exporter records. It does not parse JSONL,
render content, infer identities from text, or change the streaming path.
"""
import hashlib

PATCH_ID = 'material-identity-real-schema-20261102-01'

def annotate(rec, obj, seq, schema, turn_id, line):
    payload = obj.get('payload') if isinstance(obj.get('payload'), dict) else {}
    item = payload.get('item') if isinstance(payload.get('item'), dict) else payload
    rec.message_id = ''
    if rec.kind == 'message':
        rec.message_id = str(item.get('message_id') or item.get('item_id') or item.get('id') or '')
    rec.call_id = str(item.get('call_id') or payload.get('call_id') or '')
    rec.turn_id = str(item.get('turn_id') or payload.get('turn_id') or obj.get('turn_id') or turn_id or '')
    rec.event_family = str(obj.get('type') or '')
    if payload.get('type') == 'item_completed':
        rec.event_family += '/item_completed'
    prefix = 'payload.item' if item is not payload else 'payload'
    content = item.get('content')
    metadata = item.get('internal_chat_message_metadata_passthrough') or {}
    if not rec.turn_id:
        rec.turn_id = str(metadata.get('turn_id') or '')
    kind = str(item.get('type') or '')
    rec.real_user_form = ('retained_user_text' if rec.event_family == 'response_item'
        and item.get('role') == 'user' and metadata.get('content_item_kinds') == ['user.text']
        and all(m.get('provenance', {}).get('type') == 'user' for m in metadata.get('content_item_metadata', []))
        and bool(metadata.get('content_item_metadata')) else
        'completed_user_item' if rec.event_family == 'event_msg/item_completed'
        and kind == 'UserMessage' and item.get('client_id') else '')
    rec.source_refs = [{'line': seq, 'schema': schema,
        'line_text_sha256': hashlib.sha256(line.encode('utf-8')).hexdigest(),
        'message_id': rec.message_id, 'call_id': rec.call_id,
        'turn_id': rec.turn_id, 'event_family': rec.event_family,
        'user_representation': rec.real_user_form,
        'content_positions': [f'{prefix}.content[{i}]' for i in range(len(content))]
                             if isinstance(content, list) else []}]

def deduplicate(records, audit):
    """Pair only explicit same-message identities across supported mirror forms.

    IDs are interpreted only on recognized message schemas. Missing IDs, same
    text alone, conflicting turns, changed content, or repeated same-family
    records never authorize deletion. Each representation can join a pair once.
    """
    records = match_unique_real_user_turn(records, audit)
    out, identities, texts = [], {}, {}
    mirror_families = {'event_msg', 'event_msg/item_completed'}
    for rec in records:
        identity = (rec.kind, rec.role, rec.message_id) if rec.message_id else None
        previous = identities.get(identity, []) if identity else []
        paired = False
        for prev in previous:
            families = {r['event_family'] for r in prev.source_refs}
            cross_form = (rec.event_family == 'response_item' and bool(families & mirror_families)
                          or rec.event_family in mirror_families and 'response_item' in families)
            if (cross_form and rec.event_family not in families and len(families) == 1
                    and rec.turn_id == prev.turn_id and rec.text == prev.text):
                prev.source_refs.extend(rec.source_refs)
                audit['merges'].append({'reason': 'explicit_message_identity_across_representations',
                    'message_id': rec.message_id, 'turn_id': rec.turn_id,
                    'kept_line': prev.seq, 'merged_line': rec.seq})
                paired = True
                break
        if paired:
            continue
        signature = (rec.kind, rec.role, hashlib.sha256(rec.text.encode('utf-8')).hexdigest())
        prev_texts = texts.get(signature, [])
        uncertain = []
        for prev in previous:
            if rec.turn_id == prev.turn_id:
                uncertain.append(prev.seq)  # same ID: update/replay/conflict, not a proven mirror
        for prev in prev_texts:
            known_distinct = (rec.kind == 'message' and rec.message_id and prev.message_id
                              and rec.message_id != prev.message_id
                              and rec.event_family == prev.event_family
                              or rec.kind == 'action' and rec.call_id and prev.call_id
                              and rec.call_id != prev.call_id
                              or rec.turn_id and prev.turn_id and rec.turn_id != prev.turn_id)
            if not known_distinct:
                uncertain.append(prev.seq)
        if uncertain:
            audit['uncertainties'].append({'line': rec.seq, 'related_lines': sorted(set(uncertain)),
                'reason': 'retained_without_proven_mirror_relation',
                'message_id': rec.message_id, 'call_id': rec.call_id})
        out.append(rec)
        if identity:
            identities.setdefault(identity, []).append(rec)
        texts.setdefault(signature, []).append(rec)
    return out

def allowed_exclusion(obj, reason):
    top = obj.get('type')
    payload = obj.get('payload') if isinstance(obj.get('payload'), dict) else {}
    if reason == 'metadata_only':
        return top in {'session_meta', 'turn_context', 'world_state'}
    if reason == 'tool_catalog_metadata':
        return top == 'response_item' and payload.get('type') == 'additional_tools'
    if reason == 'runtime_configuration_update':
        return set(payload) <= {'type', 'reasoning'}
    if reason == 'reasoning_summary_opt_in_disabled':
        item = payload.get('item') if isinstance(payload.get('item'), dict) else payload
        return not item.get('summary') and not item.get('summary_text') and not item.get('raw_content')
    if reason == 'telemetry_token_count':
        return True
    if reason == 'context_history_event':
        return top == 'compacted'  # exclude derived replacement, retain all chronological records
    if reason == 'lifecycle_event':
        return payload.get('type') in {'task_started', 'task_complete', 'turn_aborted', 'thread_settings_applied'}
    return False

def match_unique_real_user_turn(records, audit):
    """Explicit desktop projection policy, not an inferred shared ID.

    Only a unique user-authored retained text and unique completed UserMessage
    in the same nonempty turn can share one material entry. Exact text is a
    consistency check, never the only evidence. Every source remains referenced.
    Multiple candidates or mismatches stay unmerged and are rejected by the gate.
    """
    groups = {}
    for rec in records:
        form = getattr(rec, 'real_user_form', '')
        if rec.kind == 'message' and rec.role == 'user' and rec.turn_id and form:
            group = groups.setdefault(rec.turn_id, {'retained_user_text': [], 'completed_user_item': []})
            group[form].append(rec)
    suppressed = set()
    for turn, group in groups.items():
        retained, completed = group['retained_user_text'], group['completed_user_item']
        if len(retained) == len(completed) == 1 and retained[0].text == completed[0].text:
            canonical, item = retained[0], completed[0]
            canonical.source_refs.extend(item.source_refs)
            suppressed.add(item.seq)
            audit['merges'].append({'reason': 'desktop_unique_user_turn_projection',
                'identity_relation': 'different ID namespaces; selected by explicit representation policy',
                'turn_id': turn, 'kept_line': canonical.seq, 'merged_line': item.seq,
                'retained_id': canonical.message_id, 'completed_item_id': item.message_id})
        elif retained and completed:
            audit['uncertainties'].append({'reason': 'ambiguous_desktop_user_turn_projection',
                'turn_id': turn, 'retained_lines': [r.seq for r in retained],
                'completed_lines': [r.seq for r in completed]})
    return [r for r in records if r.seq not in suppressed]

def finish(meta, records):
    audit = meta['_material_audit']
    audit.update(patch_id=PATCH_ID, enabled=True,
        semantics='chronological recorded user/assistant/system text plus classified tools; explicit exclusions',
        source_event_count=meta.get('_source_event_count', 0),
        rendered_records=[{'kind': rec.kind, 'role': rec.role, 'refs': rec.source_refs} for rec in records],
        parse_errors=meta.get('_parse_errors', []), repaired_lines=meta.get('_repaired_json_lines', []),
        source_truncation_markers=meta.get('_raw_source_truncation_marker_count', 0),
        unknown_event_types=dict(meta.get('_unknown_event_types', {})))
    audit['complete_for_policy'] = not any((audit['uncertainties'], audit['parse_errors'],
        audit['repaired_lines'], audit['source_truncation_markers'], audit['unknown_event_types'],
        [row for row in audit['exclusions'] if not row['allowed_by_policy']]))
    return audit
