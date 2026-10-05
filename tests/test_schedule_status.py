import copy,os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QCheckBox
from palmanager.schedule_status import publication,remote_only
from palmanager.store import Store
from palmanager.ui import MainWindow

class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.s=dict(id='test',action='broadcast',message='Maintenance soon',mode='interval',minutes=10,at='04:00',enabled=True,next=123)
        self.p=dict(schedules=[self.s],schedule_timezone='America/New_York')
        self.state=dict(installed=True,unit="fixture.service",active="active",health=dict(schedules=[copy.deepcopy(self.s)],schedule_timezone='America/New_York'))
    def test_matching_ignores_runtime(self):
        self.state['health']['schedules'][0]['next']=999
        self.assertEqual(publication(self.s,self.p,self.state),'Published')
    def test_edits_pending(self):
        for field,value in dict(action='backup',message='Changed',mode='daily',minutes=20,at='05:00',enabled=False).items():
            changed={**self.s,field:value}
            self.assertEqual(publication(changed,self.p,self.state),'Changes pending',field)
        self.p['schedule_timezone']='UTC'
        self.assertEqual(publication(self.s,self.p,self.state),'Changes pending')
    def test_unavailable_and_absent(self):
        for state in [None,{'error':'Offline'},{'installed':True},{'installed':True,'health':{}}]:
            self.assertEqual(publication(self.s,self.p,state),'Not verified')
        self.assertEqual(publication(self.s,self.p,{'installed':False}),'Not published')
        self.state['health']['schedules']=[]
        self.assertEqual(publication(self.s,self.p,self.state),'Not published')
    def test_removed_remote_tasks(self):
        self.p['schedules']=[]
        self.assertEqual(remote_only(self.p,self.state),[self.s])
        self.state['error']='Offline'
        self.assertEqual(remote_only(self.p,self.state),[])
    def test_edit_and_cancel_keep_identity(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            window=MainWindow(Store(folder),offline=True);window.timer.stop()
            window.p.update(copy.deepcopy(self.p));window.worker_states[window.p['id']]=self.state;window.render_schedule();window.schedule_table.selectRow(0)
            self.assertEqual(window.schedule_table.item(0,5).text(),'Published')
            with patch.object(QDialog,'exec',lambda d:QDialog.Rejected):window.edit_schedule()
            self.assertEqual(window.p['schedules'][0],self.s)
            with patch.object(QDialog,'exec',lambda d:QDialog.Accepted):window.edit_schedule()
            self.assertEqual(window.p['schedules'][0],self.s)
            def fill(dialog):
                field=next(f for f in dialog.findChildren(QLineEdit) if f.maxLength()==500)
                self.assertEqual(field.text(),self.s['message']);field.setText('New warning')
                dialog.findChild(QCheckBox).setChecked(False)
                return QDialog.Accepted
            with patch.object(QDialog,'exec',fill):window.edit_schedule()
            self.assertEqual(len(window.p['schedules']),1);self.assertEqual(window.p['schedules'][0]['id'],'test')
            self.assertEqual(window.schedule_table.item(0,5).text(),'Changes pending')
            self.assertFalse(Store(folder).profiles[0]['schedules'][0]['enabled'])
            self.state['health']['schedules']=copy.deepcopy(window.p['schedules']);window.render_schedule()
            self.assertEqual(window.schedule_table.item(0,5).text(),'Published');self.assertEqual(window.schedule_table.currentRow(),0)
            window.remove_schedule();self.assertIn('1 task(s)',window.schedule_sync_note.text());window.hide()

if __name__=='__main__':unittest.main()

