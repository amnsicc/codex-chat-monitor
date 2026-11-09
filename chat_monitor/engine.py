"""Single-worker coordinator. All mutations run on that worker, GUI uses commands."""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from . import discovery
from .extract import extract
from .material import count_file
from .policy import transition
from .storage import load,dump,journal,atomic_bytes

class Engine:
    def __init__(self,config):
        self.config=dict(config)
        self.input=Path(config['sessions_root']).resolve()
        self.runtime=Path(config['runtime']).resolve()
        self.allowed={os.path.normcase(str(Path(p).resolve())) for p in config['allowed_projects']}
        if not self.input.is_dir() or not self.allowed: raise ValueError('explicit_input_and_projects_required')
        if self.runtime.is_relative_to(self.input): raise ValueError('runtime_must_be_outside_input')
        if any((Path(p)/'.codex-chat-monitor').is_relative_to(self.input) for p in self.allowed):
            raise ValueError('project_outputs_must_be_outside_input')
        if not isinstance(config.get('budget'),int) or config['budget']<=0: raise ValueError('positive_trial_budget_required')
        self.runtime.mkdir(parents=True,exist_ok=True)
        self.db=load(self.runtime/'state.json',{'chats':{},'notifications':{},'outbox':[],
            'excluded':[],'history':{},'faults':{},'source_issues':{}})
        scope={'sessions_root':os.path.normcase(str(self.input)),'allowed_projects':sorted(self.allowed)}
        if self.db.get('scope',scope)!=scope: raise ValueError('runtime_input_scope_changed; use a separate runtime')
        self.db['scope']=scope
        self.chats=self.db['chats']
        self.observed=self.db.setdefault('observed_sources', {
            cid:{path:{'project':self.chats[cid]['project']} for path in history}
            for cid,history in self.db['history'].items()})
        self.known=discovery.inventory(self.input)  # baseline only; does not open bodies
        self.pending=set(self.chats)-set(self.db['excluded'])
        self.catalog={}
        for cid in self.pending: self.invalidate(cid,'processing',[])
        self.policy=hashlib.sha256(json.dumps({k:config.get(k) for k in ('budget','encoding','reserves')},sort_keys=True).encode()).hexdigest()
        previous_policy=self.db.get('policy')
        if previous_policy!=self.policy:
            journal(self.runtime/'policy.jsonl',{'old':previous_policy,'new':self.policy,'budget':self.config['budget'],'encoding':self.config['encoding'],'calibrated':False,'unix':time.time()})
        self.db['policy']=self.policy
        self.db['outbox']=[e for e in self.db['outbox'] if e.get('policy')==self.policy or e['level']=='error']
        self.cancel_excluded_alerts()
        self.save()

    def save(self):
        self.db['updated_unix']=time.time()
        dump(self.runtime/'state.json',self.db)

    def scan(self):
        current=discovery.inventory(self.input)
        changes=[p for p,s in current.items() if self.known.get(p)!=s]
        missing=set(self.known)-set(current)
        for path in changes:
            try:
                h=discovery.header(path); self.catalog[path]=h
                self.db['faults'].pop(path,None)
                for owner,history in self.observed.items():
                    if path in history and h['id']!=owner:
                        if owner not in self.db['excluded']:
                            self.pending.add(owner)
                            self.invalidate(owner,'unverified',[{'reason':'source_identity_changed','path':path}])
                        self.catalog.pop(path,None)
                if h['internal']: continue
                cid=h['id']
                if cid not in self.chats:
                    self.chats[cid]={'id':cid,'title':h['title'],'project':h['project'],
                        'status':'processing','activity':'','issues':[]}
                self.observe_source(cid,path,h)
                if cid not in self.db['excluded']:
                    self.pending.add(cid)
                    self.invalidate(cid,'processing',[])
            except (ValueError,OSError,UnicodeError) as exc:
                self.catalog.pop(path,None)
                self.db['faults'][path]=str(exc)
                candidate=getattr(exc,'session_id',None)
                if candidate in self.chats:
                    self.observe_source(candidate,path,{'project':None})
                # Observed but unverified pages must retain their ownership too.
                for cid,history in self.observed.items():
                    if path in history:
                        if cid not in self.db['excluded']:
                            self.pending.add(cid)
                            self.invalidate(cid,'unverified',[{'reason':'source_header_changed','path':path}])
        for path in missing:
            for cid,history in self.observed.items():
                if path in history:
                    if cid not in self.db['excluded']:
                        self.pending.add(cid)
                        self.invalidate(cid,'unverified',[{'reason':'source_missing','path':path}])
        self.known=current
        if changes or missing: self.save()

    def invalidate(self,cid,status,issues):
        chat=self.chats[cid]
        had_measurement='tokens' in chat
        reference={k:chat[k] for k in ('tokens','sha256','activity','material_path','cutoff','sources','encoding','published_unix') if k in chat}
        chat={k:v for k,v in chat.items() if k not in {'tokens','remaining','percent','at_budget','over_by','sha256','material_path','sources','cutoff','encoding','published_unix'}}
        if had_measurement: chat['previous_reference']=reference
        chat.update(status=status,issues=issues,budget_label='无法判断' if status=='unverified' else status)
        self.chats[cid]=chat

    def observe_source(self,cid,path,header):
        sources=self.observed.setdefault(cid,{})
        if path not in sources:
            sources[path]={'project':header['project']}
            journal(self.runtime/'sources.jsonl',{'event':'observed','id':cid,
                'path':path,'project':header['project'],'unix':time.time()})

    def related(self,cid):
        # Only metadata heads of other logs are read to locate all pages of this ID.
        for path in self.known:
            if path not in self.catalog:
                try: self.catalog[path]=discovery.header(path)
                except (ValueError,OSError,UnicodeError) as exc:
                    if getattr(exc,'session_id',None)==cid:
                        self.observe_source(cid,path,{'project':None})
                    continue
        paths=[Path(p) for p in self.known if self.catalog.get(p,{}).get('id')==cid
                and not self.catalog[p]['internal']]
        for path in paths: self.observe_source(cid,str(path),self.catalog[str(path)])
        self.save()
        return paths

    def process_pending(self):
        for cid in sorted(self.pending.copy()):
            self.pending.discard(cid)
            if cid in self.db['excluded']: continue
            started=time.time()
            self.invalidate(cid,'processing',[]); self.save()
            journal(self.runtime/'schedule.jsonl',{'event':'start','id':cid,'unix':started})
            try:
                paths=self.related(cid)
                missing=set(self.observed.get(cid,{}))-{str(p) for p in paths}
                if missing: raise ValueError('source_missing_or_identity_changed: '+', '.join(sorted(missing)))
                if not paths: raise ValueError('no_recoverable_sources')
                signatures={str(p):discovery.signature(p) for p in paths}
                source_issues=[]
                for p in paths:
                    if self.catalog[str(p)]['project'] not in self.allowed:
                        raise ValueError('project_outside_explicit_allowlist')
                    old=self.db['history'].get(cid,{}).get(str(p))
                    if old:
                        with p.open('rb') as stream: prefix=stream.read(old['bytes'])
                        if hashlib.sha256(prefix).hexdigest()!=old['sha256']:
                            row={'reason':'source_rewritten_or_shortened','path':str(p)}
                            source_issues.append(row)
                result=extract(paths,cid)
                issues=result.issues+source_issues
                if any(discovery.signature(p)!=signatures[str(p)] for p in paths):
                    issues.append({'reason':'source_changed_during_processing'}); self.pending.add(cid)
                if result.project not in self.allowed: issues.append({'reason':'project_not_verified'})
                if issues:
                    self.invalidate(cid,'unverified',issues)
                    self.notify(cid,None,str(issues[0].get('reason','source_unverified')))
                    journal(self.runtime/'audit.jsonl',{'id':cid,'issues':issues,'unix':time.time()})
                    continue
                base=Path(result.project)/'.codex-chat-monitor'/cid/'latest'
                body=result.text.encode('utf-8')
                body_hash=hashlib.sha256(body).hexdigest()
                target=base/('material-'+body_hash+'.md')
                if not target.exists(): atomic_bytes(target,body)
                measurement=count_file(target,self.config['encoding'])
                if measurement['sha256']!=body_hash: raise ValueError('published_material_hash_mismatch')
                self.scan()
                if cid in self.pending or any(discovery.signature(p)!=signatures[str(p)] for p in paths):
                    self.pending.add(cid)
                    raise ValueError('source_changed_while_counting')
                audit_bytes=(json.dumps(result.audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                audit_target=base/('audit-'+hashlib.sha256(audit_bytes).hexdigest()+'.json')
                if not audit_target.exists(): atomic_bytes(audit_target,audit_bytes)
                value={**self.chats[cid],**measurement,'id':cid,'source_id':cid,'project':result.project,
                    'material_path':str(target),'status':'ready','issues':[],
                    'activity':result.activity,'sources':result.sources,'cutoff':result.activity,
                    'policy':self.policy,'budget':self.config['budget'],'reserves':self.config.get('reserves',{}),
                    'published_unix':time.time(),'audit_path':str(audit_target)}
                value['remaining']=max(0,value['budget']-value['tokens'])
                value['over_by']=max(0,value['tokens']-value['budget'])
                value['percent']=value['tokens']/value['budget']*100
                value['at_budget']=value['tokens']==value['budget']
                self.chats[cid]=value
                self.db['history'][cid]={s['path']:s for s in result.sources}
                value['budget_label']='已超限' if value['over_by'] else ('已到上限' if value['at_budget'] else '预算内')
                self.notify(cid,value['tokens'])
                journal(self.runtime/'publications.jsonl',value)
            except Exception as exc:
                self.invalidate(cid,'unverified',[{'reason':type(exc).__name__+': '+str(exc)}])
                self.notify(cid,None,str(exc))
            finally:
                self.save()
                journal(self.runtime/'schedule.jsonl',{'event':'end','id':cid,'unix':time.time(),
                    'elapsed_ms':(time.time()-started)*1000,'status':self.chats[cid]['status']})

    def notify(self,cid,tokens,problem=None):
        previous=self.db['notifications'].get(cid,{})
        if tokens is not None and previous.get('faults'):
            journal(self.runtime/'alerts.jsonl',{'event':'recovered','chat_id':cid,
                'faults':previous['faults'],'cutoff':self.chats[cid].get('cutoff'),
                'sha256':self.chats[cid].get('sha256'),'unix':time.time()})
        state,event=transition(self.db['notifications'].get(cid,{}),tokens,self.policy,self.config['budget'],problem)
        self.db['notifications'][cid]=state
        if event:
            event.update(id=uuid.uuid4().hex,chat_id=cid,title=self.chats[cid]['title'],unix=time.time())
            event['policy']=self.policy
            if event['level']!='error':
                superseded=[e for e in self.db['outbox'] if e['chat_id']==cid and e['level']!='error']
                for old in superseded:
                    journal(self.runtime/'alerts.jsonl',{'event':'superseded','id':old['id'],'by':event['id'],'unix':time.time()})
                self.db['outbox']=[e for e in self.db['outbox'] if e not in superseded]
            self.db['outbox'].append(event)
            journal(self.runtime/'alerts.jsonl',{'event':'queued',**event})

    def cancel_excluded_alerts(self):
        cancelled=[event for event in self.db['outbox'] if event['chat_id'] in self.db['excluded']]
        for event in cancelled:
            journal(self.runtime/'alerts.jsonl',{'event':'cancelled','id':event['id'],
                'chat_id':event['chat_id'],'reason':'chat_excluded','unix':time.time()})
        if cancelled:
            self.db['outbox']=[event for event in self.db['outbox'] if event not in cancelled]
            self.save()

    def outbox(self):
        self.cancel_excluded_alerts()
        return list(self.db['outbox'])

    def ack(self,event_id,receipt):
        event=next(e for e in self.db['outbox'] if e['id']==event_id)
        self.db['outbox']=[e for e in self.db['outbox'] if e['id']!=event_id]
        journal(self.runtime/'alerts.jsonl',{'event':'delivered','id':event_id,'chat_id':event['chat_id'],
            'receipt':receipt,'unix':time.time()})
        self.save()

    def exclude(self,cid,excluded):
        values=set(self.db['excluded'])
        if excluded:
            values.add(cid); self.pending.discard(cid); self.invalidate(cid,'excluded',[])
        else:
            values.discard(cid); self.pending.add(cid); self.invalidate(cid,'processing',[])
        self.db['excluded']=sorted(values)
        self.cancel_excluded_alerts()
        self.save()
