import copy,datetime,io,json,os,re,sys,time,uuid,zipfile,threading
from pathlib import Path
from zoneinfo import ZoneInfo
from PySide6.QtCore import Qt,QObject,Signal,QRunnable,QThreadPool,QTimer,QSize,QUrl
from PySide6.QtGui import QColor,QPainter,QPen,QPixmap,QIcon,QFont,QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QPushButton,QLineEdit,QComboBox,QStackedWidget,QFrame,QScrollArea,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPlainTextEdit,QMessageBox,QFileDialog,QInputDialog,QDialog,QDialogButtonBox,QCheckBox,QSpinBox,QDoubleSpinBox,QColorDialog,QProgressBar,QSplitter)
from .store import Store,DEFAULT_PROFILE,recycle,atomic
from .settings import parse,patch,group,label,PRESETS
from .controller import Controller,next_run,COMMANDS,EVENTS,render_map
from .discord_bot import WorldBot
from .locations import locate,validate_custom
from .coordinates import map_position,map_player,FULL_MAP_BOUNDS,MAP_DOWNLOAD
from .remote import normalize_fingerprint
from .schedule_status import publication,remote_only

STYLE='''
* { font-family: "Segoe UI"; font-size: 13px; }
QMainWindow, QDialog { background:#0d141e; color:#e7edf5; }
QWidget { color:#e7edf5; }
QFrame#sidebar { background:#101b28; border-right:1px solid #253143; }
QFrame#card { background:#142130; border:1px solid #26364a; border-radius:12px; }
QLabel#title { font-size:28px; font-weight:650; }
QLabel#subtitle { color:#92a6ba; font-size:13px; }
QLabel#brand { font-size:20px; font-weight:700; color:#76e9bf; }
QLabel#stat { font-size:26px; font-weight:650; }
QLabel#note { background:#1c2b38; border:1px solid #31465b; border-radius:8px; padding:12px; color:#b5cadd; }
QPushButton { background:#213247; border:1px solid #30465d; border-radius:7px; padding:9px 15px; color:#e3edf7; }
QPushButton:hover { background:#2b425a; border-color:#53816f; }
QPushButton:pressed { background:#304f61; }
QPushButton:disabled { color:#67798b; background:#182431; border-color:#24313f; }
QPushButton#primary { background:#65dfb2; color:#09271e; font-weight:650; border:0; }
QPushButton#primary:hover { background:#8bedca; }
QPushButton#primary:disabled { background:#213b35; color:#718b82; border:1px solid #30483f; }
QPushButton#danger { color:#ff9b9b; border-color:#70464e; background:#35232e; }
QPushButton#nav { border:0; background:transparent; text-align:left; padding:12px 18px; color:#9ab0c6; }
QPushButton#nav:checked { background:#1d3b3a; color:#8df0c9; border-left:3px solid #65dfb2; border-radius:5px; }
QPushButton#nav:hover { background:#1c2c3e; color:white; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background:#0e1b29; border:1px solid #314258; border-radius:6px; padding:8px; selection-background-color:#316b5b; }
QLineEdit:focus,QComboBox:focus { border-color:#65dfb2; }
QComboBox QAbstractItemView { background:#162537; color:#e7edf5; selection-background-color:#2c594e; }
QPlainTextEdit { background:#0c1520; border:1px solid #2a3a4e; border-radius:8px; padding:8px; font-family:"Cascadia Mono","Consolas"; font-size:12px; }
QTableWidget { background:#111e2c; alternate-background-color:#152434; border:1px solid #28394d; border-radius:8px; gridline-color:#243549; selection-background-color:#25493f; }
QHeaderView::section { background:#1b2b3e; color:#a6bdd1; padding:10px; border:0; font-weight:600; }
QTableWidget::item { padding:8px; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#0d1722; width:10px; } QScrollBar::handle:vertical { background:#30475b; min-height:30px; border-radius:5px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QCheckBox { spacing:9px; padding:5px; }
QCheckBox::indicator { width:17px; height:17px; border:1px solid #506378; border-radius:4px; background:#142232; }
QCheckBox::indicator:checked { background:#65dfb2; border-color:#65dfb2; }
QToolTip { color:#e7edf5; background:#22364a; border:1px solid #47617a; }
QProgressBar { border:0; background:#1e3041; border-radius:3px; height:6px; } QProgressBar::chunk { background:#65dfb2; border-radius:3px; }
QStatusBar { background:#101c28; color:#9db4c9; }
'''

class Signals(QObject):
    result=Signal(object);error=Signal(str);finished=Signal()
class Job(QRunnable):
    def __init__(self,fn):super().__init__();self.fn=fn;self.signals=Signals()
    def run(self):
        try:self.signals.result.emit(self.fn())
        except Exception as e:self.signals.error.emit(str(e))
        finally:self.signals.finished.emit()
class Bus(QObject):event=Signal(str,str,str)

def button(text,fn=None,kind=''):
    b=QPushButton(text)
    if kind:b.setObjectName(kind)
    if fn:b.clicked.connect(fn)
    return b
def note(text):
    w=QLabel(text);w.setObjectName('note');w.setWordWrap(True);w.setTextFormat(Qt.PlainText);return w
def table(headers):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.setAlternatingRowColors(True);t.verticalHeader().hide();t.setSelectionBehavior(QAbstractItemView.SelectRows);t.setEditTriggers(QAbstractItemView.NoEditTriggers);t.horizontalHeader().setStretchLastSection(True);return t
def item(text):return QTableWidgetItem(str(text))
def line(value='',secret=False):
    w=QLineEdit(str(value));w.setMinimumWidth(180)
    if secret:w.setEchoMode(QLineEdit.Password)
    return w
def page(title,subtitle):
    w=QWidget();layout=QVBoxLayout(w);layout.setContentsMargins(28,24,28,24);layout.setSpacing(16)
    h=QLabel(title);h.setObjectName('title');layout.addWidget(h)
    sub=QLabel(subtitle);sub.setObjectName('subtitle');sub.setWordWrap(True);layout.addWidget(sub)
    return w,layout
def row(layout,*widgets):
    h=QHBoxLayout()
    for w in widgets:
        if w is None:h.addStretch()
        else:h.addWidget(w)
    layout.addLayout(h);return h

class ProfileDialog(QDialog):
    def __init__(self,parent,p,credentials):
        super().__init__(parent);self.setWindowTitle('World connection');self.resize(720,740);self.original=p;self.fields={};self.credential_fields={}
        box=QVBoxLayout(self);box.addWidget(note('Connects to native Ubuntu Palworld over SSH. REST requests travel inside SSH to localhost; no API port needs to be exposed.'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();body.setObjectName('connectionBody');body.setStyleSheet('QWidget#connectionBody { background:#0d141e; } QLabel { color:#e7edf5; background:transparent; }');form=QFormLayout(body);form.setRowWrapPolicy(QFormLayout.WrapAllRows);form.setSpacing(10);scroll.setWidget(body);box.addWidget(scroll)
        names={'name':'World name','host':'SSH host','port':'SSH port','user':'Steam / server owner SSH username','admin_user':'Administrator SSH username (sudo)','fingerprint':'SSH server fingerprint (SHA256 — not a password)','root':'Installation directory','service':'Systemd service','steamcmd':'SteamCMD path','api_port':'REST port','warning_seconds':'Maintenance warning (seconds)','schedule_timezone':'Schedule timezone (IANA)'}
        for key,title in names.items():
            w=line(p.get(key,DEFAULT_PROFILE[key]));w.setAccessibleName(title);field_label=QLabel(title);field_label.setBuddy(w);form.addRow(field_label,w);self.fields[key]=w
            if key in ('user','admin_user'):
                secret_key='password' if key=='user' else 'admin_password';password_title='Steam / server owner password' if key=='user' else 'Administrator SSH / sudo password'
                password=line(credentials.get(secret_key,''));password.setAccessibleName(password_title);password_label=QLabel(password_title);password_label.setBuddy(password);form.addRow(password_label,password);self.credential_fields[secret_key]=password
        for key,title in [('api_password','REST password (blank: read server INI)'),('key_file','SSH private key file (optional)')]:
            w=line(credentials.get(key,''));w.setAccessibleName(title);field_label=QLabel(title);field_label.setBuddy(w);form.addRow(field_label,w);self.credential_fields[key]=w
        self.remember=QCheckBox('Save passwords encrypted on disk (Windows account encryption)');self.remember.setChecked(True);box.addWidget(self.remember)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self.validate);buttons.rejected.connect(self.reject);box.addWidget(buttons)
    def validate(self):
        try:
            p=self.value()
            for key in ('port','api_port'):
                if not 1<=p[key]<=65535:raise ValueError('Ports must be 1–65535')
            if not 0<=p['warning_seconds']<=3600:raise ValueError('Warning must be 0–3600 seconds')
            if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',p['service']):raise ValueError('Enter a systemd .service unit')
            if not p['root'].startswith('/') or p['root']=='/':raise ValueError('Enter an absolute Linux installation directory')
            if not p['host'].strip() or not p['user'].strip():raise ValueError('Host and user are required')
            normalize_fingerprint(p['fingerprint'])
            ZoneInfo(p['schedule_timezone'])
            self.accept()
        except Exception as e:QMessageBox.warning(self,'Check connection',str(e))
    def value(self):
        p=copy.deepcopy(self.original)
        for key,w in self.fields.items():p[key]=int(w.text()) if key in ('port','api_port','warning_seconds') else w.text().strip()
        return p

class MapWidget(QWidget):
    def __init__(self):super().__init__();self.setMinimumSize(500,300);self.profile={};self.players=[];self.background=QPixmap()
    def update_data(self,p,players):
        self.profile=p;self.players=players;self.background=QPixmap(p.get('map_image',''));self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);painter.fillRect(self.rect(),QColor('#101e2b'))
        r=self.rect().adjusted(45,30,-35,-40);painter.setPen(QPen(QColor('#294153'),1))
        if not self.background.isNull():
            size=self.background.size().scaled(r.size(),Qt.KeepAspectRatio);center=r.center();r.setRect(center.x()-size.width()//2,center.y()-size.height()//2,size.width(),size.height());painter.drawPixmap(r,self.background)
        else:
            for i in range(11):
                x=r.left()+r.width()*i/10;y=r.top()+r.height()*i/10;painter.drawLine(int(x),r.top(),int(x),r.bottom());painter.drawLine(r.left(),int(y),r.right(),int(y))
        bounds=self.profile.get('map_bounds',[-1000,1000,-1000,1000]);xmin,xmax,ymin,ymax=bounds
        painter.setPen(QColor('#7892aa'));painter.drawText(r.left(),r.bottom()+24,str(xmin));painter.drawText(r.right()-50,r.bottom()+24,str(xmax));painter.drawText(3,r.top()+5,str(ymax));painter.drawText(3,r.bottom(),str(ymin))
        if not self.players:painter.setPen(QColor('#9cb2c7'));painter.drawText(r,Qt.AlignCenter,'No live player locations\nConnect and enable the REST API to populate this map.')
        visible=0
        for player in self.players:
            if 'location_x' not in player or 'location_y' not in player:continue
            try:x,y=map_position(player,self.profile)
            except (ValueError,TypeError):continue
            if self.profile.get('map_swap'):x,y=y,x
            u=(x-xmin)/(xmax-xmin);v=(y-ymin)/(ymax-ymin)
            if self.profile.get('map_flip_x'):u=1-u
            if self.profile.get('map_flip_y'):v=1-v
            if not (0<=u<=1 and 0<=v<=1):continue
            visible+=1
            px=int(r.left()+u*r.width());py=int(r.bottom()-v*r.height());painter.setBrush(QColor(self.profile.get('accent','#65dfb2')));painter.setPen(QPen(QColor('white'),2));painter.drawEllipse(px-6,py-6,12,12)
            painter.setPen(QColor('white'));painter.drawText(px+12,py+4,player.get('name','Player'))
        if self.players and not visible:
            painter.setPen(QColor('#e7edf5'));painter.drawText(r,Qt.AlignCenter,'Online players are outside this map or have unavailable coordinates.\nCheck coordinate mode and map bounds. World Tree is a separate map.')

class MainWindow(QMainWindow):
    def __init__(self,store=None,offline=False):
        super().__init__();self.setWindowTitle('Palworld Manager');self.resize(1370,900);self.setMinimumSize(1100,700)
        self.store=store or Store();self.controller=Controller(self.store);self.bus=Bus();self.controller.listener=self.bus.event.emit;self.bus.event.connect(self.on_event)
        self.worker_states={};self.jobs=set();self.pool=QThreadPool.globalInstance();self.pool.setMaxThreadCount(8);self.offline=offline;self.polling=False;self.connected=False;self.settings_data=None;self.editors={};self.current_values={};self.default_values={};self.log_cursor={};self.chat_offsets={};self.chat_remainders={};self.bots={};self.status_data={};self.players_data=[];self.pages={};self.navs=[];self.notifications=[]
        central=QWidget();outer=QHBoxLayout(central);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0);self.setCentralWidget(central)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(232);sl=QVBoxLayout(side);sl.setContentsMargins(15,27,15,18);sl.setSpacing(8)
        brand=QLabel('PALWORLD');brand.setObjectName('brand');sl.addWidget(brand);small=QLabel('SERVER MANAGER');small.setObjectName('subtitle');sl.addWidget(small);sl.addSpacing(22)
        self.world_combo=QComboBox();sl.addWidget(self.world_combo);self.world_combo.currentIndexChanged.connect(self.switch_world)
        self.connection_badge=QLabel('●  Not connected');self.connection_badge.setObjectName('subtitle');sl.addWidget(self.connection_badge);sl.addSpacing(17)
        self.stack=QStackedWidget()
        builders=[('Overview',self.build_overview),('Settings',self.build_settings),('Players',self.build_players),('Live map',self.build_map),('Console',self.build_console),('Backups',self.build_backups),('Save repair',self.build_save_repair),('Schedule',self.build_schedule),('Mods',self.build_mods),('Chat & broadcast',self.build_chat),('Discord',self.build_discord),('World profile',self.build_profile)]
        for i,(name,builder) in enumerate(builders):
            b=button(name,lambda checked=False,i=i:self.navigate(i),'nav');b.setCheckable(True);sl.addWidget(b);self.navs.append(b);w=builder();self.pages[name]=w;self.stack.addWidget(w)
        sl.addStretch();sl.addWidget(button('+ Add world',self.add_world));sl.addWidget(button('Connection…',self.edit_connection));footer=QLabel('SSH encrypted  ·  Windows\nVersion 0.2.11');footer.setObjectName('subtitle');sl.addWidget(footer)
        outer.addWidget(side);outer.addWidget(self.stack,1);self.statusBar().showMessage('Ready. Configure credentials to connect.');self.repopulate_worlds();self.navigate(0)
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(5000)
    @property
    def p(self):return self.store.profiles[max(0,self.world_combo.currentIndex())]
    def run(self,fn,done=None,quiet=False):
        job=Job(fn);self.jobs.add(job)
        if done:job.signals.result.connect(done)
        job.signals.error.connect(lambda text:self.show_error(text,quiet));job.signals.finished.connect(lambda:self.jobs.discard(job));self.pool.start(job);return job
    def show_error(self,text,quiet=False):
        self.statusBar().showMessage(text[:300]);
        if not quiet:QMessageBox.warning(self,'Operation could not complete',text)
    def repopulate_worlds(self,select=None):
        self.world_combo.blockSignals(True);self.world_combo.clear()
        for p in self.store.profiles:self.world_combo.addItem(p['name'],p['id'])
        if select:self.world_combo.setCurrentIndex(max(0,self.world_combo.findData(select)))
        self.world_combo.blockSignals(False);self.switch_world()
    def switch_world(self,*args):
        if not self.store.profiles:return
        self.repair_rows=[];self.repair_path='';self.repair_table.setRowCount(0);self.repair_owner.clear();self.repair_summary.setText('Scan a world save to inspect expedition assignments.')
        self.connected=False;self.settings_data=None;self.settings_table.setRowCount(0);self.editors={};self.players_data=[];self.player_table.setRowCount(0);self.map.update_data(self.p,[]);self.console.clear();self.chat.clear();self.backup_table.setRowCount(0);self.mod_table.setRowCount(0)
        self.world_title.setText(self.p['name']);self.host_label.setText(self.p['host']+'  /  '+self.p['service']);self.connection_badge.setText('●  Not connected');self.overview_note.setText('Connect to inspect this world. Actions use its actual SSH account, systemd service and installation directory.')
        self.render_welcome();self.render_schedule();self.render_discord();self.render_profile();self.stat_labels['State'].setText('Unknown');self.stat_labels['Players'].setText('—');self.stat_labels['Memory'].setText('—');self.stat_labels['Free disk'].setText('—');self.refresh()
    def navigate(self,index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.navs):b.setChecked(i==index)
        name=list(self.pages)[index] if self.pages else ''
        if name=='Settings' and not self.settings_data and self.connected:self.load_settings()
        if name=='Backups' and self.connected:self.load_backups()
        if name=='Mods' and self.connected:self.load_mods()
    def edit_connection(self):
        p=self.p;d=ProfileDialog(self,p,self.store.credentials(p['id']))
        if d.exec()!=QDialog.Accepted:return
        try:
            new=d.value();credentials=self.store.credentials(p['id']);credentials.update({k:w.text() for k,w in d.credential_fields.items()})
            self.store.set_credentials(p['id'],credentials,d.remember.isChecked());self.store.profiles[self.world_combo.currentIndex()]=new;self.store.save();self.repopulate_worlds(new['id']);self.refresh(verbose=True)
        except Exception as e:self.show_error(str(e))
    def add_world(self):
        choice,ok=QInputDialog.getItem(self,'Add world','Choose how to add this world',['Connect to an existing server','Install a new server on Ubuntu'],0,False)
        if not ok:return
        if choice=='Install a new server on Ubuntu':
            from .install_ui import InstallDialog
            InstallDialog(self).exec();return
        p=copy.deepcopy(DEFAULT_PROFILE);p.update(id=uuid.uuid4().hex,name='New world',host='',fingerprint='',root='',service='palworld.service')
        d=ProfileDialog(self,p,{})
        if d.exec()!=QDialog.Accepted:return
        new=d.value();self.store.profiles.append(new);self.store.set_credentials(new['id'],{k:w.text() for k,w in d.credential_fields.items()},d.remember.isChecked());self.store.save();self.repopulate_worlds(new['id'])
    def action(self,action,**kwargs):
        p=copy.deepcopy(self.p);self.run(lambda:self.controller.operate(p,action,**kwargs),lambda result:self.after_action(p['id'],action,result))
    def after_action(self,world,action,result):
        if world!=self.p['id']:return
        self.refresh()
        if action in ('backup','restore'):self.load_backups()
        if action in ('toggle_mod','install_mod','trash'):self.load_mods()
        if action=='write_settings':self.editors={};self.load_settings()
    def on_event(self,world,event,message):
        now=datetime.datetime.now().strftime('%H:%M:%S');self.notifications.append((world,event,message));self.notifications=self.notifications[-500:]
        if world==self.p['id']:
            self.activity.appendPlainText(now+'  '+event.upper()+'  '+message);self.statusBar().showMessage(message[:300])
        if event=='progress':self.operation_label.setText(message)
        if event in ('done','error'):self.operation_label.setText(message)
    def tick(self):
        if self.offline:return
        self.controller.tick();self.refresh()
    def refresh(self,verbose=False):
        if self.offline or self.polling:
            if verbose:
                self.verbose_poll=True;self.on_event(self.p['id'],'connection','A refresh is already in progress; waiting for the server response…' if self.polling else 'Offline preview mode: no connection attempted.')
            return
        if not self.store.credentials(self.p['id']).get('password') and not self.store.credentials(self.p['id']).get('key_file'):return
        p=copy.deepcopy(self.p);world=p['id'];cursor=self.log_cursor.get(world,'');self.polling=True;self.verbose_poll=verbose
        def progress(message):
            if self.verbose_poll:self.bus.event.emit(world,'connection',message)
        if verbose:self.on_event(world,'connection','Connecting to '+p['host']+':'+str(p.get('port',22))+' as '+p['user']+'…')
        def poll():
            r=self.controller.remote(p);progress('Authenticating SSH, checking the host key and reading service status…');state=r.call('status');progress('SSH connected. Service '+p['service']+': '+state.get('ActiveState','unknown')+'. Reading server logs…');out={'state':state,'players':None,'api_error':'','logs':[],'had_cursor':bool(cursor)}
            try:out['logs']=r.call('logs',{'cursor':cursor})
            except Exception as e:out['log_error']=str(e)
            if state.get('ActiveState')=='active':
                progress('Checking the REST API and online players through SSH…')
                try:out['players']=r.api('players').get('players',[])
                except Exception as e:out['api_error']=str(e)
            if p.get('chat_log'):
                try:out['chatlog']=r.call('chat_log',{'path':p['chat_log'],'offset':self.chat_offsets.get(world,0)})
                except Exception as e:out['chat_error']=str(e)
            try:out['worker_status']=r.worker_status()
            except Exception as e:out['worker_error']=str(e)
            if self.verbose_poll:
                for key in ('log_error','api_error','chat_error','worker_error'):
                    if out.get(key):progress(out[key])
                progress('Refresh complete. '+('Player count: '+str(len(out['players']))+'.' if out['players'] is not None else 'Player data unavailable; see API status above.'))
            return out
        job=self.run(poll,lambda data:self.apply_poll(p,data),quiet=True);job.signals.error.connect(lambda e:(self.connection_failed(world,e),progress('Connection / refresh failed: '+e)));job.signals.finished.connect(lambda:setattr(self,'polling',False))
    def connection_failed(self,world,error):
        if world!=self.p['id']:return
        self.worker_states[world]={'error':'SSH connection unavailable; worker installation status cannot be verified.'};self.render_schedule()
        self.connected=False;self.connection_badge.setText('●  Connection unavailable');self.stat_labels['State'].setText('Unknown');self.overview_note.setText(error);self.map_hint.setText('Connection lost. Previous locations are stale. '+error[:180])
    def apply_poll(self,p,data):
        self.controller.monitor_status(p,data['state'])
        if p['id']!=self.p['id']:return
        self.connected=True;state=data['state'];self.status_data=state;self.connection_badge.setText('●  SSH connected');self.stat_labels['State'].setText(state.get('ActiveState','unknown').capitalize());self.stat_labels['Players'].setText(str(len(data['players'])) if data['players'] is not None else 'API off')
        memory=state.get('MemoryCurrent','');self.stat_labels['Memory'].setText(f'{int(memory)/1024**3:.2f} GB' if memory.isdigit() else '—');self.stat_labels['Free disk'].setText(f'{state["disk"]["free"]/1024**3:.1f} GB')
        self.detail_label.setText('BUILD  '+state.get('build','unknown')+'     PID  '+state.get('MainPID','—')+'     CRASH RESTARTS  '+state.get('NRestarts','0'))
        self.guardian_label.setText('Systemd restart policy: '+state.get('Restart','unknown')+'   ·   Runtime limit: '+state.get('RuntimeMaxUSec','unknown'))
        if 'worker_status' in data:self.worker_states[p['id']]=data['worker_status']
        elif data.get('worker_error'):self.worker_states[p['id']]={'error':data['worker_error']}
        self.render_schedule()
        has_hook=bool(state.get('ExecStartPre',''))
        msg='Connected securely. Last refreshed '+datetime.datetime.now().strftime('%H:%M:%S')+'.'
        if has_hook:msg+=' This service has a startup hook. Your existing hook updates on every start and permanently purges backups older than 20 days. Schedule → Take over maintenance disables that hook and the six-hour runtime limit.'
        if data['api_error']:msg+=' '+data['api_error']
        self.overview_note.setText(msg)
        self.player_hint.setText(data['api_error'] or ('Live · refreshed '+datetime.datetime.now().strftime('%H:%M:%S')))
        if data['players'] is not None:
            self.players_data=data['players'];self.render_players();self.map.update_data(self.p,self.players_data);self.map_hint.setText('Live · '+str(len(self.players_data))+' players · '+datetime.datetime.now().strftime('%H:%M:%S')+' · Import a calibrated map image to show terrain.')
        else:
            self.players_data=[];self.render_players();self.map.update_data(self.p,[]);self.map_hint.setText(data['api_error'] or 'World is stopped.')
        for log in data.get('logs',[]):
            self.console.appendPlainText(str(log['message']))
            if not p.get('chat_log'):self.consume_chat(str(log['message']),p,relay=bool(data.get('had_cursor',False)))
            self.log_cursor[p['id']]=log['cursor']
        if 'chatlog' in data:
            result=data['chatlog'];initial=p['id'] not in self.chat_offsets;self.chat_offsets[p['id']]=result['offset']
            text=self.chat_remainders.get(p['id'],'')+result['text'];parts=text.splitlines(keepends=True);self.chat_remainders[p['id']]=''
            for value in parts:
                if not value.endswith(('\n','\r')):self.chat_remainders[p['id']]=value
                else:self.consume_chat(value,p,relay=not initial)
        if data.get('chat_error'):self.chat_hint.setText(data['chat_error'])
    def consume_chat(self,text,p,relay=True):
        try:
            match=re.search(p.get('chat_regex',DEFAULT_PROFILE['chat_regex']),text)
            if not match:return
            groups=match.groupdict();message=groups.get('name','Player')+': '+groups.get('message',match.group(0));self.chat.appendPlainText(message)
            if relay:self.controller.emit(p,'chat',message)
        except re.error:pass
    def build_overview(self):
        w,l=page('World overview','Your Ubuntu world, managed from Windows.');self.world_title=w.findChild(QLabel,'title');self.host_label=w.findChild(QLabel,'subtitle')
        cards=QHBoxLayout();self.stat_labels={}
        for name in ('State','Players','Memory','Free disk'):
            c=QFrame();c.setObjectName('card');v=QVBoxLayout(c);v.setContentsMargins(20,17,20,17);h=QLabel(name.upper());h.setObjectName('subtitle');v.addWidget(h);s=QLabel('—');s.setObjectName('stat');v.addWidget(s);cards.addWidget(c,1);self.stat_labels[name]=s
        l.addLayout(cards);row(l,button('Start',lambda:self.action('start'),'primary'),button('Restart',lambda:self.action('restart')),button('Stop',lambda:self.action('stop')),button('Update',lambda:self.action('update')),button('Back up',lambda:self.action('backup')),None,button('Connect / refresh',self.connect_now))
        self.operation_label=QLabel('Ready');self.operation_label.setObjectName('subtitle');l.addWidget(self.operation_label)
        self.overview_note=note('Connect to inspect this world.');l.addWidget(self.overview_note);self.detail_label=QLabel('BUILD —    PID —    CRASH RESTARTS —');self.detail_label.setObjectName('subtitle');l.addWidget(self.detail_label)
        self.guardian_label=QLabel('Crash guardian: detection pending');self.guardian_label.setObjectName('subtitle');l.addWidget(self.guardian_label)
        h=QLabel('Activity');h.setFont(QFont('Segoe UI',15,QFont.DemiBold));l.addWidget(h);self.activity=QPlainTextEdit();self.activity.setReadOnly(True);self.activity.setMaximumBlockCount(500);self.activity.setPlaceholderText('Server operations and notifications will appear here.');l.addWidget(self.activity,1)
        return w
    def connect_now(self):
        credentials=self.store.credentials(self.p['id'])
        if not credentials.get('password') and not credentials.get('key_file'):
            self.on_event(self.p['id'],'connection','Enter the Steam / server owner SSH password or a private key in Connection before connecting.');self.edit_connection()
        else:self.refresh(verbose=True)
    def build_settings(self):
        w,l=page('World settings','Every field discovered in your installed build. Only changed values are written; other bytes are preserved.')
        self.settings_search=line();self.settings_search.setPlaceholderText('Search settings…');self.settings_search.textChanged.connect(self.filter_settings);self.settings_group=QComboBox();self.settings_group.addItems(['All sections','Server & network','Combat & difficulty','Bases & guilds','Pals & breeding','Players & progression','Resources & items','World & advanced']);self.settings_group.currentTextChanged.connect(self.filter_settings)
        row(l,self.settings_search,self.settings_group,button('Reload',self.load_settings));self.settings_hint=QLabel('Load settings to begin.');self.settings_hint.setObjectName('subtitle');l.addWidget(self.settings_hint)
        self.settings_table=table(['Setting','Value','Reset']);self.settings_table.horizontalHeader().setStretchLastSection(False);self.settings_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.settings_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.settings_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Fixed);self.settings_table.setColumnWidth(2,110);l.addWidget(self.settings_table,1)
        row(l,button('Apply changed settings',self.save_settings,'primary'),button('Enable REST',self.enable_rest),button('Presets…',self.preset),None,button('Import settings',self.import_settings),button('Export settings',self.export_settings))
        return w
    def load_settings(self):
        if self.editors and self.changed_settings() and QMessageBox.question(self,'Discard edits?','Reloading will discard unsaved setting edits. Continue?')!=QMessageBox.Yes:return
        p=copy.deepcopy(self.p);self.run(lambda:self.controller.remote(p).call('read_settings'),lambda data:self.render_settings(p['id'],data))
    def render_settings(self,world,data):
        if world!=self.p['id']:return
        self.settings_data=data;self.current_values=parse(data['text']);self.default_values=parse(data['defaults']);values=dict(self.default_values);values.update(self.current_values);keys=sorted(values,key=lambda k:(group(k),k));self.settings_table.setRowCount(len(keys));self.editors={}
        for r,key in enumerate(keys):
            title=item(label(key)+'\n'+key+' · '+group(key));title.setToolTip('Default: '+('••••' if 'Password' in key else self.default_values.get(key,'Not supplied by this build')));self.settings_table.setItem(r,0,title)
            value=values[key]
            if value.lower() in ('true','false'):
                editor=QComboBox();editor.addItems(['True','False']);editor.setCurrentText(value.capitalize());editor.currentTextChanged.connect(self.settings_changed)
            else:
                editor=line(value);editor.textEdited.connect(self.settings_changed)
            editor.setToolTip(key+' — enter INI syntax; text is quoted.');self.settings_table.setCellWidget(r,1,editor);reset=button('Reset',lambda checked=False,key=key:self.reset_field(key));reset.setEnabled(key in self.default_values);self.settings_table.setCellWidget(r,2,reset);self.settings_table.setRowHeight(r,62);self.editors[key]=(editor,r)
        self.settings_changed();self.filter_settings()
    def value_of(self,editor):return editor.currentText() if isinstance(editor,QComboBox) else editor.text()
    def set_value(self,key,value):
        if key not in self.editors:return
        editor,_=self.editors[key]
        if isinstance(editor,QComboBox):editor.setCurrentText(value.capitalize())
        else:editor.setText(value)
        self.settings_changed()
    def reset_field(self,key):self.set_value(key,self.default_values[key])
    def changed_settings(self):
        changes={}
        for key,(editor,_) in self.editors.items():
            value=self.value_of(editor);old=self.current_values.get(key,self.default_values.get(key,''))
            if value!=old and not (value.lower() in ('true','false') and value.lower()==old.lower()):changes[key]=value
        return changes
    def settings_changed(self,*args):
        changes=self.changed_settings();self.settings_hint.setText(str(len(self.editors))+' settings  ·  '+str(len(changes))+' changed  ·  Reset stages the installed build’s default  ·  Restart to apply')
        for key,(editor,r) in self.editors.items():self.settings_table.item(r,0).setForeground(QColor('#79e9bc' if key in changes else '#cddbe8'))
    def filter_settings(self,*args):
        search=self.settings_search.text().lower();section=self.settings_group.currentText()
        for key,(_,r) in self.editors.items():self.settings_table.setRowHidden(r,search not in (key+' '+label(key)).lower() or (section!='All sections' and group(key)!=section))
    def save_settings(self):
        if not self.settings_data:return
        changes=self.changed_settings()
        if not changes:self.statusBar().showMessage('No changed settings.');return
        try:patch(self.settings_data['text'],changes,self.default_values)
        except Exception as e:self.show_error(str(e));return
        self.action('write_settings',hash=self.settings_data['hash'],changes=changes)
    def enable_rest(self):
        if not self.settings_data:self.load_settings();return
        self.set_value('RESTAPIEnabled','True');self.set_value('RESTAPIPort',str(self.p.get('api_port',8212)));self.statusBar().showMessage('REST enablement staged. Apply changed settings, then restart when ready.')
    def preset(self):
        if not self.settings_data:return
        name,ok=QInputDialog.getItem(self,'Suggested presets','These are suggested starting points, not independently community-tested presets.',list(PRESETS),0,False)
        if ok:
            for key,value in PRESETS[name].items():self.set_value(key,value)
    def export_settings(self):
        if not self.settings_data:return
        path,_=QFileDialog.getSaveFileName(self,'Export settings','Palworld-settings.zip','ZIP archive (*.zip)')
        if not path:return
        text=patch(self.settings_data['text'],self.changed_settings(),self.default_values);fields=parse(text);text=patch(text,{k:'""' for k in ('AdminPassword','ServerPassword') if k in fields})
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('PalWorldSettings.ini',text)
        self.statusBar().showMessage('Settings exported. Passwords excluded.')
    def import_settings(self):
        if not self.settings_data:return
        path,_=QFileDialog.getOpenFileName(self,'Import settings','','Settings (*.zip *.ini)')
        if not path:return
        try:
            if path.lower().endswith('.zip'):
                with zipfile.ZipFile(path) as z:
                    if z.getinfo('PalWorldSettings.ini').file_size>1024*1024:raise ValueError('Settings file too large')
                    text=z.read('PalWorldSettings.ini').decode('utf-8-sig')
            else:text=Path(path).read_text('utf-8-sig')
            imported=parse(text);skipped=[]
            for key,value in imported.items():
                if 'Password' in key:continue
                if key in self.editors:self.set_value(key,value)
                else:skipped.append(key)
            self.statusBar().showMessage('Imported changes staged for review. Passwords skipped.'+(' Unknown fields skipped: '+', '.join(skipped) if skipped else ''))
        except Exception as e:self.show_error(str(e))
    def build_players(self):
        w,l=page('Players','Online players and moderation through the official Palworld REST API.');self.player_hint=note('Connect and enable REST to load players.');l.addWidget(self.player_hint);self.player_table=table(['Name','Location','Account','User ID','Level','Ping','X','Y']);l.addWidget(self.player_table,1)
        l.addWidget(note('Locations show approximate proximity to known landmarks, not exact region boundaries. X/Y remain the original REST coordinates.'))
        row(l,button('Add named location…',self.add_named_location),button('Remove custom location…',self.remove_named_location),None)
        row(l,button('Refresh',self.refresh),None,button('Kick selected',lambda:self.moderate('kick')),button('Ban selected',lambda:self.moderate('ban'),'danger'),button('Unban by user ID',lambda:self.moderate('unban')));return w
    def render_players(self):
        self.player_table.setRowCount(len(self.players_data))
        for r,p in enumerate(self.players_data):
            location,explanation=locate(map_player(p,self.p),self.p)
            try:
                mx,my=map_position(p,self.p);explanation+=f' Map coordinates: {mx:.1f}, {my:.1f}.'
            except (ValueError,TypeError) as error:location='Unavailable';explanation=str(error)
            values=[p.get('name','—'),location]+[p.get(key,'—') for key in ('accountName','userId','level','ping','location_x','location_y')]
            for c,value in enumerate(values):self.player_table.setItem(r,c,item(value))
            self.player_table.item(r,1).setToolTip(explanation)
        self.player_table.resizeColumnsToContents();self.player_table.setColumnWidth(1,270)
    def add_named_location(self):
        selected=self.player_table.currentRow();player=map_player(self.players_data[selected],self.p) if 0<=selected<len(self.players_data) else {}
        d=QDialog(self);d.setWindowTitle('Name a location');d.resize(520,320);v=QVBoxLayout(d);v.addWidget(note('The selected player’s coordinates are prefilled. Matching custom locations take priority over built-in landmarks. Radius uses map units.'));f=QFormLayout();v.addLayout(f)
        name=line();x=line(player.get('location_x',''));y=line(player.get('location_y',''));radius=QSpinBox();radius.setRange(1,500);radius.setValue(40)
        f.addRow('Location name',name);f.addRow('Map X',x);f.addRow('Map Y',y);f.addRow('Match radius',radius)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);v.addWidget(buttons)
        def save():
            try:
                point=validate_custom(name.text(),x.text(),y.text(),radius.value());self.p.setdefault('named_locations',[]).append(point);self.store.save();self.render_players();d.accept()
            except ValueError as e:QMessageBox.warning(d,'Check location',str(e))
        buttons.accepted.connect(save);buttons.rejected.connect(d.reject);d.exec()
    def remove_named_location(self):
        locations=self.p.get('named_locations',[])
        if not locations:self.statusBar().showMessage('No custom named locations have been added.');return
        names=[str(i+1)+'. '+point['name'] for i,point in enumerate(locations)]
        selected,ok=QInputDialog.getItem(self,'Remove custom location','Location',names,0,False)
        if ok:locations.pop(names.index(selected));self.store.save();self.render_players()
    def moderate(self,action):
        if action=='unban':
            uid,ok=QInputDialog.getText(self,'Unban player','Platform user ID (for example steam_7656…):')
            if not ok or not uid:return
        else:
            r=self.player_table.currentRow()
            if r<0:return
            uid=self.players_data[r]['userId']
            if QMessageBox.question(self,action.capitalize()+' player?',action.capitalize()+' '+self.players_data[r].get('name',uid)+'?')!=QMessageBox.Yes:return
        self.action(action,userid=uid)
    def build_map(self):
        w,l=page('Live map','Player positions refresh with the REST API. Add a terrain image and calibrate its coordinate bounds.');self.map_hint=note('No live data yet.');l.addWidget(self.map_hint);self.map=MapWidget();l.addWidget(self.map,1);row(l,button('Map image & calibration…',self.calibrate_map),None,button('Export PNG',self.export_map));return w
    def calibrate_map(self):
        d=QDialog(self);d.setWindowTitle('Map calibration');v=QVBoxLayout(d);v.addWidget(note('REST world coordinates are converted to the in-game map grid. Bounds describe the edges of your image in map coordinates. Use the PalMap preset only with its full, uncropped PNG.'));f=QFormLayout();v.addLayout(f);path=line(self.p.get('map_image',''));f.addRow('Map image',path)
        def browse():
            name,_=QFileDialog.getOpenFileName(d,'Map image','','Images (*.png *.jpg *.jpeg *.webp)')
            if name:path.setText(name)
        f.addRow('',button('Browse…',browse));bounds=[]
        for title,value in zip(('Minimum X','Maximum X','Minimum Y','Maximum Y'),self.p.get('map_bounds',[-1000,1000,-1000,1000])):w=line(value);bounds.append(w);f.addRow(title,w)
        coordinate_mode=QComboBox();coordinate_mode.addItem('REST world coordinates (Palworld default)','world');coordinate_mode.addItem('Already in-game map coordinates','map');coordinate_mode.setCurrentIndex(max(0,coordinate_mode.findData(self.p.get('coordinate_space','world'))));f.addRow('Player coordinate format',coordinate_mode)
        def full_map():
            for widget,value in zip(bounds,FULL_MAP_BOUNDS):widget.setText(str(value))
            coordinate_mode.setCurrentIndex(0)
            for widget in checks.values():widget.setChecked(False)
        f.addRow('',button('Use full PalMap PNG bounds',full_map));f.addRow('',button('Open full map PNG download',lambda:QDesktopServices.openUrl(QUrl(MAP_DOWNLOAD))))
        checks={}
        for key,title in [('map_swap','Swap X and Y'),('map_flip_x','Flip horizontally'),('map_flip_y','Flip vertically')]:c=QCheckBox(title);c.setChecked(self.p.get(key,False));checks[key]=c;f.addRow(c)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(d.accept);b.rejected.connect(d.reject);v.addWidget(b)
        if d.exec()!=QDialog.Accepted:return
        try:
            values=[float(w.text()) for w in bounds]
            if not values[0]<values[1] or not values[2]<values[3]:raise ValueError('Minimum bounds must be less than maximum bounds')
            self.p['coordinate_space']=coordinate_mode.currentData();self.p['map_bounds']=values;self.p['map_image']=self.copy_asset(path.text(),'map_image');self.p.update({k:c.isChecked() for k,c in checks.items()});self.store.save();self.map.update_data(self.p,self.players_data);self.render_players()
        except Exception as e:self.show_error(str(e))
    def export_map(self):
        path,_=QFileDialog.getSaveFileName(self,'Export current map','player-locations.png','PNG image (*.png)')
        if path:Path(path).write_bytes(render_map(self.p,self.players_data))
    def build_console(self):
        w,l=page('Console','Live systemd journal, read securely over SSH.');self.console=QPlainTextEdit();self.console.setReadOnly(True);self.console.setMaximumBlockCount(3000);self.console.setPlaceholderText('Waiting for server logs…');l.addWidget(self.console,1);row(l,button('Refresh',self.refresh),button('Clear view',self.console.clear),None,button('Save visible log',self.export_log));return w
    def export_log(self):
        path,_=QFileDialog.getSaveFileName(self,'Save log','palworld.log','Log (*.log)')
        if path:Path(path).write_text(self.console.toPlainText(),encoding='utf-8')
    def build_backups(self):
        w,l=page('Backups','Verified archives of Pal/Saved, including world identity and configuration.');l.addWidget(note('A running world is warned, saved and briefly stopped for a consistent backup. Restore first takes another backup, then moves the old Saved directory to Linux Trash. A failed restore leaves the world stopped.'));self.backup_table=table(['Archive','Created','Size']);l.addWidget(self.backup_table,1)
        row(l,button('Take backup',lambda:self.action('backup'),'primary'),button('Refresh',self.load_backups),button('Download',self.download_backup),None,button('Restore selected',self.restore_backup),button('Move to Trash',self.trash_backup,'danger'));return w
    def build_save_repair(self):
        w,l=page('Save repair','Recover Pals locked to an expedition that no longer exists after a world transfer.')
        l.addWidget(note('Scan reads a copy through SSH without stopping the game. Recovery warns players, stops the world, creates a full backup, validates the selected records again, and restarts only if the world was running. Existing expeditions and unknown owners are blocked.'))
        self.repair_rows=[];self.repair_path='';self.repair_busy=False
        self.repair_scan_button=button('Scan world save',self.scan_save,'primary')
        self.repair_owner=QComboBox();self.repair_owner.setMinimumWidth(240);self.repair_owner.setAccessibleName('Player to recover');self.repair_owner.currentIndexChanged.connect(self.render_save_repair)
        row(l,self.repair_scan_button,QLabel('Player'),self.repair_owner,None)
        self.repair_summary=note('Scan a world save to inspect expedition assignments.');l.addWidget(self.repair_summary)
        self.repair_table=table(['Pal / nickname','Species','Expedition status','Pal ID']);self.repair_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for col,width in enumerate((220,180,280)):self.repair_table.setColumnWidth(col,width)
        l.addWidget(self.repair_table)
        self.repair_apply_button=button('Recover selected Pals',self.apply_save_repair,'primary')
        row(l,button('Select recoverable Pals',self.select_recoverable),None,self.repair_apply_button)
        return w
    def scan_save(self):
        if self.repair_busy:return
        p=copy.deepcopy(self.p);self.repair_busy=True;self.repair_scan_button.setEnabled(False);self.repair_apply_button.setEnabled(False)
        self.repair_rows=[];self.repair_path='';self.repair_table.setRowCount(0)
        self.repair_summary.setText('Reading available world saves through SSH…')
        self.on_event(p['id'],'progress','Save repair: finding world saves…')
        def choose(paths):
            if p['id']!=self.p['id']:self.finish_save_scan();return
            if not paths:self.finish_save_scan();self.repair_summary.setText('No supported Level.sav files found.');return
            path=paths[0]
            if len(paths)>1:
                path,ok=QInputDialog.getItem(self,'Select world save','World save',paths,0,False)
                if not ok:self.finish_save_scan();return
            self.repair_summary.setText('Downloading a read-only copy and validating expedition records…')
            def scan():
                import base64
                from .save_repair import inspect
                r=self.controller.remote(p);snapshot=r.call('read_world_save',{'path':path},timeout=180)
                self.bus.event.emit(p['id'],'progress','Save repair: parsing save and checking a no-change round trip…')
                preview=inspect(base64.b64decode(snapshot['data'],validate=True))
                if preview['hash']!=snapshot['hash']:raise RuntimeError('Save transfer hash mismatch')
                return preview
            def show(preview):
                if p['id']!=self.p['id']:return
                self.repair_rows=preview['pals'];self.repair_path=path
                owners={r['owner']:r['player'] for r in self.repair_rows}
                self.repair_owner.blockSignals(True);self.repair_owner.clear()
                for owner,name in sorted(owners.items(),key=lambda pair:pair[1]):self.repair_owner.addItem(name+' ('+owner[:8]+')',owner)
                self.repair_owner.blockSignals(False);self.render_save_repair()
                self.on_event(p['id'],'done','Save scan complete: '+str(len(self.repair_rows))+' expedition-assigned Pals. No server files changed.')
            job=self.run(scan,show);job.signals.error.connect(lambda text:self.on_event(p['id'],'error','Save scan failed: '+text));job.signals.finished.connect(self.finish_save_scan)
        job=self.run(lambda:self.controller.remote(p).call('list_world_saves'),choose)
        job.signals.error.connect(lambda text:(self.finish_save_scan(),self.on_event(p['id'],'error','Save scan failed: '+text)))
    def finish_save_scan(self):
        self.repair_busy=False;self.repair_scan_button.setEnabled(True);self.repair_apply_button.setEnabled(True)
    def render_save_repair(self,*args):
        owner=self.repair_owner.currentData();rows=[r for r in self.repair_rows if r['owner']==owner];self.repair_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            status='Missing expedition — recoverable' if r['recoverable'] else ('Existing expedition — blocked' if not r['stale'] else 'Ambiguous ownership / record — blocked')
            for col,text in enumerate((r['name'] or r['species'],r['species'],status,r['id'].split('/')[-1][:8])):
                cell=item(text);cell.setToolTip(r['id'] if col==3 else text);self.repair_table.setItem(i,col,cell)
            self.repair_table.item(i,0).setData(Qt.UserRole,r)
        self.repair_summary.setText(str(len(rows))+' expedition-assigned Pals; '+str(sum(r['recoverable'] for r in rows))+' eligible for recovery. Select the Pals you want to release.' if rows else 'No expedition-assigned Pals found for this player.')
    def select_recoverable(self):
        self.repair_table.clearSelection()
        for i in range(self.repair_table.rowCount()):
            if self.repair_table.item(i,0).data(Qt.UserRole)['recoverable']:
                for col in range(self.repair_table.columnCount()):self.repair_table.item(i,col).setSelected(True)
    def apply_save_repair(self):
        if self.repair_busy:return
        rows=[self.repair_table.item(i.row(),0).data(Qt.UserRole) for i in self.repair_table.selectionModel().selectedRows()]
        if not rows:self.show_error('Select one or more recoverable Pals.');return
        owner=self.repair_owner.currentData()
        if any(not r['recoverable'] or r['owner']!=owner for r in rows):self.show_error('Select only recoverable Pals belonging to this player.');return
        if QMessageBox.question(self,'Recover expedition Pals?',f"Release {len(rows)} Pals belonging to {rows[0]['player']}?\n\nThe world will be stopped after the configured player warning. A full backup and an original Level.sav recovery copy are created first. Any validation failure leaves the world stopped for inspection.")!=QMessageBox.Yes:return
        p=copy.deepcopy(self.p);path=self.repair_path;expected={r['id']:r['expedition'] for r in rows}
        self.repair_busy=True;self.repair_scan_button.setEnabled(False);self.repair_apply_button.setEnabled(False)
        def done(result):
            if p['id']!=self.p['id']:return
            self.repair_rows=[];self.repair_table.setRowCount(0);self.repair_summary.setText('Recovered '+str(result['recovered'])+' Pals. Backup: '+result['backup']+'. Ask the player to check their Palbox in-game.');self.refresh()
        job=self.run(lambda:self.controller.operate(p,'recover_expedition',path=path,owner=owner,expected=expected),done);job.signals.finished.connect(self.finish_save_scan)
    def load_backups(self):
        p=copy.deepcopy(self.p)
        def show(data):
            if self.p['id']!=p['id']:return
            self.backup_table.setRowCount(len(data))
            for r,b in enumerate(data):
                for c,value in enumerate((b['name'],datetime.datetime.fromtimestamp(b['time']).strftime('%Y-%m-%d %H:%M'),f'{b["size"]/1024**2:.1f} MB')):self.backup_table.setItem(r,c,item(value))
            self.backup_table.resizeColumnsToContents()
        self.run(lambda:self.controller.remote(p).call('list_backups'),show)
    def selected_backup(self):
        r=self.backup_table.currentRow();return self.backup_table.item(r,0).text() if r>=0 else None
    def download_backup(self):
        name=self.selected_backup()
        if not name:return
        path,_=QFileDialog.getSaveFileName(self,'Download backup',name,'Backup (*.tar.gz)')
        if path:
            p=copy.deepcopy(self.p);self.run(lambda:self.controller.remote(p).download_backup(name,path),lambda _:self.statusBar().showMessage('Backup downloaded.'))
    def restore_backup(self):
        name=self.selected_backup()
        if name and QMessageBox.question(self,'Restore world?',f'Restore {name}? Players will be warned before maintenance. Current saves will be backed up and moved to Trash.')==QMessageBox.Yes:self.action('restore',name=name)
    def trash_backup(self):
        name=self.selected_backup()
        if name and QMessageBox.question(self,'Move backup to Trash?',name)==QMessageBox.Yes:self.action('trash',path='.palmanager/backups/'+name)
    def build_schedule(self):
        w,l=page('Schedule & guardian','Control when maintenance happens and how a crashed world recovers.');l.addWidget(note('Install the Ubuntu worker to keep schedules, updates, notifications and your bot running when this PC is off. Without it, jobs run in this Windows app. Publish again after changing schedules, Discord routing or chat settings. The existing startup hook remains until you take over maintenance.'))
        self.worker_status_label=note('Ubuntu worker: Not checked · connect to verify installation.');l.addWidget(self.worker_status_label)
        row(l,button('Check worker status',lambda:self.refresh(verbose=True)),None)
        self.background_label=QLabel('Automation runs on Windows');self.background_label.setObjectName('subtitle');l.addWidget(self.background_label)
        row(l,button('Install / publish to Ubuntu',lambda:self.sync_background('install'),'primary'),button('Ubuntu bot runtime',lambda:self.sync_background('runtime')),button('Disable Ubuntu worker',lambda:self.sync_background('disable')))
        row(l,button('Enable crash guardian',lambda:self.action('guardian',enabled=True)),button('Disable guardian',lambda:self.action('guardian',enabled=False)),button('Take over maintenance…',self.take_over));self.auto_update=QCheckBox('Check Steam for updates every hour; warn players, back up and update when a new build exists');self.auto_update.clicked.connect(self.set_auto_update);l.addWidget(self.auto_update)
        self.schedule_table=table(['Action','Message','Timing','Next run (Windows local time)','Enabled','Ubuntu sync']);l.addWidget(self.schedule_table,1)
        self.schedule_sync_note=note('Ubuntu sync is verified against the running worker. Published means the configuration matches, not that a task has executed.');l.addWidget(self.schedule_sync_note)
        row(l,button('+ Add schedule',self.add_schedule,'primary'),button('Edit selected',self.edit_schedule),button('Toggle selected',self.toggle_schedule),None,button('Remove selected',self.remove_schedule));self.schedule_table.cellDoubleClicked.connect(lambda *_:self.edit_schedule());return w
    def take_over(self):
        if QMessageBox.question(self,'Take over maintenance?','Install a systemd override that disables existing ExecStartPre/ExecStopPost hooks and the runtime limit, and enables crash recovery? The original unit remains intact. Configure schedules here afterward. This does not restart the running world.')==QMessageBox.Yes:self.action('guardian',enabled=True,managed_maintenance=True)
    def set_auto_update(self,value):self.p['auto_update']=value;self.store.save()
    def render_worker_status(self):
        state=self.worker_states.get(self.p['id'])
        if state is None:text='Ubuntu worker: Not checked · connect to verify installation.'
        elif state.get('error'):text='Ubuntu worker: Status unavailable · '+state['error'][:220]
        elif not state['installed']:text='Ubuntu worker: Not installed · use Install / publish to Ubuntu to set it up.'
        else:
            active=state.get('active','unknown');health=state.get('health')
            status=('Running' if health else 'Running · health unavailable') if active=='active' else ('Stopped' if active=='inactive' else active.capitalize())
            text='Ubuntu worker: Installed · '+status+' · startup: '+state.get('enabled','unknown')+'\n'+state['unit']
            if health:text+=' · '+('Maintenance in progress' if health.get('busy') else 'Ready')
            if state.get('health_error'):text+='\n'+state['health_error'][:180]
        self.worker_status_label.setText(text)
    def render_schedule(self):
        selected=self.schedule_table.currentRow()
        selected_id=self.schedule_table.item(selected,0).data(Qt.UserRole) if selected>=0 and self.schedule_table.item(selected,0) else None
        self.render_worker_status()
        self.background_label.setText(('Automation target: Ubuntu worker · last published configuration' if self.p.get('background_enabled') else 'Automation target: Windows · jobs run while this app is open')+' · '+self.p.get('schedule_timezone','server local time'))
        self.auto_update.setChecked(self.p.get('auto_update',False));schedules=self.p.get('schedules',[]);self.schedule_table.setRowCount(len(schedules))
        for r,s in enumerate(schedules):
            values=[('Send message' if s['action']=='broadcast' else s['action']),s.get('message',''),('Every '+str(s['minutes'])+' minutes') if s['mode']=='interval' else 'Daily at '+s['at'],datetime.datetime.fromtimestamp(s['next']).strftime('%Y-%m-%d %H:%M') if s.get('next') else 'On next tick','Yes' if s.get('enabled') else 'No']
            sync=publication(s,self.p,self.worker_states.get(self.p['id']));values.append(sync)
            for c,v in enumerate(values):self.schedule_table.setItem(r,c,item(v))
            self.schedule_table.item(r,0).setData(Qt.UserRole,s['id'])
            cell=self.schedule_table.item(r,5);cell.setForeground(QColor({'Published':'#65dfb2','Changes pending':'#ffd080','Not published':'#ffad91','Not verified':'#a5b4c4'}[sync]));cell.setToolTip('Compared with the last successful worker health check. Publish after editing, toggling or removing tasks. Worker health is separate from publication status.')
            if s['id']==selected_id:self.schedule_table.selectRow(r)
        pending=remote_only(self.p,self.worker_states.get(self.p['id']))
        self.schedule_sync_note.setText((str(len(pending))+' task(s) still exist on Ubuntu but are absent locally. They can continue running until you publish again.\n' if pending else '')+'Ubuntu sync compares task settings and timezone with the worker. Published does not confirm execution; Not verified means a fresh worker check is needed.')
        self.schedule_table.resizeColumnsToContents();self.schedule_table.setColumnWidth(1,300)
    def sync_background(self,mode='install'):
        if self.p['id'] in self.controller.busy:self.show_error('Wait for the current world operation to finish.');return
        message={'install':'Install or update a root-owned background service on Ubuntu? It grants the steam account control of this Palworld service through a local permission-restricted socket. Existing game processes are not restarted. Configured webhook/bot secrets are stored root-only on Ubuntu.',
                 'runtime':'Install the Ubuntu bot runtime (python3-venv if needed, discord.py and Pillow) and publish this world’s configuration? This downloads dependencies on Ubuntu and enables the configured bot to run independently of Windows.',
                 'disable':'Stop and disable the Ubuntu manager worker? The game remains running. Schedules return to this Windows app. Worker files are retained for recovery.'}[mode]
        if QMessageBox.question(self,'Ubuntu background manager',message)!=QMessageBox.Yes:return
        p=copy.deepcopy(self.p)
        resource=(p['host'],p.get('port',22),p['root'].rstrip('/'))
        with self.controller.guard:lock=self.controller.locks.setdefault(resource,threading.Lock())
        if not lock.acquire(False):self.show_error('Another operation is already running for this world');return
        self.controller.busy.add(p['id'])
        def release():self.controller.busy.discard(p['id']);lock.release()
        def done(result):
            if mode!='disable':
                bot=self.bots.pop(p['id'],None)
                if bot:bot.stop()
            for saved in self.store.profiles:
                if saved['id']==p['id']:
                    saved['background_enabled']=mode!='disable'
                    if mode=='disable':
                        remote_schedules={s['id']:s for s in result.get('schedules',[])}
                        for schedule in saved.get('schedules',[]):
                            previous=remote_schedules.get(schedule['id'],{})
                            if previous and all(previous.get(k)==schedule.get(k) for k in ('action','mode','minutes','at','enabled','message')):schedule['next']=previous.get('next',0)
            self.worker_states.pop(p['id'],None);self.store.save();self.render_schedule();self.refresh();self.statusBar().showMessage('Ubuntu worker '+('disabled' if mode=='disable' else 'published and ready')+' · '+result['unit'])
        job=self.run(lambda:self.controller.remote(p).deploy_background(mode),done);job.signals.finished.connect(release)
    def add_schedule(self):
        self.schedule_dialog()
    def edit_schedule(self):
        r=self.schedule_table.currentRow()
        if r<0:self.show_error('Select a schedule to edit.');return
        self.schedule_dialog(self.p['schedules'][r])
    def schedule_dialog(self,existing=None):
        profile=self.p
        d=QDialog(self);d.setWindowTitle('Add maintenance schedule');v=QVBoxLayout(d);f=QFormLayout();v.addLayout(f);action=QComboBox();action.addItem('Backup','backup');action.addItem('Restart','restart');action.addItem('Send message','broadcast');message=line();message.setMaxLength(500);message.setPlaceholderText('Maintenance begins in 10 minutes. Please find a safe place.');message.setEnabled(False);action.currentIndexChanged.connect(lambda:message.setEnabled(action.currentData()=='broadcast'));mode=QComboBox();mode.addItems(['interval','daily']);minutes=QSpinBox();minutes.setRange(1,525600);minutes.setValue(360);at=line('04:00');f.addRow('Action',action);f.addRow('Message to players',message);f.addRow('Mode',mode);f.addRow('Interval (minutes)',minutes);f.addRow('Daily time (HH:MM)',at);b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);v.addWidget(b);b.accepted.connect(d.accept);b.rejected.connect(d.reject)
        enabled=QCheckBox('Enabled');enabled.setChecked(existing.get('enabled',True) if existing else True);f.addRow(enabled)
        if existing:
            d.setWindowTitle('Edit maintenance schedule');action.setCurrentIndex(action.findData(existing['action']));message.setText(existing.get('message',''));mode.setCurrentText(existing['mode']);minutes.setValue(existing.get('minutes',360));at.setText(existing.get('at','04:00'))
        if d.exec()!=QDialog.Accepted:return
        try:
            if action.currentData()=='broadcast' and not message.text().strip():raise ValueError('Enter the message to send to players')
            s=dict(id=existing['id'] if existing else uuid.uuid4().hex,action=action.currentData(),mode=mode.currentText(),minutes=minutes.value(),at=at.text(),enabled=enabled.isChecked())
            if s['action']=='broadcast':s['message']=message.text().strip()
            s['next']=next_run(s,timezone=profile.get('schedule_timezone'))
            if existing:
                if all(existing.get(k)==s.get(k) for k in ('action','mode','minutes','at','enabled','message')):s['next']=existing.get('next',s['next'])
                existing.clear();existing.update(s)
            else:profile.setdefault('schedules',[]).append(s)
            self.store.save();self.render_schedule()
        except Exception as e:self.show_error(str(e))
    def toggle_schedule(self):
        r=self.schedule_table.currentRow()
        if r>=0:s=self.p['schedules'][r];s['enabled']=not s['enabled'];s['next']=next_run(s,timezone=self.p.get('schedule_timezone'));self.store.save();self.render_schedule()
    def remove_schedule(self):
        r=self.schedule_table.currentRow()
        if r>=0:self.p['schedules'].pop(r);self.store.save();self.render_schedule()
    def build_mods(self):
        w,l=page('Mods','Manage compatible server content without losing recoverability.');self.mod_hint=note('Native Linux detected. Pocketpair’s official Workshop loader currently requires the Windows server build. UE4SS and PalSchema need native Linux binaries compatible with your exact game and glibc versions.');l.addWidget(self.mod_hint)
        row(l,button('Framework compatibility…',self.frameworks),button('Import mod…',self.import_mod,'primary'),button('Refresh',self.load_mods));self.mod_table=table(['Name','Kind','Enabled','Path']);l.addWidget(self.mod_table,1);row(l,button('Enable / disable selected',self.toggle_mod),None,button('Move selected to Trash',self.trash_mod,'danger'));return w
    def load_mods(self):
        p=copy.deepcopy(self.p)
        def show(data):
            if p['id']!=self.p['id']:return
            self.mod_table.setRowCount(len(data))
            for r,m in enumerate(data):
                for c,v in enumerate((m['name'],m['kind'],'Yes' if m['enabled'] else 'No',m['path'])):self.mod_table.setItem(r,c,item(v))
            self.mod_table.resizeColumnsToContents()
        self.run(lambda:self.controller.remote(p).call('list_mods'),show)
    def frameworks(self):
        QMessageBox.information(self,'Linux framework compatibility','This installation uses Ubuntu glibc 2.35 and native Palworld 1.0.4.\n\nThe inspected BlackBook and Xarmina UE4SS binaries require glibc 2.38; NullPrism requires 2.39. PalSchema 0.6.7 ships a Windows DLL. Those builds cannot safely be installed here.\n\nOne-click Workshop, UE4SS and PalSchema installation is unavailable for this verified configuration. Compatible Linux frameworks must be supplied and validated before Lua/JSON mods can be enabled. PAK imports are supported.\n\nSee the compatibility notes in README for sources and alternatives.')
    def import_mod(self):
        kind,ok=QInputDialog.getItem(self,'Import mod','Mod type',['pak','lua','schema'],0,False)
        if not ok:return
        path,_=QFileDialog.getOpenFileName(self,'Import '+kind+' mod','','PAK (*.pak)' if kind=='pak' else 'ZIP (*.zip)')
        if not path:return
        name,ok=QInputDialog.getText(self,'Mod name','Name (letters, numbers, spaces, underscores and hyphens):',text=Path(path).stem)
        if not ok:return
        p=copy.deepcopy(self.p)
        def install():
            r=self.controller.remote(p)
            if r.call('status')['ActiveState'] not in ('inactive','failed'):raise RuntimeError('Stop the world before importing mods')
            upload=r.upload(path);return self.controller.operate(p,'install_mod',kind=kind,name=name,upload=upload)
        self.run(install,lambda _:self.load_mods())
    def toggle_mod(self):
        r=self.mod_table.currentRow()
        if r>=0:self.action('toggle_mod',name=self.mod_table.item(r,0).text(),kind=self.mod_table.item(r,1).text(),enabled=self.mod_table.item(r,2).text()!='Yes')
    def trash_mod(self):
        r=self.mod_table.currentRow()
        if r>=0 and QMessageBox.question(self,'Move mod to Trash?',self.mod_table.item(r,0).text())==QMessageBox.Yes:self.action('trash',path=self.mod_table.item(r,3).text())
    def build_chat(self):
        w,l=page('Chat & broadcast','Send announcements and follow a configured server-side chat log.');self.chat_hint=note('The official REST API has announcements but no chat-reading endpoint. Chat appears only if your server or a compatible mod emits chat to the journal or a configured file. No chat bridge is installed automatically.');l.addWidget(self.chat_hint);self.chat=QPlainTextEdit();self.chat.setReadOnly(True);self.chat.setMaximumBlockCount(1000);l.addWidget(self.chat,1);self.message=line();self.message.setPlaceholderText('Announcement to all players…');self.message.setMaxLength(500);row(l,self.message,button('Broadcast',self.broadcast,'primary'));row(l,button('Configure chat source…',self.configure_chat),None)
        self.welcome_enabled=QCheckBox('Send a welcome announcement when a player joins');self.welcome_enabled.clicked.connect(self.save_welcome);l.addWidget(self.welcome_enabled)
        self.welcome_message=line();self.welcome_message.setMaxLength(500);f=QFormLayout();f.addRow('Welcome message',self.welcome_message);l.addLayout(f);row(l,button('Save welcome message',self.save_welcome),None)
        l.addWidget(note('Use {player} for the player name and {world} for the world name. Welcomes are broadcast to everyone. Requires the REST player list. Players already online when monitoring starts are not greeted. Windows must stay open, or publish changes in Schedule to run on Ubuntu.'));return w
    def render_welcome(self):
        self.welcome_enabled.setChecked(self.p.get('welcome_enabled',False));self.welcome_message.setText(self.p.get('welcome_message',DEFAULT_PROFILE['welcome_message']))
    def save_welcome(self):
        text=self.welcome_message.text().strip()
        if self.welcome_enabled.isChecked() and not text:
            self.show_error('Enter a welcome message before enabling it.');self.welcome_enabled.setChecked(self.p.get('welcome_enabled',False));return
        self.p['welcome_enabled']=self.welcome_enabled.isChecked();self.p['welcome_message']=text;self.store.save()
        if not self.p['welcome_enabled']:self.controller.welcome_seen.pop(self.p['id'],None)
        self.statusBar().showMessage('Welcome settings saved.'+(' Publish changes in Schedule to update Ubuntu.' if self.p.get('background_enabled') else ''))
    def broadcast(self):
        text=self.message.text().strip()
        if text:self.action('broadcast',message=text);self.message.clear()
    def configure_chat(self):
        d=QDialog(self);d.setWindowTitle('Chat log source');v=QVBoxLayout(d);v.addWidget(note('Leave path blank to parse the systemd journal. File paths are relative to the PalServer installation. The regex needs named groups name and message.'));f=QFormLayout();v.addLayout(f);path=line(self.p.get('chat_log',''));pattern=line(self.p.get('chat_regex',DEFAULT_PROFILE['chat_regex']));f.addRow('Relative log path',path);f.addRow('Chat regex',pattern);b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(d.accept);b.rejected.connect(d.reject);v.addWidget(b)
        if d.exec()!=QDialog.Accepted:return
        try:
            compiled=re.compile(pattern.text())
            if not {'name','message'}<=set(compiled.groupindex):raise ValueError('Regex needs (?P<name>…) and (?P<message>…) groups')
            self.p['chat_log']=path.text();self.p['chat_regex']=pattern.text();self.store.save();self.chat_offsets.pop(self.p['id'],None)
        except Exception as e:self.show_error(str(e))
    def build_discord(self):
        w,l=page('Discord','Route events to webhook channels and control a world with your own slash-command bot.');l.addWidget(note('Webhook URLs and bot tokens are encrypted with Windows DPAPI. No credentials ship in profile exports. Commands deny access unless a user ID or role ID is allowed. The bot does not read Discord messages.'))
        self.channel_table=table(['Channel','Routed events']);self.channel_table.setMaximumHeight(190);l.addWidget(self.channel_table);row(l,button('+ Webhook channel',self.add_channel),button('Edit routing',self.edit_channel),button('Remove channel',self.remove_channel))
        self.permissions_table=table(['Command','Allowed user IDs (comma separated)','Allowed role IDs (comma separated)']);self.permissions_table.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed);l.addWidget(self.permissions_table,1)
        row(l,button('Save permissions',self.save_permissions),button('Bot credentials…',self.bot_credentials),None,button('Start bot',self.start_bot,'primary'),button('Stop bot',self.stop_bot));return w
    def render_discord(self):
        channels=self.p.get('channels',[]);self.channel_table.setRowCount(len(channels))
        for r,c in enumerate(channels):self.channel_table.setItem(r,0,item(c['name']));self.channel_table.setItem(r,1,item(', '.join(c['events'])))
        self.channel_table.resizeColumnsToContents();self.permissions_table.setRowCount(len(COMMANDS))
        for r,command in enumerate(COMMANDS):
            title=item('/'+command);title.setFlags(title.flags()&~Qt.ItemIsEditable);self.permissions_table.setItem(r,0,title);rule=self.p.get('permissions',{}).get(command,{})
            for c,key in enumerate(('users','roles'),1):self.permissions_table.setItem(r,c,item(', '.join(rule.get(key,[]))))
        self.permissions_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
    def channel_dialog(self,existing=None):
        c=copy.deepcopy(existing or dict(id=uuid.uuid4().hex,name='Server events',events=['start','stop','restart','crash','backup','update','error']));d=QDialog(self);d.setWindowTitle('Discord webhook channel');v=QVBoxLayout(d);f=QFormLayout();v.addLayout(f);name=line(c['name']);url=line(self.store.credentials(self.p['id']).get('webhooks',{}).get(c['id'],''),True);f.addRow('Channel label',name);f.addRow('Discord webhook URL',url);checks={}
        for event in EVENTS:b=QCheckBox(event.capitalize());b.setChecked(event in c['events']);v.addWidget(b);checks[event]=b
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(d.accept);b.rejected.connect(d.reject);v.addWidget(b)
        if d.exec()!=QDialog.Accepted:return
        if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[A-Za-z0-9_.-]+',url.text()):self.show_error('Enter a valid Discord webhook URL.');return
        c['name']=name.text();c['events']=[e for e,b in checks.items() if b.isChecked()];secrets=self.store.credentials(self.p['id']);secrets.setdefault('webhooks',{})[c['id']]=url.text();self.store.set_credentials(self.p['id'],secrets);return c
    def add_channel(self):
        c=self.channel_dialog()
        if c:self.p.setdefault('channels',[]).append(c);self.store.save();self.render_discord()
    def edit_channel(self):
        r=self.channel_table.currentRow()
        if r<0:return
        c=self.channel_dialog(self.p['channels'][r])
        if c:self.p['channels'][r]=c;self.store.save();self.render_discord()
    def remove_channel(self):
        r=self.channel_table.currentRow()
        if r>=0:
            c=self.p['channels'].pop(r);secrets=self.store.credentials(self.p['id']);secrets.get('webhooks',{}).pop(c['id'],None);self.store.set_credentials(self.p['id'],secrets);self.store.save();self.render_discord()
    def save_permissions(self):
        try:
            rules={}
            for r,command in enumerate(COMMANDS):
                rules[command]={}
                for c,key in enumerate(('users','roles'),1):
                    values=[x.strip() for x in self.permissions_table.item(r,c).text().split(',') if x.strip()]
                    if any(not x.isdigit() for x in values):raise ValueError('Use numeric Discord IDs separated by commas')
                    rules[command][key]=values
            self.p['permissions']=rules;self.store.save();self.statusBar().showMessage('Command permissions saved. Empty lists deny everyone.')
        except Exception as e:self.show_error(str(e))
    def bot_credentials(self):
        d=QDialog(self);d.setWindowTitle('Discord bot credentials');v=QVBoxLayout(d);v.addWidget(note('Create a bot in the Discord Developer Portal and invite it with bot and applications.commands scopes. No Message Content intent is needed. Use a separate bot application for each world.'));f=QFormLayout();v.addLayout(f);guild=line(self.p.get('guild_id',''));token=line(self.store.credentials(self.p['id']).get('bot_token',''),True);f.addRow('Discord server / guild ID',guild);f.addRow('Bot token',token);b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(d.accept);b.rejected.connect(d.reject);v.addWidget(b)
        if d.exec()!=QDialog.Accepted:return
        if not guild.text().isdigit():self.show_error('Guild ID must be numeric');return
        self.p['guild_id']=guild.text();secrets=self.store.credentials(self.p['id']);secrets['bot_token']=token.text();self.store.set_credentials(self.p['id'],secrets);self.store.save()
    def start_bot(self):
        if self.p.get('background_enabled'):
            if not self.store.credentials(self.p['id']).get('bot_token') or not self.p.get('guild_id'):self.show_error('Configure bot credentials first');return
            self.p['bot_enabled']=True;self.store.save();self.sync_background('runtime');return
        try:
            if self.p['id'] in self.bots:raise ValueError('Stop the existing bot before starting another')
            token=self.store.credentials(self.p['id']).get('bot_token','')
            if not token or not self.p.get('guild_id'):raise ValueError('Configure bot credentials first')
            bot=WorldBot(copy.deepcopy(self.p),self.controller,token);self.bots[self.p['id']]=bot;bot.start();self.statusBar().showMessage('Connecting Discord bot…')
        except Exception as e:self.show_error(str(e))
    def stop_bot(self):
        if self.p.get('background_enabled'):self.p['bot_enabled']=False;self.store.save();self.sync_background('install');return
        bot=self.bots.pop(self.p['id'],None)
        if bot:bot.stop();self.statusBar().showMessage('Bot stopping…')
    def build_profile(self):
        w,l=page('World profile','Make it yours, move profiles between PCs, and keep removals recoverable.');self.banner_preview=QLabel();self.banner_preview.setFixedHeight(140);self.banner_preview.setAlignment(Qt.AlignCenter);self.banner_preview.setObjectName('note');l.addWidget(self.banner_preview)
        row(l,button('Profile icon…',lambda:self.choose_asset('icon')),button('Banner…',lambda:self.choose_asset('banner')),button('Accent color…',self.choose_accent),None)
        self.profile_details=note('');l.addWidget(self.profile_details);row(l,button('Export profile ZIP',self.export_profile,'primary'),button('Import profile ZIP',self.import_profile));l.addWidget(note('A profile ZIP includes connection details, appearance and redacted settings. Credentials, Discord destinations, active schedules and saves are excluded. Use Backups to move world saves. Imported settings are staged separately in the Settings tab.'))
        row(l,button('Manage save folders…',self.manage_saves),button('Remove profile',self.remove_profile),button('Trash server installation…',self.trash_installation,'danger'));l.addStretch();return w
    def copy_asset(self,path,key):
        if not path:return ''
        path=Path(path)
        if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or path.stat().st_size>50*1024*1024:raise ValueError('Choose an image under 50 MB')
        if QPixmap(str(path)).isNull():raise ValueError('Image could not be decoded')
        dest=self.store.directory/'assets'/self.p['id']/(key+path.suffix.lower());atomic(dest,path.read_bytes());return str(dest)
    def choose_asset(self,key):
        path,_=QFileDialog.getOpenFileName(self,'Choose '+key,'','Images (*.png *.jpg *.jpeg *.webp)')
        if not path:return
        try:self.p[key]=self.copy_asset(path,key);self.store.save();self.render_profile()
        except Exception as e:self.show_error(str(e))
    def choose_accent(self):
        c=QColorDialog.getColor(QColor(self.p.get('accent','#62dfb0')),self,'World accent')
        if c.isValid():self.p['accent']=c.name();self.store.save();self.render_profile()
    def render_profile(self):
        self.profile_details.setText(self.p['name']+'\n'+self.p['host']+' · '+self.p['user']+'\n'+self.p['root']+'\n'+self.p['service'])
        pix=QPixmap(self.p.get('banner',''))
        if pix.isNull():self.banner_preview.setPixmap(QPixmap());self.banner_preview.setText('◈  '+self.p['name']);self.banner_preview.setStyleSheet('font-size:28px;font-weight:650;color:'+self.p.get('accent','#62dfb0')+';background:#172939;border-radius:12px;')
        else:self.banner_preview.setPixmap(pix.scaled(850,140,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation))
        self.world_combo.setItemIcon(self.world_combo.currentIndex(),QIcon(self.p.get('icon','')))
    def export_profile(self):
        path,_=QFileDialog.getSaveFileName(self,'Export world profile',self.p['name']+'.zip','ZIP archive (*.zip)')
        if path:
            try:self.store.export_profile(self.p,path,self.settings_data['text'] if self.settings_data else '');self.statusBar().showMessage('Profile exported without secrets or automation.')
            except Exception as e:self.show_error(str(e))
    def import_profile(self):
        path,_=QFileDialog.getOpenFileName(self,'Import world profile','','ZIP archive (*.zip)')
        if path:
            try:p=self.store.import_profile(path);self.repopulate_worlds(p['id'])
            except Exception as e:self.show_error(str(e))
    def remove_profile(self):
        if len(self.store.profiles)==1:self.show_error('Add another world before removing the last profile.');return
        if self.p['id'] in self.controller.busy:self.show_error('Wait for the current operation to finish.');return
        if QMessageBox.question(self,'Remove profile?','This removes the local profile only. A recovery ZIP is moved to the Windows Recycle Bin. Server files are untouched.')!=QMessageBox.Yes:return
        try:
            dest=self.store.directory/(self.p['id']+'-removed.zip');self.store.export_profile(self.p,dest);recycle(dest);self.stop_bot();self.store.profiles.pop(self.world_combo.currentIndex());self.store.save();self.repopulate_worlds()
        except Exception as e:self.show_error(str(e))
    def manage_saves(self):
        p=copy.deepcopy(self.p)
        def show(paths):
            if not paths:QMessageBox.information(self,'Saves','No world save folders found.');return
            value,ok=QInputDialog.getItem(self,'Move save to Linux Trash','Select a save folder. World must be stopped.',paths,0,False)
            if ok and QMessageBox.question(self,'Trash save?',value)==QMessageBox.Yes:self.action('trash',path=value)
        self.run(lambda:self.controller.remote(p).call('list_saves'),show)
    def trash_installation(self):
        value,ok=QInputDialog.getText(self,'Move server files to Linux Trash','World must be stopped. Type the exact installation path to confirm:')
        if ok and value==self.p['root']:self.action('trash_installation',confirm=value)
    def closeEvent(self,event):
        if self.controller.busy:
            QMessageBox.information(self,'Operation running','Wait for maintenance to finish before closing the manager.');event.ignore();return
        active=bool(self.bots) or any(not p.get('background_enabled') and (p.get('auto_update') or any(s.get('enabled') for s in p.get('schedules',[]))) for p in self.store.profiles)
        if active and QMessageBox.question(self,'Close manager?','Closing pauses schedules, auto-update checks, Discord bots and chat relay. Ubuntu systemd crash recovery continues. Close?')!=QMessageBox.Yes:event.ignore();return
        self.controller.stopping=True
        for bot in self.bots.values():bot.stop()
        self.store.save();event.accept()

def launch():
    from PySide6.QtCore import QLockFile
    app=QApplication(sys.argv);app.setApplicationName('Palworld Manager');app.setOrganizationName('PalworldManager');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    try:store=Store()
    except Exception as e:QMessageBox.critical(None,'Profile storage error',str(e));return 1
    lock=QLockFile(str(store.directory/'app.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(0):QMessageBox.information(None,'Already running','Palworld Manager is already running for this Windows profile.');return 0
    window=MainWindow(store);window.show();return app.exec()
