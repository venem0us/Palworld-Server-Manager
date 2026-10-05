"""Ubuntu installer sent through pinned SSH. Root installs packages/unit only.

settings.py is prepended by the Windows client. Game downloads run as the SSH user.
"""
import os,sys,json,re,pwd,platform,shutil,socket,subprocess,time,hashlib,fcntl,tempfile,signal
from pathlib import Path

STATE=Path('/var/lib/palworld-manager-installer')
UNITS=Path('/etc/systemd/system')

def emit(message):print(json.dumps({'event':'progress','message':message}),flush=True)

def run(args,stage,timeout=900,input=None):
    emit(stage)
    process=subprocess.Popen(args,stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',LC_ALL='C'))
    start=time.monotonic();first=True
    while True:
        try:
            output,_=process.communicate(input=input if first else None,timeout=10)
            if process.returncode:raise RuntimeError(stage+' failed: '+output[-1800:])
            return output
        except subprocess.TimeoutExpired:
            first=False
            if time.monotonic()-start>timeout:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.communicate(timeout=15)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.communicate()
                raise TimeoutError(stage+' timed out; partial installation retained for retry')
            emit(stage+' ('+str(int(time.monotonic()-start))+' seconds elapsed)')

def clean_path(path):
    p=Path(path)
    if not p.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(p)) or '..' in p.parts:raise ValueError('Unsupported home/directory path')
    for component in (p,*p.parents):
        if component.is_symlink():raise ValueError('Installation paths cannot contain symbolic links')
    return p

def config(data):
    user=data.get('user','');slug=data.get('slug','')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',user) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',slug):raise ValueError('Use a valid Ubuntu username and a directory name containing lowercase letters, numbers or hyphens')
    account=pwd.getpwnam(user)
    if account.pw_uid==0:raise ValueError('Use an existing non-root SSH account with sudo access; the game must not run as root')
    if account.pw_shell.endswith(('nologin','false')):raise ValueError('The server owner needs a login shell')
    home=clean_path(account.pw_dir)
    if home==Path('/') or not home.is_dir() or home.stat().st_uid!=account.pw_uid:raise ValueError('The SSH account needs its own existing home directory')
    root=clean_path(home/'PalServers'/slug)
    ports={k:int(data[k]) for k in ('game_port','query_port','api_port')}
    if any(not 1024<=p<=65535 for p in ports.values()) or len(set(ports.values()))!=3:raise ValueError('Choose three distinct ports between 1024 and 65535')
    name=data.get('name','').strip()
    if not name or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('World name must contain 1–80 printable characters')
    service='palworld-'+slug+'.service'
    public=dict(user=user,slug=slug,root=str(root),home=str(home),service=service,name=name,**ports)
    ident=hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()
    return public,account,STATE/(service+'.json'),ident

def unit_text(p):
    return '''[Unit]
Description=Palworld dedicated server
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User={user}
WorkingDirectory={root}
Environment=HOME={home}
ExecStart={root}/PalServer.sh -port={game_port} -QueryPort={query_port}
Restart=on-failure
RestartSec=15
KillSignal=SIGINT
TimeoutStopSec=180
LimitNOFILE=100000
UMask=0077

[Install]
WantedBy=multi-user.target
'''.format(**p)

def available(port,kind):
    sock=socket.socket(socket.AF_INET,kind)
    try:sock.bind(('0.0.0.0',port))
    except OSError:return False
    finally:sock.close()
    return True

def inspect(data):
    if os.geteuid()!=0:raise ValueError('Sudo authentication is required')
    release={}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            k,v=line.split('=',1);release[k]=v.strip('"')
    try:version=tuple(int(x) for x in release.get('VERSION_ID','0').split('.'))
    except ValueError:version=(0,)
    if release.get('ID')!='ubuntu' or version<(22,4):raise ValueError('This installer supports Ubuntu 22.04 and newer')
    if platform.machine()!='x86_64':raise ValueError('Native Palworld/SteamCMD installation requires x86-64; ARM is unsupported')
    if not Path('/run/systemd/system').is_dir() or not shutil.which('systemctl'):raise ValueError('A running systemd installation is required')
    if not shutil.which('apt-get') or not shutil.which('runuser'):raise ValueError('Ubuntu apt-get and runuser are required')
    p,account,marker,ident=config(data);root=Path(p['root']);unit=UNITS/p['service']
    clean_path(unit);clean_path(marker)
    old=json.loads(marker.read_text()) if marker.exists() else {}
    resume=old.get('identity')==ident and old.get('phase') in ('download','configured')
    # Check all unit search paths, including vendor units and active transient units.
    response=subprocess.run(['systemctl','show',p['service'],'-p','LoadState','--value'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    load=response.stdout.strip()
    if getattr(response,'returncode',0) and load!='not-found':raise ValueError('Could not query systemd service state')
    if (unit.exists() or load not in ('not-found','')) and not (resume and unit.is_file() and unit.read_text()==unit_text(p)):
        raise ValueError('That service already exists. Choose a different directory name or connect to the existing server.')
    if root.exists() and (not root.is_dir() or (any(root.iterdir()) and not resume)):
        raise ValueError('Installation directory is not empty. Existing installations and saves are never overwritten.')
    if root.exists() and list(root.glob('Pal/Saved/SaveGames/**/*.sav')):raise ValueError('This directory already has world saves; use Connection to manage it')
    if resume and subprocess.run(['systemctl','is-active',p['service']],stdout=subprocess.PIPE,text=True).stdout.strip()=='active':raise ValueError('The partial installation is running; stop it before retrying')
    volume=root
    while not volume.exists():volume=volume.parent
    free=shutil.disk_usage(volume).free
    required=1 if resume and old.get('phase')=='configured' else 15
    if free<required*1024**3:raise ValueError('At least '+str(required)+' GiB of free space is required for this installation')
    memory=int(re.search(r'MemTotal:\s+(\d+)',Path('/proc/meminfo').read_text())[1])*1024
    if memory<7*1024**3:raise ValueError('At least 8 GB RAM is required; 16 GB or more is recommended')
    for key,kind in [('game_port',socket.SOCK_DGRAM),('query_port',socket.SOCK_DGRAM),('api_port',socket.SOCK_STREAM)]:
        if not available(p[key],kind):raise ValueError(key.replace('_',' ').capitalize()+' is already in use')
    if data.get('allow_ufw'):
        if not shutil.which('ufw'):raise ValueError('UFW is not installed; turn off the optional UFW step')
        status=subprocess.check_output(['ufw','status'],text=True,env=dict(os.environ,LC_ALL='C'))
        if not re.search(r'^Status: active',status,re.M):raise ValueError('UFW is inactive; turn off the optional UFW step. The wizard will not enable it.')
    warnings=[]
    if memory<15*1024**3:warnings.append('Less than 16 GB RAM: out-of-memory crashes are more likely.')
    if (os.cpu_count() or 1)<4:warnings.append('Fewer than four CPU threads are available.')
    return dict(p,ubuntu=release.get('PRETTY_NAME','Ubuntu'),free_gib=round(free/1024**3,1),ram_gib=round(memory/1024**3,1),warnings=warnings,resume=resume)

def root_write(path,text,mode):
    clean_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(temp,mode);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def install(data):
    if not data.get('accept_steam'):raise ValueError('Accept the Steam terms in the installation wizard first')
    admin=data.get('api_password','')
    if not 16<=len(admin)<=128 or any(c in admin for c in '\r\n\0"\\'):raise ValueError('Use a REST admin password of 16–128 characters without quotes, backslashes or line breaks')
    with open('/run/lock/palworld-manager-install.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another Palworld installation is in progress')
        report=inspect(data);p,account,marker,ident=config(data)
        phase=json.loads(marker.read_text()).get('phase') if marker.exists() else None
        def save_phase(phase):root_write(marker,json.dumps({'identity':ident,'phase':phase}),0o600)
        user_prefix=['runuser','-u',p['user'],'--','env','HOME='+p['home']]
        if phase!='configured':
            run(['apt-get','update'],'Refreshing Ubuntu package indexes')
            run(['apt-get','install','-y','software-properties-common','ca-certificates'],'Installing package prerequisites')
            run(['add-apt-repository','-y','multiverse'],'Enabling Ubuntu multiverse for SteamCMD')
            run(['dpkg','--add-architecture','i386'],'Enabling SteamCMD 32-bit dependencies')
            run(['apt-get','update'],'Refreshing SteamCMD package indexes')
            run(['debconf-set-selections'],'Recording accepted Steam license',input='steam steam/question select I AGREE\nsteam steam/license note\n')
            run(['apt-get','install','-y','steamcmd','lib32gcc-s1','lib32stdc++6'],'Installing SteamCMD and runtime libraries',timeout=1800)
            save_phase('download')
            run(user_prefix+['mkdir','-p',p['root']],'Creating the world directory')
            downloaded=run(user_prefix+['/usr/games/steamcmd','+force_install_dir',p['root'],'+login','anonymous','+app_update','2394010','validate','+quit'],'Downloading and validating Palworld (this can take several minutes)',timeout=7200)
            if "Success! App '2394010' fully installed" not in downloaded:raise RuntimeError('SteamCMD did not confirm a successful download. Partial files are retained for retry.')
            root=Path(p['root']);clean_path(root/'PalServer.sh');clean_path(root/'DefaultPalWorldSettings.ini')
            if not (root/'PalServer.sh').is_file() or not (root/'DefaultPalWorldSettings.ini').is_file():raise RuntimeError('SteamCMD did not produce a complete Palworld installation; retry the wizard')
            # SDK/config writes run as the unprivileged owner, never recursively chown a home.
            setup='''import pathlib,shutil,sys,os,json
p=json.loads(sys.stdin.read());home=pathlib.Path(p['home']);root=pathlib.Path(p['root'])
sdk=home/'.steam/sdk64/steamclient.so'
if not sdk.exists():
 candidates=[home/'.steam/steamcmd/linux64/steamclient.so',home/'.steam/steam/linux64/steamclient.so',home/'Steam/linux64/steamclient.so',home/'.local/share/Steam/steamcmd/linux64/steamclient.so',pathlib.Path('/usr/lib/games/steam/linux64/steamclient.so')]
 source=next((x for x in candidates if x.is_file()),None)
 if source is None:raise RuntimeError('SteamCMD steamclient.so was not found')
 sdk.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,sdk)
cfg=root/'Pal/Saved/Config/LinuxServer/PalWorldSettings.ini'
if cfg.exists() and cfg.stat().st_size:
 if cfg.read_text('utf-8')==p['settings']:sys.exit(0)
 raise RuntimeError('Existing settings found; refusing to overwrite')
cfg.parent.mkdir(parents=True,exist_ok=True)
with cfg.open('w',encoding='utf-8') as f:f.write(p['settings'])
os.chmod(cfg,0o600)
'''
            cfg='[/Script/Pal.PalGameWorldSettings]\nOptionSettings=()\n'
            defaults=parse((root/'DefaultPalWorldSettings.ini').read_text('utf-8-sig'))
            text=patch(cfg,{'ServerName':json.dumps(p['name'],ensure_ascii=False),'AdminPassword':json.dumps(admin,ensure_ascii=False),'PublicPort':str(p['game_port']),'RESTAPIEnabled':'True','RESTAPIPort':str(p['api_port']),'RCONEnabled':'False'},defaults)
            run(user_prefix+['python3','-c',setup],'Configuring the Steam SDK and server settings',input=json.dumps(dict(p,settings=text)))
            save_phase('configured')
        else:
            retained=parse((Path(p['root'])/'Pal/Saved/Config/LinuxServer/PalWorldSettings.ini').read_text('utf-8-sig'))
            admin=json.loads(retained['AdminPassword'])
        root_write(UNITS/p['service'],unit_text(p),0o644)
        run(['systemctl','daemon-reload'],'Registering the Palworld systemd service')
        run(['systemctl','enable',p['service']],'Enabling Palworld at Ubuntu startup')
        if data.get('allow_ufw'):
            if not shutil.which('ufw'):raise ValueError('UFW is not installed. Disable the optional firewall step and retry, or configure your firewall manually.')
            status=run(['ufw','status'],'Checking existing UFW firewall')
            if not re.search(r'^Status: active',status,re.M):raise ValueError('UFW is inactive. This wizard will not enable it or change default rules; disable the optional firewall step and retry.')
            run(['ufw','allow',str(p['game_port'])+'/udp'],'Allowing the game UDP port in existing UFW rules')
        save_phase('complete')
        report['started']=False;report['startup_error']=''
        if data.get('start',True):
            try:
                run(['systemctl','start',p['service']],'Starting Palworld',timeout=300)
                emit('Waiting for the REST API to become ready')
                import http.client,base64
                deadline=time.monotonic()+120;next_update=time.monotonic()+15
                while time.monotonic()<deadline:
                    if time.monotonic()>=next_update:
                        emit('Waiting for Palworld startup and REST readiness…');next_update=time.monotonic()+15
                    conn=http.client.HTTPConnection('127.0.0.1',p['api_port'],timeout=3)
                    try:
                        conn.request('GET','/v1/api/info',headers={'Authorization':'Basic '+base64.b64encode(('admin:'+admin).encode()).decode()})
                        if conn.getresponse().status==200:report['started']=True;break
                    except OSError:pass
                    finally:conn.close()
                    time.sleep(3)
                if not report['started']:report['startup_error']='Installed, but REST readiness was not confirmed. Check service status and Console in the saved profile.'
            except Exception as e:report['startup_error']='Installed, but startup failed: '+str(e)
        report['steamcmd']='/usr/games/steamcmd'
        return report

if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.read().split('PALMANAGER_REQUEST_V1\n')[-1])
        if request.get('action') not in ('inspect','install'):raise ValueError('Unknown installer action')
        result=inspect(request) if request['action']=='inspect' else install(request)
        print(json.dumps({'event':'result','result':result}),flush=True)
    except Exception as e:print(json.dumps({'event':'error','message':str(e)}),flush=True);sys.exit(1)
