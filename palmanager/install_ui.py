import copy,secrets,uuid
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QScrollArea,QWidget,QLabel,QCheckBox,QPlainTextEdit,QDialogButtonBox
from .ui import line,button,note,row
from .store import DEFAULT_PROFILE
from .remote import normalize_fingerprint
from .provision import discover_key,provision

class InstallDialog(QDialog):
    progress=Signal(str)
    def __init__(self,parent):
        super().__init__(parent);self.manager=parent;self.running=False;self.checked=None;self.new_id=uuid.uuid4().hex
        self.setWindowTitle('Install Palworld on Ubuntu');self.resize(780,880)
        layout=QVBoxLayout(self)
        layout.addWidget(note('Ubuntu 22.04+ on x86-64, with SSH, Python 3 and systemd. Use an existing non-root account with sudo access. The game runs under that account. Existing servers and saves are protected.'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();body.setObjectName('installerBody');body.setStyleSheet('QWidget#installerBody { background:#0d141e; } QLabel { color:#e7edf5; background:transparent; }');form=QFormLayout(body);form.setRowWrapPolicy(QFormLayout.WrapAllRows);scroll.setWidget(body);layout.addWidget(scroll,1)
        self.fields={}
        fields=[('host','Ubuntu SSH host',''),('port','SSH port','22'),('user','SSH account / server owner','ubuntu'),('password','SSH account password',''),('admin_password','Sudo password (blank: use SSH password)',''),('key_file','SSH private key file (optional)',''),('fingerprint','SSH server fingerprint',''),('name','World name','New Palworld server'),('slug','Directory name (also identifies the service)','world1'),('game_port','Game UDP port','8211'),('query_port','Query UDP port','27015'),('api_port','REST TCP port','8212'),('api_password','New server admin password',secrets.token_urlsafe(24))]
        for key,title,value in fields:
            widget=line(value);widget.setAccessibleName(title);label=QLabel(title);label.setBuddy(widget);form.addRow(label,widget);self.fields[key]=widget;widget.textChanged.connect(self.invalidate)
            if key=='fingerprint':
                self.fingerprint_button=button('Read SSH fingerprint',self.read_fingerprint);form.addRow(self.fingerprint_button)
                form.addRow(note('Verify the fingerprint using a trusted Ubuntu console before checking the box below. You can view host fingerprints with: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub (use the matching host key type).'))
                self.verified=QCheckBox('I verified this SSH fingerprint');self.verified.toggled.connect(self.invalidate);form.addRow(self.verified)
        for key in ('host','port','fingerprint'):self.fields[key].textChanged.connect(lambda *_:self.verified.setChecked(False))
        self.start=QCheckBox('Start the server when installation finishes');self.start.setChecked(True);self.start.toggled.connect(self.invalidate);form.addRow(self.start)
        self.ufw=QCheckBox('Allow the game UDP port in an already-active UFW firewall');self.ufw.toggled.connect(self.invalidate);form.addRow(self.ufw)
        form.addRow(note('REST is enabled with the admin password above for manager controls. Keep its TCP port private using your firewall. Router and cloud firewall rules remain manual; the wizard does not enable UFW or change its defaults.'))
        link=QLabel('<a href="https://store.steampowered.com/subscriber_agreement/">Review the Steam Subscriber Agreement</a>');link.setOpenExternalLinks(True);form.addRow(link)
        self.terms=QCheckBox('I accept the Steam terms required to install SteamCMD');self.terms.toggled.connect(self.update_buttons);form.addRow(self.terms)
        self.remember=QCheckBox('Save credentials encrypted on this Windows account');self.remember.setChecked(True);form.addRow(self.remember)
        self.summary=note('Enter the target host, read and verify its fingerprint, then check Ubuntu.');layout.addWidget(self.summary)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(160);layout.addWidget(self.log)
        self.check_button=button('Check Ubuntu',self.check);self.install_button=button('Install Palworld',self.install,'primary');self.install_button.setEnabled(False)
        self.close_button=button('Close',self.reject);row(layout,self.check_button,self.install_button,None,self.close_button)
        self.progress.connect(self.log_progress)
    def invalidate(self,*args):
        self.checked=None
        if hasattr(self,'install_button'):self.update_buttons()
    def update_buttons(self,*args):
        self.install_button.setEnabled(bool(self.checked) and self.terms.isChecked() and not self.running)
    def busy(self,value):
        self.running=value
        for w in [*self.fields.values(),self.verified,self.start,self.ufw,self.terms,self.remember,self.fingerprint_button,self.check_button,self.close_button]:w.setEnabled(not value)
        self.update_buttons()
    def reject(self):
        if self.running:return
        super().reject()
    def closeEvent(self,event):
        if self.running:event.ignore()
        else:super().closeEvent(event)
    def log_progress(self,message):
        self.log.appendPlainText(message)
        self.manager.on_event(self.manager.p['id'],'install',self.fields['host'].text()+': '+message)
    def fail(self,text):
        self.summary.setText('Could not complete: '+text);self.log_progress(text)
    def values(self):
        v={k:w.text().strip() if k not in ('password','admin_password','api_password') else w.text() for k,w in self.fields.items()}
        if not v['host']:raise ValueError('Enter the target Ubuntu host')
        if not self.verified.isChecked():raise ValueError('Read and verify the SSH fingerprint first')
        normalize_fingerprint(v['fingerprint'])
        if not v['fingerprint']:raise ValueError('An SSH fingerprint is required')
        if not 1<=int(v['port'])<=65535:raise ValueError('SSH port must be 1–65535')
        p=copy.deepcopy(DEFAULT_PROFILE);p.update(id=self.new_id,name=v['name'],host=v['host'],port=int(v['port']),user=v['user'],admin_user=v['user'],fingerprint=v['fingerprint'])
        credentials={'password':v['password'],'admin_password':v['admin_password'] or v['password'],'key_file':v['key_file'],'api_password':''}
        options={k:v[k] for k in ('user','slug','name','api_password')};options.update({k:int(v[k]) for k in ('game_port','query_port','api_port')});options.update(start=self.start.isChecked(),allow_ufw=self.ufw.isChecked(),accept_steam=self.terms.isChecked())
        return p,credentials,options
    def read_fingerprint(self):
        try:
            host=self.fields['host'].text().strip();port=int(self.fields['port'].text())
            if not host or not 1<=port<=65535:raise ValueError('Enter a host and valid SSH port first')
        except ValueError as e:self.fail(str(e));return
        self.busy(True);self.log_progress('Reading the SSH host key without logging in…')
        def done(pin):
            self.fields['fingerprint'].setText(pin);self.verified.setChecked(False);self.summary.setText('Observed '+pin+'. Verify this fingerprint through a trusted Ubuntu console.')
        job=self.manager.run(lambda:discover_key(host,port),done,quiet=True);job.signals.error.connect(self.fail);job.signals.finished.connect(lambda:self.busy(False))
    def check(self):
        try:p,credentials,options=self.values()
        except (ValueError,KeyError) as e:self.fail(str(e));return
        self.busy(True);self.summary.setText('Checking Ubuntu, sudo access, free resources, service name and ports…');self.log_progress('Running installation checks…')
        def done(result):
            self.checked=(p,credentials,options,result)
            self.summary.setText(f"{result['ubuntu']} · {result['ram_gib']} GiB RAM · {result['free_gib']} GiB free\nDirectory: {result['root']}\nService: {result['service']}\nWill install SteamCMD and Palworld, enable startup"+(' and start the server.' if options['start'] else '. Server will remain stopped.')+('\nResume partial installation.' if result['resume'] else '')+('\n'+' '.join(result['warnings']) if result['warnings'] else ''))
            self.log_progress('Checks passed. Review the installation and accept Steam terms to install.')
        job=self.manager.run(lambda:provision(p,credentials,dict(options,action='inspect'),self.progress.emit),done,quiet=True);job.signals.error.connect(self.fail);job.signals.finished.connect(lambda:self.busy(False))
    def install(self):
        if not self.checked or not self.terms.isChecked() or self.running:return
        p,credentials,options,report=self.checked;options=dict(options,action='install',accept_steam=True)
        self.busy(True);self.summary.setText('Installing on '+p['host']+'. Keep this app open; progress appears below and in Activity.')
        def done(result):
            p.update(root=result['root'],service=result['service'],steamcmd=result['steamcmd'],api_port=result['api_port'],game_port=result['game_port'],query_port=result['query_port'])
            # Store the profile first so a credential-storage problem does not lose the installation.
            self.manager.store.profiles.append(p);self.manager.store.save()
            try:self.manager.store.set_credentials(p['id'],credentials,self.remember.isChecked())
            except Exception as e:self.log_progress('Profile saved; credential storage failed. Re-enter credentials in Connection: '+str(e))
            self.manager.repopulate_worlds(p['id']);self.checked=None
            message='Installation complete. Connection profile saved. '+('Server is responding to REST.' if result['started'] else result['startup_error'] or 'Server is installed and stopped; use Start when ready.')
            self.summary.setText(message);self.log_progress(message)
        job=self.manager.run(lambda:provision(p,credentials,options,self.progress.emit),done,quiet=True);job.signals.error.connect(self.fail);job.signals.finished.connect(lambda:self.busy(False))
