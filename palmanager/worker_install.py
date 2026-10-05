"""Root-only Ubuntu deployment entry point, called through authenticated sudo."""
import base64,hashlib,json,os,pwd,re,subprocess,sys
from pathlib import Path
from zoneinfo import ZoneInfo

FILES={'__init__.py','settings.py','remote_agent.py','controller.py','background.py','discord_bot.py','rcon.py','coordinates.py'}

def write(path,data,mode):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.new')
    with os.fdopen(os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,mode),'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(temp,mode);os.replace(temp,path)

def install(data):
    if os.geteuid()!=0:raise ValueError('Installation requires sudo')
    p=data['profile']
    ZoneInfo(p.get('schedule_timezone','UTC'))
    if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',p['service']) or not re.fullmatch(r'[a-z_][a-z0-9_-]*',p['user']):raise ValueError('Invalid service/owner')
    account=pwd.getpwnam(p['user'])
    if account.pw_uid==0:raise ValueError('The game must run as a non-root user')
    root=Path(p['root']).resolve()
    if not (root/'PalServer.sh').is_file() or root==Path('/'):raise ValueError('Invalid game directory')
    info=subprocess.check_output(['systemctl','show',p['service'],'-p','User','-p','ExecStart','-p','LoadState'],text=True)
    if 'LoadState=loaded' not in info or ('User='+p['user']+'\n') not in info or (p['root'].rstrip('/')+'/PalServer.sh' not in info and str(root/'PalServer.sh') not in info):raise ValueError('The selected unit does not match this Palworld installation')
    ident=hashlib.sha256((p['service']+'\n'+p['root'].rstrip('/')).encode()).hexdigest()[:16]
    base=Path('/opt/palworld-manager')/ident;state=Path('/var/lib/palworld-manager')/ident;unit='palmanager-'+ident+'.service';unit_path=Path('/etc/systemd/system')/unit
    mode=data.get('mode','install')
    if mode=='disable':
        subprocess.run(['systemctl','disable','--now',unit],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4200)
        return {'id':ident,'unit':unit,'disabled':True}
    if mode=='runtime':
        if not base.exists():raise ValueError('Install the background worker first')
        result=subprocess.run(['python3','-m','venv',str(base/'venv')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        if result.returncode:
            environment=dict(os.environ,DEBIAN_FRONTEND='noninteractive')
            subprocess.run(['apt-get','update'],check=True,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=600)
            subprocess.run(['apt-get','install','-y','python3-venv'],check=True,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=600)
            subprocess.run(['python3','-m','venv',str(base/'venv')],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        subprocess.run([str(base/'venv/bin/python'),'-m','pip','install','discord.py==2.7.1','Pillow==12.3.0'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=600)
        # Reuse the normal deployment path to select the new virtual environment.
    if set(data['files'])!=FILES:raise ValueError('Unexpected worker package files')
    if unit_path.exists():subprocess.run(['systemctl','stop',unit],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4200)
    base.mkdir(parents=True,exist_ok=True,mode=0o755);state.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(state,0o700)
    for name,source in data['files'].items():write(base/'palmanager'/name,source.encode(),0o644)
    p['_background_runner']=True;p['background_enabled']=True
    if data.get('assets',{}).get('map'):
        image=base64.b64decode(data['assets']['map'],validate=True)
        if len(image)>50*1024*1024:raise ValueError('Map asset too large')
        write(state/'map-image',image,0o600);p['map_image']=str(state/'map-image')
    secrets=data.get('secrets',{})
    # No SSH/sudo credentials ever need to be stored on Ubuntu.
    secrets={k:v for k,v in secrets.items() if k in ('webhooks','bot_token')}
    write(state/'world.json',json.dumps({'profile':p,'secrets':secrets},indent=2).encode(),0o600)
    python=str(base/'venv/bin/python') if (base/'venv/bin/python').is_file() else '/usr/bin/python3'
    content='''[Unit]
Description=Palworld Manager background worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={base}
ExecStart={python} -m palmanager.background {config}
Restart=on-failure
RestartSec=10
TimeoutStopSec=4200
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
'''.format(base=base,python=python,config=state/'world.json')
    write(unit_path,content.encode(),0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now',unit],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return {'id':ident,'unit':unit,'config':str(state/'world.json'),'discord_runtime':(base/'venv/bin/python').exists()}

if __name__=='__main__':
    try:print(json.dumps({'ok':True,'result':install(json.loads(sys.stdin.read()))}))
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)}))
