import sys,types,tempfile,json,importlib.util,unittest,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from palmanager import settings

def module():
    spec=importlib.util.spec_from_file_location('ubuntu_installer_test',Path(__file__).resolve().parents[1]/'palmanager/server_install.py');m=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'pwd':types.SimpleNamespace(getpwnam=lambda _:None),'fcntl':types.SimpleNamespace(flock=lambda *a:None,LOCK_EX=1,LOCK_NB=2)}):spec.loader.exec_module(m)
    m.parse=settings.parse;m.patch=settings.patch;return m

class InstallerTests(unittest.TestCase):
    def test_rejects_user_and_directory_injection(self):
        m=module()
        for user,slug in [('root;id','world'),('steam','../world'),('steam','world%h'),('steam','world\nExecStart=x'),('steam','/etc')]:
            with self.assertRaises(ValueError):m.config({'user':user,'slug':slug})
    def test_non_root_and_terms_required(self):
        m=module()
        with self.assertRaises(ValueError):m.install({'accept_steam':False})
        with self.assertRaises(ValueError):m.install({'accept_steam':True,'api_password':'short'})
        with patch.object(m.os,'geteuid',return_value=1000,create=True):
            with self.assertRaisesRegex(ValueError,'Sudo'):m.inspect({})
    def test_unit_has_isolated_paths_and_no_destructive_hooks(self):
        m=module();text=m.unit_text(dict(user='ubuntu',root='/home/ubuntu/PalServers/world1',home='/home/ubuntu',game_port=8211,query_port=27015))
        self.assertIn('User=ubuntu',text);self.assertIn('-port=8211 -QueryPort=27015',text);self.assertIn('Restart=on-failure',text)
        for forbidden in ('ExecStartPre','ExecStopPost','rm -','killall','sudo','RuntimeMaxSec'):self.assertNotIn(forbidden,text)
    def test_complete_install_as_owner_and_resume_without_redownload(self):
        m=module()
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);root=home/'PalServers/world1';m.UNITS=home/'units';marker=home/'state/world1.json';p=dict(user='ubuntu',slug='world1',home=str(home),root=str(root),service='palworld-world1.service',name='Test',game_port=8211,query_port=27015,api_port=8212)
            calls=[]
            def fake_run(args,stage,timeout=900,input=None):
                calls.append((args,stage))
                if '+app_update' in args:
                    root.mkdir(parents=True,exist_ok=True);(root/'PalServer.sh').write_text('#!/bin/sh\n');(root/'DefaultPalWorldSettings.ini').write_text('[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ServerName="Test",AdminPassword="",PublicPort=8211,RESTAPIEnabled=False,RESTAPIPort=8212,RCONEnabled=False)')
                    return "Success! App '2394010' fully installed."
                if stage=='Configuring the Steam SDK and server settings':
                    body=json.loads(input);cfg=root/'Pal/Saved/Config/LinuxServer/PalWorldSettings.ini';cfg.parent.mkdir(parents=True);cfg.write_text(body['settings'],'utf-8')
                return ''
            opts=dict(accept_steam=True,api_password='test-secret-123456789',start=False)
            import builtins
            actual_open=builtins.open
            def safe_open(path,*args,**kwargs):return actual_open(home/'installer.lock' if path=='/run/lock/palworld-manager-install.lock' else path,*args,**kwargs)
            with patch.object(m,'inspect',return_value=p.copy()),patch.object(m,'config',return_value=(p,None,marker,'identity')),patch.object(m,'clean_path',side_effect=lambda p:p),patch.object(m,'run',side_effect=fake_run),patch.object(m,'emit'),patch('builtins.open',side_effect=safe_open):
                result=m.install(opts);self.assertFalse(result['started']);self.assertTrue((m.UNITS/p['service']).exists())
                steam=next(args for args,stage in calls if '+app_update' in args);self.assertEqual(steam[:4],['runuser','-u','ubuntu','--']);self.assertLess(steam.index('+force_install_dir'),steam.index('+login'))
                self.assertNotIn(opts['api_password'],marker.read_text());self.assertNotIn(opts['api_password'],(m.UNITS/p['service']).read_text())
                marker.write_text(json.dumps({'identity':'identity','phase':'configured'}));calls.clear();m.install(opts)
                self.assertFalse(any('+app_update' in args or args[0]=='apt-get' for args,stage in calls))
    def test_preflight_preserves_existing_directory_and_checks_resources(self):
        m=module()
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'world';home=base/'home';home.mkdir();m.UNITS=base/'units';marker=base/'state.json'
            osfile=base/'os-release';osfile.write_text('ID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04"')
            mem=base/'meminfo';mem.write_text('MemTotal:       16777216 kB\n');systemd=base/'systemd';systemd.mkdir()
            mapping={'/etc/os-release':osfile,'/proc/meminfo':mem,'/run/systemd/system':systemd}
            p=dict(user='ubuntu',home=str(home),root=str(root),service='palworld-test.service',game_port=8211,query_port=27015,api_port=8212)
            with patch.object(m,'Path',side_effect=lambda path:mapping.get(str(path),Path(path))),patch.object(m,'config',return_value=(p,None,marker,'id')),patch.object(m,'clean_path'),patch.object(m.os,'geteuid',return_value=0,create=True),patch.object(m.platform,'machine',return_value='x86_64'),patch.object(m.shutil,'which',return_value='/usr/bin/test'),patch.object(m.shutil,'disk_usage',return_value=types.SimpleNamespace(free=20*1024**3)),patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(stdout='not-found')),patch.object(m,'available',return_value=True):
                self.assertFalse(m.inspect({})['resume']);self.assertFalse(root.exists())
                root.mkdir();(root/'existing-save.sav').write_bytes(b'keep')
                with self.assertRaisesRegex(ValueError,'not empty'):m.inspect({})
                self.assertEqual((root/'existing-save.sav').read_bytes(),b'keep')
                with patch.object(m.platform,'machine',return_value='aarch64'):
                    with self.assertRaisesRegex(ValueError,'x86-64'):m.inspect({})

class InstallerUiTests(unittest.TestCase):
    def test_new_target_and_explicit_review_gate(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from palmanager.ui import MainWindow
        from palmanager.install_ui import InstallDialog
        from palmanager.store import Store,DEFAULT_PROFILE
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            parent=MainWindow(Store(d),offline=True);parent.timer.stop();dialog=InstallDialog(parent)
            self.assertEqual(dialog.fields['host'].text(),'');self.assertFalse(dialog.install_button.isEnabled())
            dialog.fields['host'].setText('example.test');dialog.fields['fingerprint'].setText(('SHA256:'+'A'*43));dialog.verified.setChecked(True)
            p,creds,opts=dialog.values();self.assertEqual(p['user'],p['admin_user']);self.assertEqual(creds['api_password'],'');self.assertFalse(opts['accept_steam'])
            dialog.checked=(p,creds,opts,{});dialog.terms.setChecked(True);self.assertTrue(dialog.install_button.isEnabled())
            dialog.fields['game_port'].setText('8221');self.assertFalse(dialog.install_button.isEnabled());dialog.close();parent.close()

class ManifestTests(unittest.TestCase):
    def test_forced_install_and_legacy_manifests(self):
        spec=importlib.util.spec_from_file_location('manifest_test',Path(__file__).resolve().parents[1]/'palmanager/remote_agent.py');m=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace()}):spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'common/PalServer';root.mkdir(parents=True);(root/'PalServer.sh').touch()
            legacy=Path(d)/'appmanifest_2394010.acf';legacy.write_text('"buildid" "123"')
            request=dict(root=str(root),service='test.service',action='status')
            with patch.object(m,'status',return_value={}):
                self.assertEqual(m.main(request)['build'],'123')
                forced=root/'steamapps/appmanifest_2394010.acf';forced.parent.mkdir();forced.write_text('"buildid" "456"')
                self.assertEqual(m.main(request)['build'],'456')

if __name__=='__main__':unittest.main()
