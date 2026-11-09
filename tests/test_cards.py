import queue,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests import test_engine
from chat_monitor.gui import Window
from chat_monitor.runtime import Service
from tests.fixtures import meta,user,write


class CardTests(unittest.TestCase):
    setUp=test_engine.EngineTests.setUp
    def window(self):
        service=SimpleNamespace(runtime=self.root,config={'encoding':'cl100k_base'},commands=queue.Queue(),
                                replies=queue.Queue(),stop=threading.Event())
        window=Window(service);self.addCleanup(lambda:window.shutdown() if not window.closing else None)
        return window
    def event(self,level='50',eid='one'):
        return dict(id=eid,chat_id='chat',title='same',level=level,tokens=int(level),budget=100,policy='p')
    def test_cards_do_not_call_windows_toast_and_duplicate_is_ignored(self):
        w=self.window()
        with patch('chat_monitor.notifications.toast',side_effect=AssertionError('legacy Toast invoked')):
            w.deliver([self.event()]);w.deliver([self.event()])
        self.assertEqual(len(w.card_events),1)
        self.assertEqual(w.service.commands.qsize(),1)
        receipt=w.service.commands.get()['receipt']
        self.assertEqual(receipt['interaction'],'automatic')
        self.assertFalse(receipt['confirmed_by_user'])
    def test_auto_hide_and_invalidated_events(self):
        w=self.window();w.deliver([self.event()])
        w.card_events['one']['deadline_monotonic']=time.monotonic()-1
        w.update_cards({'chats':{'chat':{'status':'ready','policy':'p'}},'outbox':[]})
        self.assertIsNone(w.card)
        w.deliver([self.event('75','two')])
        w.update_cards({'chats':{'chat':{'status':'excluded'}},'outbox':[]})
        self.assertIsNone(w.card)
    def test_immediate_exit_persists_pending_display_receipt(self):
        service=Service(self.config,headless=False)
        write(self.path,[meta('chat',self.project),user('u',' x'*150)])
        service.engine.scan();service.engine.process_pending()
        event=service.engine.outbox()[0]
        service.commands.put({'action':'ack','id':event['id'],'receipt':{
            'delivery':'application_card_shown','interaction':'automatic','confirmed_by_user':False}})
        service.close()
        restarted=Service(self.config,headless=False)
        try:
            self.assertFalse(restarted.engine.outbox())
        finally:restarted.close()
    def test_many_chats_share_a_scrollable_bounded_card(self):
        w=self.window()
        events=[]
        for number in range(30):
            event=self.event(eid=str(number));event['chat_id']='chat-'+str(number)
            events.append(event)
        w.deliver(events)
        w.root.update_idletasks()
        self.assertEqual(len(w.card_events),30)
        self.assertLess(w.card.window.winfo_height(),w.card.window.winfo_screenheight())
        self.assertIn('chat-29',w.card.text.cget('text'))
