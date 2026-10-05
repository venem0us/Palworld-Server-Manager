"""Ubuntu background worker. Code/config are root-owned; file work runs as steam.

Only a permission-restricted Unix socket is exposed, never a network listener.
"""
import argparse,base64,hashlib,http.client,json,os,pwd,re,signal,socket,struct,subprocess,sys,threading,time
from pathlib import Path
from zoneinfo import ZoneInfo
from .controller import Controller
from .settings import parse
from .rcon import execute as execute_rcon

ALLOWED={'start':set(),'stop':set(),'restart':set(),'backup':set(),'update':set(),
         'restore':{'name'},'broadcast':{'message'},'kick':{'userid','message'},
         'ban':{'userid','message'},'unban':{'userid'}}

def identity(p):return hashlib.sha256((p['service']+'\n'+p['root'].rstrip('/')).encode()).hexdigest()[:16]

def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix('.tmp')
    with os.fdopen(os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def validate_profile(p):
    ZoneInfo(p.get('schedule_timezone','UTC'))
    if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',p['service']):raise ValueError('Invalid service')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',p['user']):raise ValueError('Invalid server owner')
    root=Path(p['root']).resolve()
    if not (root/'PalServer.sh').is_file() or root==Path('/'):raise ValueError('Invalid Palworld root')
    account=pwd.getpwnam(p['user'])
    if account.pw_uid==0:raise ValueError('Server owner must not be root')
    info=subprocess.check_output(['systemctl','show',p['service'],'-p','User','-p','ExecStart','-p','LoadState'],text=True)
    if 'LoadState=loaded' not in info or ('User='+p['user']+'\n') not in info:raise ValueError('Service does not belong to the selected server owner')
    if p['root'].rstrip('/')+'/PalServer.sh' not in info and str(root/'PalServer.sh') not in info:raise ValueError('Service executable does not match this installation')
    return account

class WorkerStore:
    def __init__(self,config_path):
        self.path=Path(config_path);self.state_path=self.path.with_name('state.json');self.state={};self.profiles=[];self.secrets={};self.version=None;self.reload()
        if self.state_path.exists():
            try:self.state=json.loads(self.state_path.read_text())
            except ValueError:pass
        self.restore_next()
    def reload(self):
        data=json.loads(self.path.read_text());p=data['profile'];p['_background_runner']=True
        self.profiles=[p];self.secrets=data.get('secrets',{});self.version=self.path.stat().st_mtime_ns
        self.restore_next()
    def restore_next(self):
        for s in self.profiles[0].get('schedules',[]):
            saved=self.state.get('schedules',{}).get(s['id'],{})
            signature=self.signature(s)
            if saved.get('signature')==signature:s['next']=saved['next']
            else:s['next']=0
    def signature(self,s):
        return json.dumps({**{k:s.get(k) for k in ('action','mode','minutes','at','enabled','message')},'timezone':self.profiles[0].get('schedule_timezone','UTC')},sort_keys=True)
    def save(self):
        schedules={}
        for s in self.profiles[0].get('schedules',[]):
            schedules[s['id']]={'next':s.get('next',0),'signature':self.signature(s)}
        self.state['schedules']=schedules;atomic_json(self.state_path,self.state)
    def credentials(self,world):return self.secrets.copy()

class LocalRemote:
    def __init__(self,p):self.p=p
    def user_command(self,args,timeout=120,data=None):
        result=subprocess.run(['runuser','-u',self.p['user'],'--']+args,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
        if result.returncode:raise RuntimeError((result.stderr or result.stdout or 'Command failed')[-3000:])
        return result.stdout
    def call(self,action,args=None,timeout=120):
        folder=Path(__file__).parent;source=(folder/'settings.py').read_text()+'\n'+(folder/'remote_agent.py').read_text()
        code="import base64;exec(compile(base64.b64decode('"+base64.b64encode(source.encode()).decode()+"'),'<palmanager>','exec'))"
        data=json.loads(self.user_command(['python3','-c',code],timeout,json.dumps({'root':self.p['root'],'service':self.p['service'],'action':action,'args':args or {}})))
        if not data['ok']:raise RuntimeError(data['error'])
        return data['result']
    def control(self,action):
        if action not in ('start','stop','restart'):raise ValueError('Unsupported action')
        subprocess.run(['systemctl',action,self.p['service']],check=True,timeout=900,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def wait_state(self,expected,timeout=180):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            state=self.call('status')
            if state['ActiveState'] in expected:return state
            time.sleep(2)
        raise TimeoutError('World did not reach '+str(expected))
    def acquire_workflow(self):
        script="import pathlib,fcntl,sys; p=pathlib.Path("+repr(self.p['root'])+")/'.palmanager'; p.mkdir(exist_ok=True,mode=448); f=(p/'workflow.lock').open('a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print('READY',flush=True); sys.stdin.read()"
        process=subprocess.Popen(['runuser','-u',self.p['user'],'--','python3','-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if process.stdout.readline().strip()!='READY':process.wait(timeout=10);raise RuntimeError('Another maintenance operation is running')
        return process
    def release_workflow(self,process):
        try:process.stdin.close();process.wait(timeout=10)
        except Exception:process.kill();process.wait()
    def api(self,endpoint,payload=None):
        if endpoint not in ('info','players','metrics','announce','kick','ban','unban','save','shutdown','stop'):raise ValueError('Invalid API endpoint')
        values=parse(self.call('read_settings')['text'])
        if values.get('RESTAPIEnabled','False').lower()!='true':raise RuntimeError('REST API is disabled')
        password=values.get('AdminPassword','""')[1:-1]
        conn=http.client.HTTPConnection('127.0.0.1',int(values.get('RESTAPIPort','8212')),timeout=15)
        try:
            conn.request('POST' if payload is not None else 'GET','/v1/api/'+endpoint,json.dumps(payload) if payload is not None else None,{'Content-Type':'application/json','Authorization':'Basic '+base64.b64encode(('admin:'+password).encode()).decode()})
            response=conn.getresponse();data=response.read(4*1024*1024)
            if response.status>=400:raise RuntimeError('REST API returned '+str(response.status))
            return json.loads(data) if data.strip() else {'ok':True}
        finally:conn.close()
    def rcon(self,command):
        if command!='Save' and not command.startswith('Broadcast '):raise ValueError('Only save/broadcast use RCON')
        values=parse(self.call('read_settings')['text'])
        if values.get('RCONEnabled','False').lower()!='true':raise RuntimeError('No API is available to notify and save the world')
        with socket.create_connection(('127.0.0.1',int(values.get('RCONPort','25575'))),timeout=15) as ch:
            return execute_rcon(ch,values.get('AdminPassword','""')[1:-1],command)
    def update_build(self):
        if self.call('status')['ActiveState'] not in ('inactive','failed'):raise RuntimeError('World must be stopped')
        output=self.user_command([self.p.get('steamcmd','/usr/games/steamcmd'),'+force_install_dir',self.p['root'],'+login','anonymous','+app_update','2394010','validate','+quit'],3600)
        if "Success! App '2394010' fully installed" not in output:raise RuntimeError('SteamCMD did not confirm success')
        return 'SteamCMD update verified'
    def latest_build(self):
        output=self.user_command([self.p.get('steamcmd','/usr/games/steamcmd'),'+login','anonymous','+app_info_update','1','+app_info_print','2394010','+quit'],180)
        match=re.search(r'"public"\s*\{\s*"buildid"\s*"(\d+)"',output)
        if not match:raise RuntimeError('No public Steam build ID found')
        return match.group(1)

class Worker:
    def __init__(self,config):
        self.store=WorkerStore(config);self.p=self.store.profiles[0];self.account=validate_profile(self.p)
        self.controller=Controller(self.store);self.controller.remote=lambda p:LocalRemote(p);self.controller.listener=self.event
        self.running=True;self.bot=None;self.bot_signature=None;self.server=None;self.cursor='';self.offset=0;self.chat_ready=False;self.chat_remainder=''
        self.state_path=self.store.path.with_name('health.json');self.last_error='';self.clients=threading.BoundedSemaphore(4)
        if self.p.get('schedule_timezone'):os.environ['TZ']=self.p['schedule_timezone'];time.tzset()
    def event(self,world,event,message):
        print(json.dumps({'event':event,'message':message,'time':time.time()}),flush=True)
        if event=='error':self.last_error=message
    def configure_bot(self):
        token=self.store.secrets.get('bot_token','');signature=(token,self.p.get('guild_id'),self.p.get('bot_enabled',False))
        if signature==self.bot_signature:return
        if self.bot:self.bot.stop();self.bot=None
        self.bot_signature=signature
        if not token or not self.p.get('guild_id') or not self.p.get('bot_enabled',False):return
        try:
            from .discord_bot import WorldBot
            self.bot=WorldBot(self.p,self.controller,token);self.bot.start()
        except ImportError:self.event(self.p['id'],'error','Discord runtime is not installed. Enable the Ubuntu bot runtime from the Windows app.')
    def client(self,connection):
        response={'ok':False,'error':'Connection closed'}
        try:
            connection.settimeout(30);buffer=b''
            while b'\n' not in buffer:
                part=connection.recv(4096)
                if not part:return
                buffer+=part
                if len(buffer)>16384:raise ValueError('Request too large')
            request=json.loads(buffer.split(b'\n',1)[0]);action=request['action'];args=request.get('args',{})
            if action=='health':result={'running':True,'busy':bool(self.controller.busy),'last_error':self.last_error,'schedules':self.p.get('schedules',[]),'auto_update':self.p.get('auto_update',False),'schedule_timezone':self.p.get('schedule_timezone','UTC'),'bot_connected':bool(self.bot and self.bot.client and self.bot.client.is_ready())}
            else:
                if self.controller.stopping:raise RuntimeError('Background manager is stopping; retry after it restarts')
                if action not in ALLOWED or not isinstance(args,dict) or set(args)-ALLOWED[action]:raise ValueError('Unsupported operation or argument')
                if any(not isinstance(v,str) or len(v)>2000 for v in args.values()):raise ValueError('Invalid argument')
                result=self.controller.operate(self.p,action,**args)
            response={'ok':True,'result':result}
        except Exception as e:response={'ok':False,'error':str(e)}
        finally:
            try:connection.sendall(json.dumps(response).encode()+b'\n')
            except Exception:pass
            connection.close();self.clients.release()
    def serve(self):
        path='/run/palmanager-'+identity(self.p)+'.sock'
        if os.path.exists(path):os.unlink(path)
        self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.server.bind(path);os.chown(path,self.account.pw_uid,self.account.pw_gid);os.chmod(path,0o600);self.server.listen(4);self.server.settimeout(1)
        while self.running:
            try:connection,_=self.server.accept()
            except socket.timeout:continue
            except OSError:break
            if not self.clients.acquire(False):connection.close();continue
            threading.Thread(target=self.client,args=(connection,),daemon=True).start()
        self.server.close()
        if os.path.exists(path):os.unlink(path)
    def poll_chat(self,r):
        p=self.p
        if p.get('chat_log'):
            data=r.call('chat_log',{'path':p['chat_log'],'offset':self.offset})
            if data['offset']<self.offset:self.chat_remainder=''
            self.offset=data['offset'];parts=(self.chat_remainder+data['text']).splitlines(keepends=True);self.chat_remainder='';lines=[]
            for part in parts:
                if part.endswith(('\n','\r')):lines.append(part)
                else:self.chat_remainder=part[-65536:]
        else:
            data=r.call('logs',{'cursor':self.cursor});lines=[str(v['message']) for v in data]
            if data:self.cursor=data[-1]['cursor']
        if not self.chat_ready:self.chat_ready=True;return
        regex=re.compile(p.get('chat_regex',r'\[CHAT\]\s*(?P<name>[^:]+):\s*(?P<message>.*)'))
        for line in lines:
            match=regex.search(line)
            if match:self.controller.emit(p,'chat',match.groupdict().get('name','Player')+': '+match.groupdict().get('message',match.group(0)))
    def stop(self,*args):
        # Never interrupt a backup/update because the worker service is stopped.
        self.controller.stopping=True
        if not self.controller.busy:self.running=False
    def run(self):
        signal.signal(signal.SIGTERM,self.stop);signal.signal(signal.SIGINT,self.stop)
        threading.Thread(target=self.serve,daemon=True).start();self.configure_bot();self.event(self.p['id'],'ready','Background manager running')
        while self.running:
            try:
                if self.store.path.stat().st_mtime_ns!=self.store.version and not self.controller.busy:
                    self.store.reload();self.p=self.store.profiles[0];validate_profile(self.p);self.configure_bot()
                    if self.p.get('schedule_timezone'):os.environ['TZ']=self.p['schedule_timezone'];time.tzset()
                self.controller.tick();r=LocalRemote(self.p);self.controller.monitor_status(self.p,r.call('status'))
                if any('chat' in c.get('events',[]) for c in self.p.get('channels',[])):self.poll_chat(r)
                atomic_json(self.state_path,{'time':time.time(),'running':True,'busy':bool(self.controller.busy),'last_error':self.last_error})
            except Exception as e:self.event(self.p['id'],'error',str(e))
            if self.controller.stopping and not self.controller.busy:self.running=False
            time.sleep(3)
        if self.bot:self.bot.stop()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('config');args=parser.parse_args();Worker(args.config).run()
