"""Directory statistics and bounded metadata-only reads; no historical body crawl."""
import json
import os
import re
from pathlib import Path

def signature(path):
    stat=path.stat()
    return [stat.st_size,stat.st_mtime_ns,stat.st_ino]

def inventory(root):
    return {str(p):signature(p) for p in Path(root).rglob('*.jsonl') if p.is_file()}

def header(path):
    with Path(path).open('rb') as stream:
        raw=stream.readline(65537)
    if len(raw)>65536 or not raw.endswith(b'\n'):
        raise ValueError('session_header_incomplete_or_oversized')
    obj=json.loads(raw.decode('utf-8'))
    payload=obj.get('payload',{})
    if obj.get('type')!='session_meta': raise ValueError('session_header_missing')
    cid=payload.get('id','')
    if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,128}',cid):
        raise ValueError('invalid_session_id')
    source=payload.get('source')
    internal=(isinstance(source,dict) and 'subagent' in source or
              isinstance(source,str) and source.lower().startswith('subagent'))
    if not internal and source not in ('cli','vscode','exec','app','appServer','app-server'):
        raise ValueError('unknown_session_source')
    cwd=payload.get('cwd')
    if not isinstance(cwd,str) or not Path(cwd).is_absolute(): raise ValueError('project_not_absolute')
    return {'id':cid,'project':os.path.normcase(str(Path(cwd).resolve())),
            'internal':bool(internal),'title':payload.get('title') or cid[:12]}
