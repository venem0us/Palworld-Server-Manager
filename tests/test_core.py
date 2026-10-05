import copy,datetime,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch as mockpatch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from palmanager.settings import parse,patch,validate
from palmanager.store import Store,DEFAULT_PROFILE,protect
from palmanager.controller import Controller,next_run,render_map
from palmanager.discord_bot import permitted
from palmanager.remote import PinPolicy,normalize_fingerprint,fingerprint

INI=';keep this\r\n[/Script/Pal.PalGameWorldSettings]\r\nOptionSettings=( A = 1.000 ,ServerName="a, b \\"hi\\"",CrossplayPlatforms=(Steam,Xbox,PS5,Mac),DenyTechnologyList=("PALBOX","RepairBench"),Unknown=(Inner=(A,B)),Flag=True)\r\n; keep that\r\n[Other]\r\nKey=unchanged\r\n'

class SettingsTests(unittest.TestCase):
    def test_nested_and_quoted_values(self):
        p=parse(INI);self.assertEqual(p['CrossplayPlatforms'],'(Steam,Xbox,PS5,Mac)');self.assertEqual(p['Unknown'],'(Inner=(A,B))');self.assertEqual(len(p),6)
    def test_lossless_noop(self):self.assertEqual(INI,patch(INI,{}))
    def test_only_changed_bytes(self):self.assertEqual(patch(INI,{'A':'2.000'}),INI.replace(' A = 1.000 ',' A = 2.000 '))
    def test_append_preserves_unrelated_content(self):
        s=patch(INI,{'NewSetting':'True'});self.assertEqual(parse(s)['NewSetting'],'True');self.assertTrue(s.endswith('[Other]\r\nKey=unchanged\r\n'))
    def test_injection(self):
        for value in ['1,Bad=True','1)\n[Other]','"unclosed','(A,B','False\x00']:
            with self.assertRaises(ValueError):patch(INI,{'A':value})
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):parse('[ /wrong ]\nOptionSettings=(A=1)')
        with self.assertRaises(ValueError):parse('[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(A=1,A=2)')
    def test_boolean_and_port_validation(self):
        with self.assertRaises(ValueError):validate('Flag','maybe','True')
        with self.assertRaises(ValueError):validate('RESTAPIPort','70000','8212')
    def test_blank_and_nested_array(self):
        value='[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(DenyTechnologyList=,CrossplayPlatforms=(Steam,Xbox))'
        self.assertEqual(parse(patch(value,{'DenyTechnologyList':'("ONE","TWO")'}))['DenyTechnologyList'],'("ONE","TWO")')

class StorageTests(unittest.TestCase):
    def test_dpapi(self):
        if os.name!='nt':self.skipTest('Windows only')
        value=b'test secret';encrypted=protect(value);self.assertNotIn(value,encrypted);self.assertEqual(protect(encrypted,True),value)
    def test_export_excludes_secrets_and_automation(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);p=copy.deepcopy(DEFAULT_PROFILE);p['channels']=[{'id':'test','events':['chat']}];p['auto_update']=True;p['permissions']={'start':{'users':['123']}};p['schedules']=[{'enabled':True}]
            text='[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(AdminPassword="sensitive",ServerPassword="private",ServerName="test")';path=Path(d)/'out.zip';store.export_profile(p,path,text)
            with zipfile.ZipFile(path) as z:
                data=b''.join(z.read(n) for n in z.namelist());self.assertNotIn(b'sensitive',data);self.assertNotIn(b'private',data)
                exported=json.loads(z.read('profile.json'))['profile'];self.assertFalse(exported['auto_update']);self.assertEqual(exported['channels'],[]);self.assertEqual(exported['schedules'],[])
            imported=store.import_profile(path);self.assertNotEqual(imported['id'],p['id'])
    def test_import_path_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);path=Path(d)/'evil.zip';p=dict(DEFAULT_PROFILE);p['icon']='../../evil.png'
            with zipfile.ZipFile(path,'w') as z:z.writestr('profile.json',json.dumps({'format':1,'profile':p}));z.writestr('../../evil.png',b'bad')
            with self.assertRaises(ValueError):store.import_profile(path)

class FakeRemote:
    def __init__(self,fail=None):self.calls=[];self.fail=fail;self.state='active'
    def call(self,action,args=None,timeout=None):
        self.calls.append(action)
        if action==self.fail:raise RuntimeError('simulated failure')
        if action=='status':return {'ActiveState':self.state,'build':'1'}
        if action=='backup':return {'name':'test.tar.gz'}
        return {}
    def api(self,name,payload=None):self.calls.append('api:'+name);return {}
    def control(self,name):self.calls.append('control:'+name);self.state='active' if name=='start' else 'inactive'
    def wait_state(self,*args):self.calls.append('wait');return {'ActiveState':self.state}
    def update_build(self):self.calls.append('update');return 'updated'

class MaintenanceTests(unittest.TestCase):
    def setup_controller(self,d,fail=None):
        store=Store(d);c=Controller(store);r=FakeRemote(fail);c.remote=lambda _:r;c.warning=lambda p,r,action:r.calls.append('warning');return c,r,store.profiles[0]
    def test_backup_order(self):
        with tempfile.TemporaryDirectory() as d:
            c,r,p=self.setup_controller(d);c.operate(p,'backup');self.assertEqual(r.calls,['status','warning','control:stop','wait','backup','control:start','wait'])
    def test_failed_backup_leaves_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            c,r,p=self.setup_controller(d,'backup')
            with self.assertRaises(RuntimeError):c.operate(p,'update')
            self.assertNotIn('control:start',r.calls);self.assertNotIn('update',r.calls);self.assertFalse(c.busy)
    def test_offline_backup_does_not_start_world(self):
        with tempfile.TemporaryDirectory() as d:
            c,r,p=self.setup_controller(d);r.state='inactive';c.operate(p,'backup');self.assertNotIn('control:start',r.calls);self.assertNotIn('warning',r.calls)
    def test_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            c,r,p=self.setup_controller(d);import threading;resource=(p['host'],p.get('port',22),p['root'].rstrip('/'));c.locks[resource]=threading.Lock();c.locks[resource].acquire()
            with self.assertRaises(RuntimeError):c.operate(p,'start')
    def test_restore_first_backs_up(self):
        with tempfile.TemporaryDirectory() as d:
            c,r,p=self.setup_controller(d);c.operate(p,'restore',name='older.tar.gz');self.assertLess(r.calls.index('backup'),r.calls.index('restore'))

class SchedulingAndBotTests(unittest.TestCase):
    def test_timezone_is_independent_of_windows_local_time(self):
        from zoneinfo import ZoneInfo
        now=datetime.datetime(2026,9,7,12,tzinfo=datetime.timezone.utc).timestamp()
        n=next_run({'mode':'daily','at':'09:00'},now,'America/New_York')
        self.assertEqual(datetime.datetime.fromtimestamp(n,datetime.timezone.utc).hour,13)
    def test_spring_gap_moves_forward(self):
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/New_York');now=datetime.datetime(2026,3,8,1,tzinfo=zone).timestamp()
        n=next_run({'mode':'daily','at':'02:30'},now,zone.key)
        self.assertEqual(datetime.datetime.fromtimestamp(n,zone).strftime('%H:%M'),'03:30')
    def test_fall_overlap_runs_once(self):
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/New_York');now=datetime.datetime(2026,11,1,1,45,tzinfo=zone,fold=0).timestamp()
        n=next_run({'mode':'daily','at':'01:30'},now,zone.key)
        self.assertEqual(datetime.datetime.fromtimestamp(n,zone).date(),datetime.date(2026,11,2))
    def test_background_routes_without_local_maintenance(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);c=Controller(store);p=store.profiles[0];p['background_enabled']=True;r=FakeRemote();calls=[]
            r.background_action=lambda action,args:calls.append((action,args)) or {'name':'remote.tar.gz'};c.remote=lambda _:r
            self.assertEqual(c.operate(p,'backup')['name'],'remote.tar.gz');self.assertEqual(calls,[('backup',{})]);self.assertEqual(r.calls,[])
    def test_background_suppresses_windows_scheduler(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);c=Controller(store);p=store.profiles[0];p['background_enabled']=True;p['schedules']=[dict(id='test',enabled=True,mode='interval',minutes=1,next=1,action='backup')]
            c.tick();self.assertEqual(p['schedules'][0]['next'],1)
    def test_interval(self):self.assertEqual(next_run({'mode':'interval','minutes':15},1000),1900)
    def test_daily(self):
        now=datetime.datetime(2026,9,7,5,30).timestamp();n=next_run({'mode':'daily','at':'04:00'},now);self.assertEqual(datetime.datetime.fromtimestamp(n),datetime.datetime(2026,9,8,4,0))
    def test_permissions_deny_default(self):self.assertFalse(permitted({},'start',123,[1,2]))
    def test_permissions_scoped(self):
        p={'permissions':{'start':{'users':['123'],'roles':['9']}}};self.assertTrue(permitted(p,'start',123,[]));self.assertTrue(permitted(p,'start',456,[9]));self.assertFalse(permitted(p,'stop',123,[9]))
    def test_map_png(self):self.assertTrue(render_map(DEFAULT_PROFILE,[{'name':'Test','location_x':0,'location_y':0}]).startswith(b'\x89PNG'))

if __name__=='__main__':unittest.main()

class HostFingerprintTests(unittest.TestCase):
    def test_formatting_normalizes_without_changing_key(self):
        pin=('SHA256:'+'A'*43);self.assertEqual(normalize_fingerprint('  '+pin+'=  '),pin)
    def test_password_in_fingerprint_field_is_explained(self):
        with self.assertRaisesRegex(ValueError,'account password fields'):normalize_fingerprint('example-misplaced-password')
    def test_correct_key_accepted_but_different_key_rejected(self):
        class Key:
            def asbytes(self):return b'test-host-key'
        key=Key();PinPolicy(fingerprint(key)).missing_host_key(None,'test',key)
        with self.assertRaisesRegex(RuntimeError,'host key changed'):PinPolicy(('SHA256:'+'A'*43)).missing_host_key(None,'test',key)
