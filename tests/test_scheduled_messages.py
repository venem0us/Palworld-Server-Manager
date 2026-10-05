import tempfile,threading,time,unittest
from palmanager.store import Store
from palmanager.controller import Controller

class ScheduledMessageTests(unittest.TestCase):
 def test_message_dispatches_on_windows_and_ubuntu(self):
  for worker in (False,True):
   with self.subTest(worker=worker),tempfile.TemporaryDirectory() as folder:
    store=Store(folder);p=store.profiles[0];p['_background_runner']=worker;p['background_enabled']=worker
    p['schedules']=[dict(id='warning',action='broadcast',message='Maintenance in 10 minutes.',mode='interval',minutes=60,next=time.time()-1,enabled=True)]
    controller=Controller(store);calls=[];ready=threading.Event()
    def operate(profile,action,**kwargs):calls.append((action,kwargs));ready.set()
    controller.operate=operate;controller.tick();self.assertTrue(ready.wait(2));self.assertEqual(calls,[('broadcast',{'message':'Maintenance in 10 minutes.'})]);self.assertGreater(p['schedules'][0]['next'],time.time())
    controller.tick();self.assertEqual(len(calls),1)
 def test_existing_backup_has_no_message_argument(self):
  with tempfile.TemporaryDirectory() as folder:
   store=Store(folder);p=store.profiles[0];p['schedules']=[dict(id='backup',action='backup',mode='interval',minutes=60,next=1,enabled=True)]
   controller=Controller(store);ready=threading.Event();calls=[]
   def operate(profile,action,**kwargs):calls.append((action,kwargs));ready.set()
   controller.operate=operate;controller.tick();self.assertTrue(ready.wait(2));self.assertEqual(calls,[('backup',{})])
