"""Connection UX regression tests; no network access."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication,QLineEdit,QLabel,QFormLayout
from palmanager.ui import MainWindow,ProfileDialog,STYLE
from palmanager.store import Store,DEFAULT_PROFILE
from palmanager.remote import Remote
from unittest.mock import patch

class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyleSheet(STYLE)
    def test_labeled_visible_independent_passwords(self):
        dialog=ProfileDialog(None,DEFAULT_PROFILE,{'password':'steam-example','admin_password':'admin-example','api_password':'api-example'})
        labels={w.text() for w in dialog.findChildren(QLabel)}
        self.assertIn('Steam / server owner password',labels);self.assertIn('Administrator SSH / sudo password',labels)
        for widget in list(dialog.fields.values())+list(dialog.credential_fields.values()):
            self.assertTrue(widget.accessibleName());self.assertEqual(widget.echoMode(),QLineEdit.Normal)
        self.assertEqual(dialog.credential_fields['password'].text(),'steam-example');self.assertEqual(dialog.credential_fields['admin_password'].text(),'admin-example')
        dialog.close()
    def test_distinct_account_credentials_reach_ssh(self):
        remote=Remote(DEFAULT_PROFILE,{'password':'steam-example','admin_password':'admin-example'})
        with patch('palmanager.remote.paramiko.SSHClient') as factory:
            remote.connect();self.assertEqual(factory.return_value.connect.call_args.kwargs['username'],'steam');self.assertEqual(factory.return_value.connect.call_args.kwargs['password'],'steam-example')
            remote.connect(True);self.assertEqual(factory.return_value.connect.call_args.kwargs['username'],DEFAULT_PROFILE['admin_user']);self.assertEqual(factory.return_value.connect.call_args.kwargs['password'],'admin-example')
    def test_passwords_encrypted_and_reload_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);secrets={'password':'steam-example-distinct','admin_password':'admin-example-distinct','api_password':'api-example-distinct'}
            store.set_credentials(store.profiles[0]['id'],secrets);store.save()
            for file in Path(folder).iterdir():
                for value in secrets.values():self.assertNotIn(value.encode(),file.read_bytes())
            self.assertEqual(Store(folder).credentials(store.profiles[0]['id']),secrets)
    def test_activity_success_and_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.set_credentials(store.profiles[0]['id'],{'password':'memory-only'},False)
            window=MainWindow(store,offline=True);window.timer.stop();window.offline=False
            class Fixture:
                fail=False
                def call(self,action,args=None):
                    if self.fail:raise RuntimeError('fixture connection refused')
                    if action=='logs':return []
                    return dict(ActiveState='active',MemoryCurrent='1024',MainPID='12',NRestarts='0',disk={'free':1024**3})
                def worker_status(self):return {'installed':False}
                def api(self,*args):raise RuntimeError('REST API is disabled')
            fixture=Fixture();window.controller.remote=lambda _:fixture
            def finish():
                deadline=time.monotonic()+5
                while window.polling and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
                self.app.processEvents();self.assertFalse(window.polling)
            window.connect_now();self.assertIn('Connecting to',window.activity.toPlainText());finish()
            text=window.activity.toPlainText();self.assertIn('Authenticating SSH',text);self.assertIn('REST API is disabled',text);self.assertIn('Refresh complete',text)
            fixture.fail=True;window.connect_now();finish();self.assertIn('Connection / refresh failed: fixture connection refused',window.activity.toPlainText());self.assertNotIn('memory-only',window.activity.toPlainText());window.hide()

    def test_add_message_schedule_from_dialog(self):
        from PySide6.QtWidgets import QDialog,QComboBox
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);window=MainWindow(store,offline=True);window.timer.stop()
            def fill(dialog):
                action=next(combo for combo in dialog.findChildren(QComboBox) if combo.findData('broadcast')>=0);action.setCurrentIndex(action.findData('broadcast'))
                message=next(field for field in dialog.findChildren(QLineEdit) if field.maxLength()==500);self.assertTrue(message.isEnabled());message.setText('Downtime starts at 04:00.');return QDialog.Accepted
            with patch.object(QDialog,'exec',fill):window.add_schedule()
            schedule=store.profiles[0]['schedules'][-1];self.assertEqual(schedule['action'],'broadcast');self.assertEqual(schedule['message'],'Downtime starts at 04:00.');self.assertEqual(window.schedule_table.item(window.schedule_table.rowCount()-1,1).text(),schedule['message']);window.hide()

    def test_player_location_column_preserves_identity_and_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            window=MainWindow(Store(folder),offline=True);window.timer.stop();window.p['coordinate_space']='map';window.players_data=[dict(name='Player',userId='steam_test',location_x=77,location_y=-489)];window.render_players()
            self.assertEqual(window.player_table.item(0,1).text(),'Near Small Settlement');self.assertEqual(window.player_table.item(0,3).text(),'steam_test');self.assertEqual(window.player_table.item(0,6).text(),'77');self.assertEqual(window.player_table.item(0,7).text(),'-489');self.assertIn('Approximate',window.player_table.item(0,1).toolTip());window.hide()

    def test_worker_status_ignores_local_enabled_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            window=MainWindow(Store(folder),offline=True);window.timer.stop();window.p['background_enabled']=False
            states=[({'installed':False},'Not installed'),({'installed':True,'active':'inactive','enabled':'disabled','unit':'worker.service'},'Installed · Stopped'),({'installed':True,'active':'active','enabled':'enabled','unit':'worker.service','health':{'busy':False}},'Installed · Running'),({'error':'Network unavailable'},'Status unavailable')]
            for state,expected in states:
                window.worker_states[window.p['id']]=state;window.render_schedule();self.assertIn(expected,window.worker_status_label.text())
            self.assertFalse(window.p['background_enabled']);window.hide()

if __name__=='__main__':unittest.main()
