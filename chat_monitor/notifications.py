import json
import subprocess
from pathlib import Path
from .storage import dump

def toast(event,runtime):
    runtime=Path(runtime); folder=runtime/'delivery'; folder.mkdir(exist_ok=True)
    data=folder/(event['id']+'.input.json'); receipt=folder/(event['id']+'.json')
    dump(data,{'title':'Codex 纯聊天材料 '+event['level']+'%',
        'body':f"{event['title']} [{event['chat_id'][:12]}]：{event['tokens']} / {event['budget']} token（试用预算）"})
    return subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(Path(__file__).resolve().parents[1]/'scripts/toast.ps1'),'-InputFile',str(data),'-ReceiptFile',str(receipt)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
