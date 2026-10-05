"""Opt-in packaged application smoke test; never connects to a server."""
import json,os,sys
from pathlib import Path

def run(directory):
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from .ui import MainWindow,STYLE
    from .store import Store,protect
    from .settings import parse,patch
    from .controller import render_map,next_run
    from . import __version__
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    app=QApplication([])
    for font in ('segoeui.ttf','segoeuib.ttf','consola.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    app.setStyle('Fusion');app.setStyleSheet(STYLE);window=MainWindow(Store(directory/'profile'),offline=True);window.show();app.processEvents()
    for i in range(window.stack.count()):window.navigate(i);app.processEvents()
    window.navigate(0);app.processEvents();window.grab().save(str(directory/'packaged-ui.png'))
    root=Path(__file__).parent
    for source in ('settings.py','remote_agent.py','controller.py','background.py','worker_install.py','server_install.py','provision.py','rcon.py','discord_bot.py','__init__.py'):assert (root/source).is_file(),source+' missing from executable'
    ini='[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ExpRate=1.0,ServerName="Test")'
    assert parse(patch(ini,{'ExpRate':'2.0'}))['ExpRate']=='2.0'
    assert protect(protect(b'smoke-test'),True)==b'smoke-test'
    assert render_map(window.p,[]).startswith(b'\x89PNG')
    assert next_run({'mode':'daily','at':'09:00'},1788782400,'America/New_York')>1788782400
    from .save_repair import pack,unpack,parse_raw
    from palworld_save_tools.gvas import GvasFile
    codec_sample=b'GVAS'+b'packaged-codec-test'*1024
    assert unpack(pack(codec_sample))==codec_sample
    from .install_ui import InstallDialog
    installer=InstallDialog(window);assert installer.fields['host'].text()=='';assert not installer.install_button.isEnabled();installer.close()
    report={'ok':True,'version':__version__,'frozen':bool(getattr(sys,'frozen',False)),'pages':window.stack.count(),'ubuntu_installer':True,'save_codec':True,'ssh_helper_resources':True,'worker_sources':True,'timezone_data':True,'dpapi':True,'map_png':True,'network_used':False}
    (directory/'report.json').write_text(json.dumps(report,indent=2));window.hide();return 0
