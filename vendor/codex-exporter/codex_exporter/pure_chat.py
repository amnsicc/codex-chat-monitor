"""Strict opt-in policy around the existing classic parser/classifier.

No JSONL parser, tokenizer, or text-based deletion rules live here.
"""
from copy import deepcopy
import hashlib

TEXT_TYPES = {'input_text', 'output_text', 'text'}
ATTACHMENTS = {'input_image','image','image_url','input_file','file','audio','input_audio'}
RUNTIME = {'task_started','task_complete','turn_aborted','thread_settings_applied',
           'token_count','item_started','agent_message_delta','agent_reasoning_delta',
           'agent_reasoning_section_break','raw_response_item','thread_name_updated'}
TOOLS = {'function_call','function_call_output','custom_tool_call','custom_tool_call_output',
         'web_search_call','local_shell_call','computer_call','computer_call_output',
         'reasoning','additional_tools'}
DESKTOP_TOOLS = {'commandexecution','filechange','extension','imageview','mcptoolcall',
                 'websearch','reasoning','plan','collabagenttoolcall'}

def issue(audit, seq, reason):
    audit['issues'].append({'line':seq,'reason':reason})

def select(obj, seq, audit):
    """Return a structurally verified message for the original classifier."""
    top = obj.get('type')
    payload = obj.get('payload') if isinstance(obj.get('payload'),dict) else {}
    kind = payload.get('type','')
    if top in {'session_meta','turn_context','world_state','compacted'}:
        return None, 'metadata_or_derived_history'
    if top == 'event_msg' and kind in RUNTIME:
        return None, 'runtime_event'
    item = payload.get('item') if kind == 'item_completed' and isinstance(payload.get('item'),dict) else payload
    subtype = str(item.get('type','')).lower()
    if (top == 'response_item' and kind in TOOLS or
            top == 'event_msg' and kind == 'item_completed' and subtype in DESKTOP_TOOLS):
        return None, 'tool_or_reasoning'
    role = item.get('role')
    completed = top == 'event_msg' and kind == 'item_completed'
    if completed and subtype in {'usermessage','agentmessage'}:
        role = 'user' if subtype == 'usermessage' else 'assistant'
    supported = (top == 'response_item' and kind == 'message' or
                 completed and subtype in {'usermessage','agentmessage'})
    if role in {'system','developer'}:
        return None, 'system_or_host'
    if not supported:
        issue(audit,seq,'unknown_source_schema')
        return None, 'unverified'
    if role == 'assistant' and (item.get('channel') in {'analysis','justify','confidence'} or
            item.get('recipient') not in (None,'','all')):
        return None, 'internal_assistant_message'
    if role not in {'user','assistant'}:
        issue(audit,seq,'unknown_role')
        return None, 'unverified'
    if item.get('truncated') or item.get('is_truncated') or item.get('incomplete'):
        issue(audit,seq,'chat_body_truncated')
    content = item.get('content')
    if not isinstance(content,list):
        if completed and isinstance(item.get('text'),str):
            content = [{'type':'text','text':item['text']}]
        else:
            issue(audit,seq,'unknown_content_structure')
            return None,'unverified'
    metadata = item.get('internal_chat_message_metadata_passthrough') or {}
    provenances = metadata.get('content_item_metadata',[])
    if role == 'user' and not completed and len(provenances) != len(content):
        issue(audit,seq,'missing_user_content_provenance')
        return None, 'unverified'
    if role == 'user' and completed and not item.get('client_id'):
        issue(audit,seq,'missing_completed_user_client_provenance')
        return None, 'unverified'
    chosen, positions = [], []
    for i,part in enumerate(content):
        if not isinstance(part,dict):
            issue(audit,seq,'unknown_content_part'); continue
        part_type = part.get('type')
        if part_type in ATTACHMENTS:
            audit['parts_excluded'].append({'line':seq,'position':i,'reason':'attachment_body'})
            continue
        if role == 'user' and not completed:
            provenance = provenances[i].get('provenance',{}).get('type')
            if provenance in {'context','system','developer','host','environment'}:
                audit['parts_excluded'].append({'line':seq,'position':i,'reason':'host_provenance'})
                continue
            if provenance != 'user':
                issue(audit,seq,'unknown_user_content_provenance'); continue
        if part_type not in TEXT_TYPES or not isinstance(part.get('text'),str):
            issue(audit,seq,'unknown_text_part'); continue
        if part.get('truncated') or part.get('is_truncated'):
            issue(audit,seq,'chat_part_truncated')
        chosen.append(part)
        positions.append(i)
    if not chosen:
        return None,'no_chat_text'
    result = deepcopy(obj)
    target = result['payload']['item'] if completed else result['payload']
    target['content'] = chosen
    # Match projection only when every retained part was user-authored text.
    if role == 'user' and not completed:
        md = target['internal_chat_message_metadata_passthrough']
        md['content_item_metadata'] = [provenances[i] for i in positions]
        md['content_item_kinds'] = ['user.text'] * len(positions)
    audit['included'].append({'line':seq,'role':role,'positions':positions})
    return result,'chat'

def deduplicate(records, audit):
    """Reuse existing desktop turn projection; only proven IDs authorize merges."""
    from .material_identity import match_unique_real_user_turn
    # Native ID namespaces differ for response items and desktop user items.
    out, identities = [], {}
    for rec in records:
        namespace = 'desktop_user' if rec.role == 'user' and rec.event_family.endswith('item_completed') else 'native'
        key = (namespace,rec.role,rec.turn_id,rec.message_id) if rec.message_id else None
        previous = identities.get(key) if key else None
        if previous:
            sources = {r.get('source') for r in previous.source_refs}
            cross_source = rec.source_refs[0].get('source') not in sources
            cross_form = rec.event_family != previous.event_family
            if previous.text != rec.text:
                audit['uncertainties'].append({'reason':'identity_content_conflict','refs':rec.source_refs})
            elif cross_source or cross_form:
                previous.source_refs.extend(rec.source_refs)
                audit['merges'].append({'reason':'verified_message_identity','id':rec.message_id,
                                       'refs':rec.source_refs})
                continue
            else:
                audit['uncertainties'].append({'reason':'same_identity_replay','refs':rec.source_refs})
        out.append(rec)
        if key: identities[key] = rec
    out = match_unique_real_user_turn(out,audit)
    # Unidentified cross-form copies remain visible and explicitly uncertain.
    for i,rec in enumerate(out):
        if not rec.message_id:
            for prev in out[:i]:
                if (rec.role,rec.turn_id,rec.text) == (prev.role,prev.turn_id,prev.text) and rec.event_family != prev.event_family:
                    audit['uncertainties'].append({'reason':'unidentified_mirror','refs':rec.source_refs})
    return out
