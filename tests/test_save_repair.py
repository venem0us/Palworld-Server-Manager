import sys,unittest,base64,tempfile,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from palmanager import save_repair as s
from palworld_save_tools.archive import FArchiveWriter,UUID
from palworld_save_tools.gvas import GvasFile,GvasHeader

OWNER='11111111-1111-1111-1111-111111111111'
OTHER='22222222-2222-2222-2222-222222222222'
PAL='33333333-3333-3333-3333-333333333333'
EXP='44444444-4444-4444-4444-444444444444'
def guid(text):return UUID(bytes.fromhex(text.replace('-','')))
def scalar(kind,value):return dict(type=kind,value=value,id=None)
def structure(name,value):return dict(type='StructProperty',struct_type=name,struct_id=guid(s.ZERO),id=None,value=value)
def gp(text):return structure('Guid',guid(text))
def arr(values):return dict(type='ArrayProperty',array_type='ByteProperty',id=None,value={'values':list(values)})
def fixture(existing=False):
    def record(key_owner,instance,owner,player=False,exp=True):
        props={'CharacterID':scalar('NameProperty','TestPal'),'NickName':scalar('StrProperty','Example'),'OwnerPlayerUId':gp(owner)}
        if player:props['IsPlayer']=scalar('BoolProperty',True)
        if exp:props[s.FIELD]=gp(EXP)
        props['Level']=scalar('IntProperty',42)
        w=FArchiveWriter();w.properties({'SaveParameter':structure('PalIndividualCharacterSaveParameter',props)});w.write(b'\x00'*24)
        return dict(key={'PlayerUId':gp(key_owner),'InstanceId':gp(instance)},value={'RawData':arr(w.bytes())})
    recs=[record(OWNER,OWNER,OWNER,True,False),record(OWNER,PAL,OWNER),record(OTHER,PAL,OTHER,False,False)]
    chars=dict(type='MapProperty',key_type='StructProperty',value_type='StructProperty',key_struct_type='StructProperty',value_struct_type='StructProperty',id=None,value=recs)
    objects=[]
    if existing:objects=[{'MapObjectId':scalar('NameProperty','Expedition'),'ConcreteModel':structure('Model',{'RawData':arr(guid(EXP).raw_bytes+b'\0'*16)})}]
    maps=dict(type='ArrayProperty',array_type='StructProperty',id=None,value=dict(prop_name='MapObjectSaveData',prop_type='StructProperty',type_name='PalMapObjectSaveData',id=guid(s.ZERO),values=objects))
    g=GvasFile();g.header=GvasHeader.load(dict(magic=0x53415647,save_game_version=3,package_file_version_ue4=522,package_file_version_ue5=1009,engine_version_major=5,engine_version_minor=1,engine_version_patch=1,engine_version_changelist=0,engine_version_branch='test',custom_version_format=3,custom_versions=[],save_game_class_name='/Script/Pal.PalWorldSaveGame'))
    g.properties={'worldSaveData':structure('PalWorldSaveData',{'CharacterSaveParameterMap':chars,'MapObjectSaveData':maps})};g.trailer=b'\0'*4
    return s.pack(g.write())

class SaveRepairTests(unittest.TestCase):
    def test_full_key_targets_one_record_and_preserves_other_copy(self):
        data=fixture();preview=s.inspect(data);self.assertEqual(len(preview['pals']),1)
        row=preview['pals'][0];self.assertTrue(row['recoverable'])
        result,report=s.repair(data,OWNER,{row['id']:EXP})
        self.assertEqual(report['recovered'],1);self.assertEqual(s.inspect(result)['pals'],[])
        self.assertEqual(s.inspect(data),preview)
    def test_existing_expedition_is_blocked(self):
        data=fixture(True);row=s.inspect(data)['pals'][0];self.assertFalse(row['recoverable'])
        with self.assertRaises(ValueError):s.repair(data,OWNER,{row['id']:EXP})
    def test_changed_selection_and_owner_are_blocked(self):
        data=fixture();row=s.inspect(data)['pals'][0]
        for owner,expected in [(OTHER,{row['id']:EXP}),(OWNER,{row['id']:OTHER}),(OWNER,{}),(OWNER,{'missing':EXP})]:
            with self.assertRaises(ValueError):s.repair(data,owner,expected)
    def test_corrupt_headers_rejected(self):
        data=fixture()
        for bad in (b'',data[:-1],data[:8]+b'PlZ2'+data[12:],b'\xff'*4+data[4:]):
            with self.assertRaises(ValueError):s.inspect(bad)
    def test_compression_roundtrip(self):
        data=fixture();self.assertEqual(s.unpack(s.pack(s.unpack(data))),s.unpack(data))

class RecoveryMaintenanceTests(unittest.TestCase):
    def test_failure_leaves_stopped_and_never_installs(self):
        from palmanager.controller import Controller
        from palmanager.store import Store
        from test_core import FakeRemote
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);c=Controller(store);r=FakeRemote();c.remote=lambda _:r;c.warning=lambda *args:None
            with patch('palmanager.save_repair.repair',side_effect=ValueError('bad save')):
                with self.assertRaises(Exception):c.operate(store.profiles[0],'recover_expedition',path='test',owner=OWNER,expected={'test':EXP})
            self.assertIn('backup',r.calls);self.assertNotIn('write_world_save',r.calls);self.assertNotIn('control:start',r.calls)
    def test_backup_fresh_read_write_restart_order(self):
        from palmanager.controller import Controller
        from palmanager.store import Store
        from test_core import FakeRemote
        data=fixture();row=s.inspect(data)['pals'][0]
        class Remote(FakeRemote):
            def call(self,action,args=None,timeout=None):
                result=super().call(action,args,timeout)
                if action=='read_world_save':return {'data':base64.b64encode(data).decode(),'hash':s.digest(data)}
                if action=='write_world_save':
                    self.fixed=base64.b64decode(args['data']);return {'hash':s.digest(self.fixed),'recovery':'recovery/Level.sav'}
                return result
        for running in (True,False):
            with tempfile.TemporaryDirectory() as d:
                store=Store(d);c=Controller(store);r=Remote();r.state='active' if running else 'inactive';c.remote=lambda _:r;c.warning=lambda *args:None
                result=c.operate(store.profiles[0],'recover_expedition',path='test',owner=OWNER,expected={row['id']:EXP})
                self.assertEqual(result['recovered'],1);self.assertEqual(s.inspect(r.fixed)['pals'],[])
                self.assertLess(r.calls.index('backup'),r.calls.index('read_world_save'))
                self.assertLess(r.calls.index('read_world_save'),r.calls.index('write_world_save'))
                self.assertEqual('control:start' in r.calls,running)

class RemoteSaveWriteTests(unittest.TestCase):
    def test_hash_guard_recovery_and_stopped_requirement(self):
        import importlib.util,types
        spec=importlib.util.spec_from_file_location('save_agent_test',Path(__file__).resolve().parents[1]/'palmanager/remote_agent.py')
        mod=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(flock=lambda *a:None,LOCK_EX=1,LOCK_NB=2)}):spec.loader.exec_module(mod)
        data=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'PalServer.sh').touch();rel='Pal/Saved/SaveGames/0/ABC/Level.sav';target=root/rel;target.parent.mkdir(parents=True);target.write_bytes(data)
            req=dict(root=d,service='test.service',action='write_world_save',args=dict(path=rel,hash=s.digest(data),data=base64.b64encode(data).decode()))
            with patch.object(mod,'status',return_value={'ActiveState':'active'}):
                with self.assertRaises(RuntimeError):mod.main(req)
            with patch.object(mod,'status',return_value={'ActiveState':'inactive'}):
                bad=copy.deepcopy(req);bad['args']['hash']='0'*64
                with self.assertRaises(RuntimeError):mod.main(bad)
                result=mod.main(req);self.assertEqual((root/result['recovery']).read_bytes(),data)
                bad=copy.deepcopy(req);bad['args']['path']='../Level.sav'
                with self.assertRaises(ValueError):mod.main(bad)
            self.assertEqual(target.read_bytes(),data)

class SaveRepairUiTests(unittest.TestCase):
    def test_selection_excludes_blocked_and_other_owner(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from palmanager.ui import MainWindow
        from palmanager.store import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Store(d),offline=True);window.timer.stop()
            row=dict(id='one',owner=OWNER,player='Example',species='Test',name='',expedition=EXP,stale=True,recoverable=True)
            window.repair_rows=[row,dict(row,id='two',recoverable=False),dict(row,id='three',owner=OTHER)]
            window.repair_owner.addItem('Example',OWNER);window.render_save_repair();window.select_recoverable()
            self.assertEqual(window.repair_table.rowCount(),2);self.assertEqual(len(window.repair_table.selectionModel().selectedRows()),1)
            window.switch_world();self.assertEqual(window.repair_rows,[]);window.close()

if __name__=='__main__':unittest.main()
