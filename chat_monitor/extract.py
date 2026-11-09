"""Adapter for the fixed classic exporter; source files are never modified."""
import hashlib
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from .ordering import reconcile_order

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'vendor/codex-exporter'))
from codex_exporter import cli
from codex_exporter.pure_chat import deduplicate

_LOCK = threading.Lock()  # upstream classic globals are deliberately serialized

@dataclass
class Extraction:
    text: str
    complete: bool
    issues: list
    audit: dict
    project: str
    source_id: str
    activity: str
    sources: list

def extract(paths: list[Path], expected_id: str) -> Extraction:
    records, issues, projects, sources = [], [], set(), []
    audit = {'merges':[], 'uncertainties':[], 'sources':[]}
    with _LOCK:
        prior = cli._MATERIAL_INTEGRITY, cli._PURE_CHAT, cli._SOURCE_TRUNCATION_POLICY
        cli._MATERIAL_INTEGRITY, cli._PURE_CHAT, cli._SOURCE_TRUNCATION_POLICY = True, True, 'preserve'
        try:
            for path in sorted(map(Path,paths),key=lambda p:str(p)):
                path = Path(path)
                before = path.stat()
                data = path.read_bytes()
                after = path.stat()
                sources.append({'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),
                    'bytes':len(data),'mtime_ns':after.st_mtime_ns,'lines':data.count(b'\n')+(1 if data and not data.endswith(b'\n') else 0)})
                if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                    issues.append({'reason':'source_changed_during_read','source':str(path)})
                try:
                    decoded = data.decode('utf-8',errors='strict')
                except UnicodeDecodeError as exc:
                    issues.append({'reason':'invalid_utf8','source':str(path),
                        'byte_offset':exc.start,'byte_end':exc.end,
                        'line':data[:exc.start].count(b'\n')+1,'detail':exc.reason})
                    continue
                group, meta = cli.parse_session(path,include_actions=False,tool_outputs='full',
                    max_tool_chars=0,strip=False,max_line_chars=0,max_repeated_lines=0,
                    source_text=decoded)
                pure = meta['_pure_audit']
                if not data.endswith(b'\n') and data:
                    issues.append({'reason':'partial_final_line','source':str(path)})
                issues += [{'source':str(path),**row} for row in pure['issues']]
                issues += [{'source':str(path),'reason':'parse_error',**row} for row in meta['_parse_errors']]
                issues += [{'source':str(path),'reason':'repaired_source',**row} for row in meta['_repaired_json_lines']]
                identities = pure['session_ids']
                if set(identities) != {expected_id}:
                    issues.append({'reason':'source_identity_conflict_or_missing','source':str(path),'ids':identities})
                for project in pure['projects']: projects.add(os.path.normcase(str(Path(project).resolve())))
                audit['sources'].append({'path':str(path),**pure})
                for rec in group:
                    for ref in rec.source_refs: ref['source'] = str(path)
                    rec.seq = len(records)+1
                    records.append(rec)
            records = deduplicate(records,audit)
            records,activity = reconcile_order(records,audit)
        finally:
            cli._MATERIAL_INTEGRITY, cli._PURE_CHAT, cli._SOURCE_TRUNCATION_POLICY = prior
    issues += audit['uncertainties']
    if len(projects) != 1: issues.append({'reason':'project_conflict_or_missing','projects':sorted(projects)})
    text = '\n\n'.join('## '+rec.role+'\n\n'+rec.text for rec in records)
    if records: text += '\n'
    audit['messages'] = [{'role':r.role,'id':r.message_id,'turn':r.turn_id,'refs':r.source_refs} for r in records]
    return Extraction(text,not issues,issues,audit,next(iter(projects)) if len(projects)==1 else '',
                      expected_id,activity,sources)
