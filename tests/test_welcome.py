import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import Mock
from palmanager.controller import Controller
from palmanager.store import Store
from palmanager.ui import MainWindow
from PySide6.QtWidgets import QApplication

class WelcomeTests(unittest.TestCase):
    def setUp(self):
        self.p=dict(id='world',name='Test world',welcome_enabled=True,welcome_message='Hello {player}, welcome to {world}!')
        self.c=Controller(Mock());self.r=Mock();self.c.remote=Mock(return_value=self.r);self.c.operate=Mock();self.c.listener=Mock()
    def poll(self,players):
        self.r.api.return_value={'players':players};self.c.poll_welcome(self.p)
    def test_join_rejoin_and_initial_baseline(self):
        a=dict(userId='a',name='Alice');b=dict(userId='b',name='Bob')
        self.poll([a]);self.c.operate.assert_not_called()
        self.poll([a,b]);self.c.operate.assert_called_once_with(self.p,'broadcast',message='Hello Bob, welcome to Test world!')
        self.poll([a,b]);self.assertEqual(self.c.operate.call_count,1)
        self.poll([a]);self.poll([a,b]);self.assertEqual(self.c.operate.call_count,2)
    def test_outage_preserves_roster(self):
        a=dict(userId='a',name='Alice');self.poll([a])
        self.r.api.side_effect=RuntimeError('API disabled');self.c.poll_welcome(self.p);self.c.poll_welcome(self.p)
        self.assertEqual(self.c.listener.call_count,1)
        self.r.api.side_effect=None;self.poll([a]);self.c.operate.assert_not_called()
    def test_disabled_or_worker_owned_does_not_send(self):
        for change in [{'welcome_enabled':False},{'background_enabled':True}]:
            self.c.welcome_seen['world']=set();p={**self.p,**change};self.r.api.return_value={'players':[dict(userId='a',name='Alice')]};self.c.poll_welcome(p)
        self.c.operate.assert_not_called()
    def test_worker_runner_sends(self):
        self.p.update(background_enabled=True,_background_runner=True);self.poll([]);self.poll([dict(userId='a',name='Alice')]);self.c.operate.assert_called_once()
    def test_ui_saves_toggle_and_text_per_world(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            w=MainWindow(Store(folder),offline=True);w.timer.stop()
            self.assertFalse(w.welcome_enabled.isChecked());w.welcome_message.setText('Welcome {player}!');w.welcome_enabled.setChecked(True);w.save_welcome()
            saved=Store(folder).profiles[0];self.assertTrue(saved['welcome_enabled']);self.assertEqual(saved['welcome_message'],'Welcome {player}!')
            w.welcome_enabled.setChecked(False);w.save_welcome();self.assertFalse(Store(folder).profiles[0]['welcome_enabled']);w.hide()
