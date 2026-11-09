import os
import subprocess
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from .storage import load,dump,journal

def clamp_position(x,y,w,h,sw,sh):
    return max(0,min(x,max(0,sw-w))),max(0,min(y,max(0,sh-h)))

def display_chat(chat):
    status=chat.get('status')
    if status=='processing': return '处理中 · 当前用量待更新'
    if status=='excluded': return '已排除 · 监控暂停'
    if status!='ready': return '无法判断 · '+str(chat.get('issues',[])[:1])
    label='已超限 '+str(chat.get('over_by',0)) if chat.get('over_by',0)>0 else '已到上限' if chat.get('at_budget') else '余量 '+str(chat['remaining'])
    return f"已更新 · {chat['tokens']:,} / {chat['budget']:,} token · {chat['percent']:.1f}% · {label}"

class Window:
    def __init__(self,service):
        self.service=service; self.runtime=service.runtime
        self.root=tk.Tk(); self.root.title('Codex 纯聊天监控 · 隔离试用')
        self.settings=load(self.runtime/'ui.json',{})
        self.root.geometry('820x420'); self.root.minsize(620,320)
        self.root.attributes('-topmost',self.settings.get('topmost',True))
        x,y=clamp_position(self.settings.get('x',50),self.settings.get('y',70),820,420,
            self.root.winfo_screenwidth(),self.root.winfo_screenheight())
        self.root.geometry(f'+{x}+{y}')
        self.drag=None; self.dialog=None; self.dialog_ids=[]; self.toast_jobs={}; self.seen=set(); self.failed=set(); self.active_events={}
        self.cancel_jobs={}
        self.cancel_failures={}
        self.cancel_checked=set()
        self.refresh_callback=None
        self.closing=False
        self.hidden=False
        bar=ttk.Frame(self.root); bar.pack(fill='x',padx=10,pady=6)
        grip=ttk.Label(bar,text='⠿ Codex 纯聊天监控',font=('Microsoft YaHei UI',12,'bold')); grip.pack(side='left')
        grip.bind('<ButtonPress-1>',self.drag_start); grip.bind('<B1-Motion>',self.drag_move)
        ttk.Label(bar,text='显示数量').pack(side='left',padx=(20,4))
        self.count=tk.IntVar(value=self.settings.get('count',5))
        ttk.Spinbox(bar,from_=1,to=100,textvariable=self.count,width=4,command=self.save_settings).pack(side='left')
        self.top=tk.BooleanVar(value=self.settings.get('topmost',True))
        ttk.Checkbutton(bar,text='置顶',variable=self.top,command=self.toggle_top).pack(side='right')
        self.all_chats=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text='全部 / 含排除',variable=self.all_chats).pack(side='right')
        ttk.Label(self.root,text='encoding '+service.config['encoding']+' · 估算 / 试用 / 未校准 · 最近活跃按聊天正文更新 · 隐藏后仍监控',foreground='#8a4b00').pack(anchor='w',padx=10)
        self.table=ttk.Treeview(self.root,columns=('title','project','usage'),show='headings',selectmode='browse')
        for name,label,width in [('title','聊天 / 身份',150),('project','源项目',180),('usage','用量与处理状态',440)]:
            self.table.heading(name,text=label); self.table.column(name,width=width,minwidth=80)
        self.table.pack(fill='both',expand=True,padx=10,pady=8)
        buttons=ttk.Frame(self.root); buttons.pack(fill='x',padx=10,pady=5)
        ttk.Button(buttons,text='准备蒸馏（阶段4）',state='disabled').pack(side='left')
        for text,fn in [('排除',lambda:self.exclude(True)),('恢复',lambda:self.exclude(False)),
                        ('查看日志',lambda:os.startfile(self.runtime)),('隐藏',self.hide),('退出',self.quit)]:
            ttk.Button(buttons,text=text,command=fn).pack(side='left',padx=3)
        self.status=ttk.Label(self.root,text='等待启动后新增或再次活动的聊天'); self.status.pack(anchor='w',padx=10,pady=5)
        self.detail=ttk.Label(self.root,text='',wraplength=780)
        self.detail.pack(anchor='w',padx=10)
        self.table.bind('<<TreeviewSelect>>',self.show_details)
        self.root.protocol('WM_DELETE_WINDOW',self.hide)
        self.root.bind('<Configure>',self.save_settings)
        self.refresh_callback=self.root.after(200,self.refresh)

    def toggle_top(self):
        self.root.attributes('-topmost',self.top.get()); self.save_settings()

    def drag_start(self,event): self.drag=(event.x_root-self.root.winfo_x(),event.y_root-self.root.winfo_y())
    def drag_move(self,event):
        if self.drag:self.root.geometry(f'+{event.x_root-self.drag[0]}+{event.y_root-self.drag[1]}')
    def save_settings(self,event=None):
        if event is not None and event.widget!=self.root:return
        try:
            dump(self.runtime/'ui.json',{'x':self.root.winfo_x(),'y':self.root.winfo_y(),
                'count':max(1,min(100,self.count.get())),'topmost':self.top.get()})
        except (tk.TclError,ValueError):pass
    def selected(self):
        items=self.table.selection()
        return items[0] if items else None
    def show_details(self,event=None):
        cid=self.selected()
        chat=load(self.runtime/'state.json',{}).get('chats',{}).get(cid)
        self.detail.configure(text=f"ID {cid} · 项目 {chat['project']}" if chat else '')
    def exclude(self,value):
        cid=self.selected()
        if cid:self.service.commands.put({'action':'exclude','id':cid,'value':value})
    def prepare(self):
        cid=self.selected()
        if cid:self.service.commands.put({'action':'prepare','id':cid})
    def hide(self):
        self.hidden=True; self.root.withdraw()
        journal(self.runtime/'ui-events.jsonl',{'event':'hidden','unix':time.time()})
    def quit(self):
        if self.closing:return
        try:self.save_settings()
        finally:self.shutdown()
    def shutdown(self):
        if self.closing:return
        self.closing=True
        self.service.stop.set()
        if self.refresh_callback:
            self.root.after_cancel(self.refresh_callback)
            self.refresh_callback=None
        try:
            for job in [*self.toast_jobs.values(),*self.cancel_jobs.values()]:
                if job.poll() is None:
                    job.terminate()
                    try:job.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        job.kill();job.wait(timeout=5)
        finally:
            try:
                close=getattr(self.service,'close',None)
                if close:close()
            finally:self.root.destroy()
    def show(self):
        self.hidden=False; self.root.deiconify(); self.root.lift()
    def refresh(self):
        self.refresh_callback=None
        try:self.update_view()
        finally:
            if not self.closing:
                self.refresh_callback=self.root.after(300,self.refresh)
    def update_view(self):
        if self.service.stop.is_set():
            self.shutdown(); return
        if (self.runtime/'show.request').exists():
            (self.runtime/'show.request').unlink(); self.show()
        state=load(self.runtime/'state.json',{'chats':{},'outbox':[]})
        selected=self.selected()
        try:limit=max(1,min(100,self.count.get()))
        except (ValueError,tk.TclError):limit=5
        rows=sorted(state['chats'].values(),key=lambda v:v.get('activity',''),reverse=True)
        if not self.all_chats.get(): rows=[c for c in rows if c['status']!='excluded'][:limit]
        self.table.delete(*self.table.get_children())
        for c in rows:self.table.insert('',tk.END,iid=c['id'],values=(c['title']+' · '+c['id'],c['project'],display_chat(c)))
        if selected in self.table.get_children():self.table.selection_set(selected)
        self.status.configure(text=f"监控 {len(state['chats'])} 个聊天 · 显示 {len(rows)} 个 · 元数据故障 {len(state.get('faults',{}))} · 通知提交失败 {len(self.failed)} · 取消失败 {len(self.cancel_failures)}"+(' · 查看日志 ui-events.jsonl' if self.cancel_failures else ''))
        while not self.service.replies.empty():
            reply=self.service.replies.get_nowait()
            if reply['action']=='prepared':self.prepared(reply['path'])
            else:messagebox.showerror('无法完成',reply.get('error','未知错误'),parent=self.root)
        self.active_events={e['id']:e for e in state['outbox']}
        from .notifications import cancel_toast
        for eid,job in self.toast_jobs.items():
            if eid not in self.active_events and eid not in self.seen and eid not in self.cancel_jobs and eid not in self.cancel_failures:
                try:
                    if job.poll() is None:job.terminate();job.wait(timeout=5)
                    self.cancel_jobs[eid]=cancel_toast(eid,self.runtime)
                except (OSError,subprocess.TimeoutExpired) as exc:
                    self.cancel_failed(eid,str(exc))
        for eid,job in self.cancel_jobs.items():
            if eid in self.cancel_checked or job.poll() is None:continue
            self.cancel_checked.add(eid)
            receipt=load(self.runtime/'delivery'/f'{eid}.cancel.json',{})
            if job.returncode!=0 or not receipt.get('removal_submitted'):
                self.cancel_failed(eid,str(receipt.get('error','cancel helper failed or receipt missing')))
        invalid=set(self.dialog_ids)-set(self.active_events)
        if invalid:
            journal(self.runtime/'ui-events.jsonl',{'event':'confirmation_invalidated','ids':sorted(invalid),'unix':time.time()})
            self.dialog_ids=[eid for eid in self.dialog_ids if eid in self.active_events]
            self.redraw_dialog()
        self.deliver(state['outbox'])
        if not self.hidden:
            x,y=clamp_position(self.root.winfo_x(),self.root.winfo_y(),self.root.winfo_width(),self.root.winfo_height(),self.root.winfo_screenwidth(),self.root.winfo_screenheight())
            if (x,y)!=(self.root.winfo_x(),self.root.winfo_y()):self.root.geometry(f'+{x}+{y}')
    def cancel_failed(self,eid,error):
        self.cancel_failures[eid]=error
        journal(self.runtime/'ui-events.jsonl',{'event':'toast_cancel_failed','id':eid,
            'error':error,'removal_submitted':False,'unix':time.time()})
    def prepared(self,path):
        text=(Path(path)/'launch.txt').read_text(encoding='utf-8')
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()
        messagebox.showinfo('准备包已固定',f'启动指令已复制。请在同项目新聊天发送。\n{path}\n\n真实跨窗口读取尚需验收。',parent=self.root)
    def deliver(self,events):
        from .notifications import toast
        for event in events:
            if event['id'] in self.seen or event['id'] in self.failed:continue
            if event['level'] in {'50','75'}:
                job=self.toast_jobs.get(event['id'])
                if job is None:
                    try:self.toast_jobs[event['id']]=toast(event,self.runtime)
                    except OSError as exc:
                        self.failed.add(event['id'])
                        journal(self.runtime/'ui-events.jsonl',{'event':'toast_submission_failed','id':event['id'],'error':str(exc),'unix':time.time()})
                    continue
                if job.poll() is None:continue
                receipt=load(self.runtime/'delivery'/f"{event['id']}.json",{})
                if job.returncode==0 and receipt.get('submitted'):
                    self.service.commands.put({'action':'ack','id':event['id'],'receipt':receipt}); self.seen.add(event['id'])
                else:
                    # Keep the outbox entry; show explicit failure, avoid a tight retry storm.
                    self.failed.add(event['id'])
                    journal(self.runtime/'ui-events.jsonl',{'event':'toast_submission_failed','id':event['id'],'receipt':receipt,'unix':time.time()})
                continue
            self.open_dialog(event)
    def open_dialog(self,event):
        if event['id'] in self.dialog_ids:return
        if self.dialog is None:
            self.dialog=tk.Toplevel(self.root); self.dialog.title('Codex 材料预算提醒 · 请确认')
            self.dialog.attributes('-topmost',True); self.dialog.geometry('620x300+120+120')
            self.dialog.protocol('WM_DELETE_WINDOW',lambda:None)
            ttk.Label(self.dialog,text='材料预算提醒',font=('Microsoft YaHei UI',16,'bold')).pack(pady=12)
            self.dialog_text=tk.Text(self.dialog,height=8,wrap='word'); self.dialog_text.pack(fill='both',expand=True,padx=15)
            ttk.Button(self.dialog,text='我已知晓，继续监控',command=self.confirm).pack(pady=10)
        label='来源或计数无法判断' if event['level']=='error' else '已经超限' if event['level']=='over' else '接近预算（90%）'
        body=f"{event['title']} [{event['chat_id'][:12]}]：{label}；{event.get('tokens','?')} / {event.get('budget','?')}\n"
        if event['level']=='error':body+=str(event.get('reason',''))+'\n'
        if event['level']=='over':body+='一次长消息可能直接越界；监控没有提前阻止聊天。\n'
        self.dialog_text.insert(tk.END,body); self.dialog_ids.append(event['id'])
        self.dialog.deiconify(); self.dialog.lift()
        journal(self.runtime/'ui-events.jsonl',{'event':'confirmation_shown','id':event['id'],'body':body,'unix':time.time()})
    def redraw_dialog(self):
        if not self.dialog:return
        if not self.dialog_ids:
            self.dialog.destroy();self.dialog=None;return
        self.dialog_text.delete('1.0',tk.END)
        for eid in self.dialog_ids:
            event=self.active_events[eid]
            label={'over':'已超限','90':'接近预算（90%）','error':'无法判断'}.get(event['level'],event['level'])
            self.dialog_text.insert(tk.END,f"{event['title']} [{event['chat_id']}] {label} {event.get('tokens','?')} / {event.get('budget','?')} {event.get('reason','')}\n")

    def confirm(self,automated=False):
        current=load(self.runtime/'state.json',{}).get('outbox',[])
        valid={e['id'] for e in current}
        confirmed=[eid for eid in self.dialog_ids if eid in valid]
        for eid in confirmed:
            self.service.commands.put({'action':'ack','id':eid,'receipt':{'confirmed_by_user':not automated,'interaction':'automation' if automated else 'human','unix':time.time()}})
            self.seen.add(eid)
        journal(self.runtime/'ui-events.jsonl',{'event':'confirmed','ids':confirmed,'interaction':'automation' if automated else 'human','unix':time.time()})
        if self.dialog:self.dialog.destroy()
        self.dialog=None; self.dialog_ids=[]

    def run(self):self.root.mainloop()
