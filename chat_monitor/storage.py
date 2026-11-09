import json
import os
import uuid
import time
from pathlib import Path

def load(path, default=None):
    for attempt in range(7):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            return default
        except PermissionError as exc:
            if attempt==6:
                raise
            time.sleep(.01 * (2**attempt))

def atomic_bytes(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.parent/('.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        for attempt in range(7):
            try:
                os.replace(tmp,path)
                break
            except PermissionError as exc:
                # Windows readers can briefly deny DELETE sharing on the target.
                if getattr(exc,'winerror',None) not in {5,32,33} or attempt==6: raise
                time.sleep(.01 * (2**attempt))
    finally:
        tmp.unlink(missing_ok=True)

def dump(path, value):
    atomic_bytes(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))

def journal(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,ensure_ascii=False)+'\n'); stream.flush()
