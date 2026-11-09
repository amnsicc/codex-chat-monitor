"""Reconcile already-classified message identities, never parse JSONL or body text."""
from collections import defaultdict
from datetime import datetime,timezone
import re

INSTANT=re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$')

def reconcile_order(records,audit):
    """Page precedence is authoritative; UTC instants resolve independent heads.

    A merged identity's first occurrence in each source supplies one ordering
    anchor. Subsequent mirror representations are audit refs, not new turns.
    An equal or missing timestamp cannot silently order unrelated page heads.
    """
    edges=[set() for _ in records]
    degrees=[0 for _ in records]
    by_source=defaultdict(list)
    instants=[];stable=[]
    for node,record in enumerate(records):
        seen_times=[]
        for ref in record.source_refs:
            by_source[ref['source']].append((ref['line'],node))
            raw=ref.get('timestamp',record.timestamp)
            if not raw:continue
            try:
                if not isinstance(raw,str) or not INSTANT.fullmatch(raw):raise ValueError('unsupported RFC3339 instant')
                parsed=datetime.fromisoformat(raw.replace('Z','+00:00')).astimezone(timezone.utc)
                seen_times.append(parsed)
            except (ValueError,OverflowError):
                audit['uncertainties'].append({'reason':'unsupported_message_timestamp',
                    'source':ref['source'],'line':ref['line'],'timestamp':raw})
        instants.append(min(seen_times) if seen_times else None)
        stable.append(min((r['source'],r['line']) for r in record.source_refs))
    constraints=[]
    for source,entries in sorted(by_source.items()):
        seen=set();sequence=[]
        for line,node in sorted(entries):
            if node not in seen:
                sequence.append(node);seen.add(node)
        for left,right in zip(sequence,sequence[1:]):
            if right not in edges[left]:edges[left].add(right);degrees[right]+=1
        constraints.append({'source':source,'first_occurrence_nodes':sequence,
                            'message_ids':[records[n].message_id for n in sequence]})
    ready={n for n,d in enumerate(degrees) if not d};ordered=[]
    while ready:
        if len(ready)>1:
            known=[n for n in ready if instants[n] is not None]
            earliest=min((instants[n] for n in known),default=None)
            tied=[n for n in known if instants[n]==earliest]
            if len(known)!=len(ready) or len(tied)!=1:
                audit['uncertainties'].append({'reason':'ambiguous_cross_source_order',
                    'message_ids':[records[n].message_id for n in sorted(ready,key=lambda n:stable[n])],
                    'refs':[records[n].source_refs for n in sorted(ready,key=lambda n:stable[n])]})
            # A deterministic diagnostic order is never represented as verified.
            node=min(ready,key=lambda n:(instants[n] is None,instants[n] or datetime.max.replace(tzinfo=timezone.utc),stable[n]))
        else:node=next(iter(ready))
        ready.remove(node);ordered.append(node)
        for target in edges[node]:
            degrees[target]-=1
            if degrees[target]==0:ready.add(target)
    if len(ordered)!=len(records):
        remaining=set(range(len(records)))-set(ordered)
        audit['uncertainties'].append({'reason':'conflicting_source_message_order',
            'message_ids':[records[n].message_id for n in sorted(remaining,key=lambda n:stable[n])]})
        ordered.extend(sorted(remaining,key=lambda n:stable[n]))
    normalized=[stamp.isoformat().replace('+00:00','Z') if stamp else '' for stamp in instants]
    audit['ordering']={'method':'source_precedence_with_utc_head_comparison_v1',
        'timestamp_format':'RFC3339 with explicit timezone; fractions up to 6 digits',
        'mirror_anchor':'first source occurrence of verified merged identity',
        'source_constraints':constraints,'ordered_nodes':ordered,
        'nodes':[{'node':n,'message_id':r.message_id,'utc_instant':normalized[n]} for n,r in enumerate(records)]}
    latest=max((stamp for stamp in instants if stamp is not None),default=None)
    activity=latest.isoformat().replace('+00:00','Z') if latest else ''
    return [records[n] for n in ordered],activity
