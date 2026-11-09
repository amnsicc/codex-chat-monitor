import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from .engine import Engine
from .storage import load,dump,journal

class InstanceLock:
    def __init__(self,path): self.path=Path(path); self.stream=None
    def acquire(self):
        import msvcrt
        self.path.parent.mkdir(parents=True,exist_ok=True)
        stream=self.path.open('a+b'); stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            stream.close(); raise RuntimeError('monitor_already_running_for_runtime')
        self.stream=stream
    def close(self):
        if self.stream:
            import msvcrt
            self.stream.seek(0); msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            self.stream.close(); self.stream=None

class Service:
    def __init__(self,config,headless=False):
        self.config=config; self.runtime=Path(config['runtime']).resolve()
        self.lock=InstanceLock(self.runtime/'monitor.lock'); self.lock.acquire()
        try: self.engine=Engine(config)
        except Exception:
            self.lock.close(); raise
        self.commands=queue.Queue(); self.replies=queue.Queue()
        self.stop=threading.Event(); self.headless=headless
        self.watcher=None; self.watch_log=None; self.thread=None

    def start(self):
        (self.runtime/'stop.request').unlink(missing_ok=True)
        app=Path(__file__).resolve().parents[1]
        watch=list((app/'vendor/watcher').rglob('watchexec.exe'))
        if not watch: raise RuntimeError('vendored_watchexec_missing')
        argv=[str(watch[0]),'--watch',str(self.engine.input),'--filter','*.jsonl',
            '--project-origin',str(self.engine.input),'--no-discover-ignore','--no-default-ignore',
            '--fs-events','create,remove,rename,modify','--debounce','150ms','--on-busy-update','queue',
            '--shell','none','--quiet','--',sys.executable,'-B',str(app/'scripts/wake.py'),str(self.runtime/'wake')]
        self.watch_log=(self.runtime/'watcher.log').open('ab')
        self.watcher=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=self.watch_log,stderr=self.watch_log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        dump(self.runtime/'process.json',{'pid':os.getpid(),'watcher_pid':self.watcher.pid,
            'status':'running','started_unix':time.time(),'argv':argv,'headless':self.headless})
        self.thread=threading.Thread(target=self.run,name='chat-monitor-worker',daemon=False); self.thread.start()

    def run(self):
        last_scan=0; last_wake=None; retry_at=0
        try:
            while not self.stop.wait(.1):
                if (self.runtime/'stop.request').exists(): break
                now=time.monotonic()
                try: wake=(self.runtime/'wake').stat().st_mtime_ns
                except FileNotFoundError: wake=None
                if wake!=last_wake or now-last_scan>=1:
                    journal(self.runtime/'watch-events.jsonl',{'event':'scan','reason':'watcher' if wake!=last_wake else 'fallback','wake':wake,'unix':time.time()})
                    self.engine.scan(); last_scan=now; last_wake=wake
                for path in sorted((self.runtime/'commands').glob('*.json')):
                    self.commands.put({**load(path), '_receipt':str(self.runtime/'receipts'/path.name)})
                    path.unlink()
                while not self.commands.empty():
                    command=self.commands.get_nowait()
                    try:
                        action=command['action']
                        if action=='exclude': self.engine.exclude(command['id'],command['value'])
                        elif action=='ack': self.engine.ack(command['id'],command['receipt'])
                        elif action=='prepare':
                            from .prepare import prepare
                            # Refresh before trusting a previously displayed measurement.
                            self.engine.scan(); self.engine.process_pending()
                            value=prepare(self.engine.chats[command['id']])
                            self.replies.put({'action':'prepared','path':str(value)})
                        if '_receipt' in command: dump(command['_receipt'],{'ok':True,'unix':time.time()})
                    except Exception as exc:
                        if '_receipt' in command: dump(command['_receipt'],{'ok':False,'error':str(exc)})
                        self.replies.put({'action':'error','error':str(exc)})
                if now>=retry_at:
                    # Retry unsettled half lines without requiring another filesystem event.
                    self.engine.pending.update(cid for cid,v in self.engine.chats.items()
                        if v['status']=='unverified' and cid not in self.engine.db['excluded'])
                    retry_at=now+2
                self.engine.process_pending()
                if self.headless:
                    for event in self.engine.outbox():
                        receipt=self.runtime/'events'/(event['id']+'.json')
                        if not receipt.exists(): dump(receipt,event)
                        self.engine.ack(event['id'],{'delivery':'structured_event_file','path':str(receipt)})
                if self.watcher.poll() is not None:
                    raise RuntimeError('native_watcher_exited: '+str(self.watcher.returncode))
        except Exception as exc:
            dump(self.runtime/'fatal.json',{'error':str(exc),'unix':time.time()})
            self.replies.put({'action':'fatal','error':str(exc)})
        finally:
            self.stop.set()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=30)
        if self.thread and self.thread.is_alive(): raise RuntimeError('worker_did_not_stop')
        # The GUI may exit immediately after mapping a card. Persist its queued
        # receipt after joining the worker, so the next launch cannot resend it.
        while not self.commands.empty():
            command=self.commands.get_nowait()
            if command['action']=='ack':
                self.engine.ack(command['id'],command['receipt'])
            elif command['action']=='exclude':
                self.engine.exclude(command['id'],command['value'])
        if self.watcher and self.watcher.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(self.watcher.pid),'/T','/F'],capture_output=True)
            else: self.watcher.terminate()
            try:self.watcher.wait(timeout=10)
            except subprocess.TimeoutExpired: self.watcher.kill(); self.watcher.wait(timeout=10)
        if self.watch_log: self.watch_log.close()
        process=load(self.runtime/'process.json',{})
        process.update(status='stopped',stopped_unix=time.time(),watcher_returncode=self.watcher.returncode if self.watcher else None)
        dump(self.runtime/'process.json',process); self.lock.close()
