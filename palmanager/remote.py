import base64,hashlib,http.client,json,re,shlex,socket,time,uuid,threading,struct
from pathlib import Path
import paramiko
from . import settings
from .rcon import execute as execute_rcon

def fingerprint(key): return 'SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')

def normalize_fingerprint(value):
    value=(value or '').strip()
    if not value:return ''
    message='SSH fingerprint must be SHA256: followed by the server key fingerprint. This field identifies the server; enter passwords in the account password fields.'
    if not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}=?',value):raise ValueError(message)
    encoded=value[7:].rstrip('=')
    try:decoded=base64.b64decode(encoded+'=',validate=True)
    except ValueError:raise ValueError(message) from None
    if len(decoded)!=32 or base64.b64encode(decoded).decode().rstrip('=')!=encoded:raise ValueError(message)
    return 'SHA256:'+encoded

class HostKeyRequired(Exception): pass

class PinPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self,pin): self.pin=normalize_fingerprint(pin)
    def missing_host_key(self,client,hostname,key):
        actual=fingerprint(key)
        if not self.pin: raise HostKeyRequired('Verify this SSH host key in the connection profile: '+actual)
        if actual!=self.pin: raise RuntimeError('SSH host key changed. Connection blocked. Observed: '+actual)

class Remote:
    def __init__(self,profile,secrets): self.p=profile.copy();self.secrets=secrets.copy()
    def connect(self,admin=False):
        c=paramiko.SSHClient();c.set_missing_host_key_policy(PinPolicy(self.p.get('fingerprint','')))
        user=self.p.get('admin_user') if admin else self.p['user']
        password=self.secrets.get('admin_password' if admin else 'password')
        try:
            c.connect(self.p['host'],port=int(self.p.get('port',22)),username=user,password=password or None,
                key_filename=self.secrets.get('key_file') or None,look_for_keys=not bool(password),allow_agent=not bool(password),timeout=12,banner_timeout=12,auth_timeout=12)
            c.get_transport().set_keepalive(20);return c
        except Exception: c.close();raise
    @staticmethod
    def execute(c,command,data='',timeout=60):
        i,o,e=c.exec_command(command,timeout=timeout)
        i.write(data);i.flush();i.channel.shutdown_write()
        channel=o.channel;out=bytearray();err=bytearray();deadline=time.monotonic()+timeout
        while True:
            while channel.recv_ready(): out.extend(channel.recv(65536))
            while channel.recv_stderr_ready(): err.extend(channel.recv_stderr(65536))
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready(): break
            if time.monotonic()>deadline: channel.close();raise TimeoutError('Remote operation timed out; inspect server status before retrying')
            time.sleep(.02)
        code=channel.recv_exit_status()
        if code: raise RuntimeError(err.decode('utf-8','replace')[-3000:] or 'Remote command failed (exit '+str(code)+')')
        return out.decode('utf-8','replace')
    def call(self,action,args=None,timeout=120):
        folder=Path(__file__).parent
        source=(folder/'settings.py').read_text('utf-8')+'\n'+(folder/'remote_agent.py').read_text('utf-8')
        code="import base64;exec(compile(base64.b64decode('"+base64.b64encode(source.encode()).decode()+"'),'<palmanager>','exec'))"
        c=self.connect()
        try:
            raw=self.execute(c,'python3 -c '+shlex.quote(code),json.dumps({'root':self.p['root'],'service':self.p['service'],'action':action,'args':args or {}}),timeout)
            obj=json.loads(raw)
            if not obj['ok']: raise RuntimeError(obj['error'])
            return obj['result']
        finally: c.close()
    def control(self,action):
        if action not in ('start','stop','restart'): raise ValueError('Invalid service action')
        unit=self.p['service']
        if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',unit): raise ValueError('Invalid service name')
        c=self.connect(admin=True)
        try: return self.execute(c,'sudo -S -p "" -- systemctl '+action+' '+shlex.quote(unit),self.secrets.get('admin_password','')+'\n',900)
        finally: c.close()
    def acquire_workflow(self):
        """Hold a server-side lock across stop/backup/update/start, including other clients."""
        script="import pathlib,fcntl,sys; r=pathlib.Path("+repr(self.p['root'])+").resolve(); assert (r/'PalServer.sh').is_file(), 'Invalid installation'; p=r/'.palmanager'; p.mkdir(exist_ok=True,mode=448); f=(p/'workflow.lock').open('a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print('READY',flush=True); sys.stdin.read()"
        c=self.connect()
        try:
            i,o,e=c.exec_command('python3 -c '+shlex.quote(script),timeout=15)
            if o.readline().strip()!='READY':raise RuntimeError('Another maintenance operation is running on this server')
            return c,i
        except Exception:c.close();raise
    def release_workflow(self,workflow):
        try:workflow[1].channel.shutdown_write()
        except Exception:pass
        workflow[0].close()
    def api(self,endpoint,payload=None):
        if endpoint not in ('info','players','settings','metrics','announce','kick','ban','unban','save','shutdown','stop'): raise ValueError('Invalid API endpoint')
        password=self.secrets.get('api_password')
        if not password:
            cfg=self.call('read_settings');values=settings.parse(cfg['text'])
            if values.get('RESTAPIEnabled','False').lower()!='true': raise RuntimeError('REST API is disabled. Enable REST in Settings and restart the world.')
            password=values.get('AdminPassword','""').strip('"')
        c=self.connect();conn=None
        try:
            try:channel=c.get_transport().open_channel('direct-tcpip',('127.0.0.1',int(self.p.get('api_port',8212))),('127.0.0.1',0),timeout=10)
            except paramiko.ChannelException as e:
                if e.code==2:raise RuntimeError('REST API is not accepting connections on port '+str(self.p.get('api_port',8212))+'. After enabling REST in Settings, restart the world to apply it; otherwise check that the configured REST port matches.') from None
                raise
            channel.settimeout(15)
            conn=http.client.HTTPConnection('127.0.0.1',timeout=15);conn.sock=channel
            headers={'Authorization':'Basic '+base64.b64encode(('admin:'+password).encode()).decode(),'Content-Type':'application/json'}
            conn.request('POST' if payload is not None else 'GET','/v1/api/'+endpoint,json.dumps(payload) if payload is not None else None,headers)
            response=conn.getresponse();body=response.read(4*1024*1024)
            if response.status>=400: raise RuntimeError('Palworld REST '+str(response.status)+': '+body.decode('utf-8','replace')[:300])
            return json.loads(body) if body.strip() else {'ok':True}
        finally:
            if conn: conn.close()
            c.close()
    def wait_state(self,expected,timeout=180):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.call('status')
            if state.get('ActiveState') in expected: return state
            time.sleep(2)
        raise TimeoutError('Server did not reach '+str(expected))
    def rcon(self,command):
        if command!='Save' and not command.startswith('Broadcast '): raise ValueError('Only Save and Broadcast use the RCON fallback')
        values=settings.parse(self.call('read_settings')['text'])
        if values.get('RCONEnabled','False').lower()!='true': raise RuntimeError('REST and RCON are unavailable; cannot notify players or save safely')
        password=values.get('AdminPassword','""')[1:-1]
        c=self.connect()
        try:
            ch=c.get_transport().open_channel('direct-tcpip',('127.0.0.1',int(values.get('RCONPort','25575'))),('127.0.0.1',0),timeout=10);ch.settimeout(15)
            return execute_rcon(ch,password,command)
        finally:c.close()
    def upload(self,path):
        name=uuid.uuid4().hex+Path(path).suffix
        c=self.connect()
        try:
            # Constant subdirectory, quoted root; no shell interpolation of filenames.
            directory=self.p['root'].rstrip('/')+'/.palmanager/uploads'
            self.execute(c,'mkdir -p -- '+shlex.quote(directory))
            s=c.open_sftp()
            try: s.put(str(path),directory+'/'+name);s.chmod(directory+'/'+name,0o600)
            finally:s.close()
        finally:c.close()
        return name
    def download_backup(self,name,dest):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.tar\.gz',name): raise ValueError('Invalid backup name')
        c=self.connect()
        try:
            s=c.open_sftp()
            try:s.get(self.p['root'].rstrip('/')+'/.palmanager/backups/'+name,str(dest))
            finally:s.close()
        finally:c.close()
    def update_build(self):
        if self.call('status')['ActiveState'] not in ('inactive','failed'): raise RuntimeError('Stop the server before updating')
        c=self.connect()
        try:
            result=self.execute(c,shlex.quote(self.p.get('steamcmd','/usr/games/steamcmd'))+' +force_install_dir '+shlex.quote(self.p['root'])+' +login anonymous +app_update 2394010 validate +quit',timeout=3600)
            if "Success! App '2394010' fully installed" not in result: raise RuntimeError('SteamCMD did not confirm a successful update. Inspect the service before starting.')
            return 'SteamCMD update verified'
        finally:c.close()
    def latest_build(self):
        c=self.connect()
        try:
            raw=self.execute(c,shlex.quote(self.p.get('steamcmd','/usr/games/steamcmd'))+' +login anonymous +app_info_update 1 +app_info_print 2394010 +quit',timeout=180)
            m=re.search(r'"public"\s*\{\s*"buildid"\s*"(\d+)"',raw)
            if not m: raise RuntimeError('Could not read public Steam build ID')
            return m.group(1)
        finally:c.close()
    def guardian(self,enabled,managed_maintenance=False):
        unit=self.p['service']
        if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',unit): raise ValueError('Invalid service')
        text='[Service]\nRestart='+('on-failure' if enabled else 'no')+'\nRestartSec=15\n'
        if managed_maintenance: text+='ExecStartPre=\nExecStopPost=\nRuntimeMaxSec=infinity\n'
        script="import pathlib,subprocess,re; p=pathlib.Path("+repr('/etc/systemd/system/'+unit+'.d/90-palmanager.conf')+"); p.parent.mkdir(parents=True,exist_ok=True); old=p.read_text() if p.exists() else ''; new="+repr(text)+"; new=new+('ExecStartPre=\\nExecStopPost=\\nRuntimeMaxSec=infinity\\n' if 'ExecStartPre=' in old and 'ExecStartPre=' not in new else ''); p.write_text(new); subprocess.run(['systemctl','daemon-reload'],check=True)"
        c=self.connect(True)
        try: self.execute(c,'sudo -S -p "" -- python3 -c '+shlex.quote(script),self.secrets.get('admin_password','')+'\n')
        finally:c.close()
        return 'Systemd guardian configured. Maintenance ownership: '+('manager' if managed_maintenance else 'existing service')
    def background_id(self):return hashlib.sha256((self.p['service']+'\n'+self.p['root'].rstrip('/')).encode()).hexdigest()[:16]
    def worker_status(self):
        ident=self.background_id();unit='palmanager-'+ident+'.service'
        script=r"""import json,subprocess,socket,pathlib
unit=UNIT
result=subprocess.run(['systemctl','show',unit,'--property=LoadState,ActiveState,SubState,UnitFileState'],capture_output=True,text=True,timeout=10)
values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
if not values.get('LoadState'):raise RuntimeError('Unable to query Ubuntu worker service: '+result.stderr.strip())
installed=values['LoadState']!='not-found' or pathlib.Path(CODE_PATH).exists()
output={'installed':installed,'unit':unit,'active':values.get('ActiveState','unknown'),'substate':values.get('SubState','unknown'),'enabled':values.get('UnitFileState','unknown'),'health':None,'health_error':''}
if installed and output['active']=='active':
 try:
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
   connection.settimeout(3);connection.connect(SOCKET_PATH);connection.sendall(b'{"action":"health","args":{}}\n')
   with connection.makefile('rb') as stream:reply=json.loads(stream.readline(65536))
   if not reply.get('ok'):raise RuntimeError(reply.get('error','Worker health check failed'))
   output['health']=reply['result']
 except Exception as error:output['health_error']=str(error)
print(json.dumps(output))
""".replace('UNIT',repr(unit)).replace('CODE_PATH',repr('/opt/palworld-manager/'+ident)).replace('SOCKET_PATH',repr('/run/palmanager-'+ident+'.sock'))
        connection=self.connect()
        try:return json.loads(self.execute(connection,'python3 -c '+shlex.quote(script),timeout=25))
        finally:connection.close()
    def deploy_background(self,mode='install'):
        folder=Path(__file__).parent
        previous=None
        if mode=='disable':
            try:previous=self.background_action('health',{})
            except Exception:pass
        names=['__init__.py','settings.py','remote_agent.py','controller.py','background.py','discord_bot.py','rcon.py','coordinates.py']
        files={name:(folder/name).read_text('utf-8') for name in names}
        profile=dict(self.p)
        for key in ('icon','banner','map_image'):profile[key]=''
        assets={}
        image=self.p.get('map_image','')
        if image and Path(image).is_file() and Path(image).stat().st_size<=50*1024*1024:assets['map']=base64.b64encode(Path(image).read_bytes()).decode()
        payload={'mode':mode,'profile':profile,'files':files,'assets':assets,'secrets':{k:v for k,v in self.secrets.items() if k in ('webhooks','bot_token')}}
        script=(folder/'worker_install.py').read_text('utf-8')
        code="import base64;exec(compile(base64.b64decode('"+base64.b64encode(script.encode()).decode()+"'),'<worker-install>','exec'))"
        c=self.connect(True)
        try:
            raw=self.execute(c,'sudo -S -p "" -- python3 -c '+shlex.quote(code),self.secrets.get('admin_password','')+'\n'+json.dumps(payload),4500)
            result=json.loads(raw)
            if not result['ok']:raise RuntimeError(result['error'])
        finally:c.close()
        if mode!='disable':
            for _ in range(15):
                try:self.background_action('health',{});break
                except Exception:time.sleep(1)
            else:raise RuntimeError('Worker installed but did not become ready. Inspect journalctl -u palmanager-'+self.background_id()+'.service')
        if previous:result['result']['schedules']=previous.get('schedules',[])
        return result['result']
    def background_action(self,action,args):
        path='/run/palmanager-'+self.background_id()+'.sock'
        script="import socket,sys; s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(4200); s.connect("+repr(path)+"); s.sendall(sys.stdin.buffer.read()+b'\\n'); f=s.makefile('rb'); print(f.readline().decode()); s.close()"
        c=self.connect()
        try:
            data=json.loads(self.execute(c,'python3 -c '+shlex.quote(script),json.dumps({'action':action,'args':args}),4250))
            if not data['ok']:raise RuntimeError(data['error'])
            return data['result']
        finally:c.close()
