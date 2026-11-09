import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from chat_monitor.runtime import InstanceLock
from chat_monitor.gui import display_chat, clamp_position

class RuntimeTests(unittest.TestCase):
    def test_fault_and_processing_never_display_current_safe_numbers(self):
        for status in ['processing','unverified','excluded']:
            text=display_chat({'id':'c','status':status,'tokens':10,'remaining':90,
                'percent':10,'issues':[{'reason':'SOURCE_ERROR'}]})
            self.assertNotIn('余量',text)
            self.assertIn({'processing':'处理中','unverified':'无法判断','excluded':'已排除'}[status],text)
        text=display_chat({'id':'c','status':'ready','tokens':100,'remaining':0,'budget':100,
            'percent':100,'over_by':0,'at_budget':True})
        self.assertIn('已到上限',text); self.assertNotIn('已超限',text)
        self.assertEqual(clamp_position(-9000,9000,600,300,1920,1080),(0,780))

    def test_other_process_cannot_acquire_same_runtime_until_release(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'monitor.lock'
            code='from chat_monitor.runtime import InstanceLock; import sys; lock=InstanceLock(sys.argv[1]); lock.acquire(); lock.close()'
            lock=InstanceLock(path); lock.acquire()
            try:
                result=subprocess.run([sys.executable,'-B','-c',code,str(path)],capture_output=True)
                self.assertNotEqual(result.returncode,0)
            finally: lock.close()
            result=subprocess.run([sys.executable,'-B','-c',code,str(path)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
