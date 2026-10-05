import json,threading,time,datetime,re,urllib.request,urllib.error,io
from pathlib import Path
from zoneinfo import ZoneInfo
from .coordinates import map_position

COMMANDS=('start','stop','restart','broadcast','backup','status','kick','player-location')
EVENTS=('start','stop','restart','crash','backup','update','chat','error')

def next_run(schedule,now=None,timezone=None):
    now=time.time() if now is None else now
    if schedule['mode']=='interval': return now+max(60,int(schedule['minutes'])*60)
    hour,minute=map(int,schedule['at'].split(':'))
    if not 0<=hour<24 or not 0<=minute<60: raise ValueError('Invalid daily time')
    zone=ZoneInfo(timezone) if timezone else None
    dt=datetime.datetime.fromtimestamp(now,zone).replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
    if dt.timestamp()<=now: dt+=datetime.timedelta(days=1)
    return dt.timestamp()

def render_map(profile,players):
    from PIL import Image,ImageDraw,ImageFont
    size=(1200,850);im=Image.new('RGB',size,'#101c29');d=ImageDraw.Draw(im)
    try: font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',20)
    except OSError: font=ImageFont.load_default()
    left,top,right,bottom=60,90,1140,790
    if profile.get('map_image') and Path(profile['map_image']).exists():
        with Image.open(profile['map_image']) as bg:
            scale=min((right-left)/bg.width,(bottom-top)/bg.height);width,height=int(bg.width*scale),int(bg.height*scale);left+=(right-left-width)//2;top+=(bottom-top-height)//2;right,bottom=left+width,top+height;im.paste(bg.convert('RGB').resize((width,height)),(left,top))
    else:
        for x in range(left,right+1,60):d.line((x,top,x,bottom),fill='#243646')
        for y in range(top,bottom+1,50):d.line((left,y,right,y),fill='#243646')
    d.text((60,30),profile['name']+' | Live player locations',fill='white',font=font)
    xmin,xmax,ymin,ymax=profile.get('map_bounds',[-1000,1000,-1000,1000])
    for player in players:
        if 'location_x' not in player or 'location_y' not in player:continue
        try:x,y=map_position(player,profile)
        except (ValueError,TypeError):continue
        if profile.get('map_swap'):x,y=y,x
        u=(x-xmin)/(xmax-xmin);v=(y-ymin)/(ymax-ymin)
        if profile.get('map_flip_x'):u=1-u
        if profile.get('map_flip_y'):v=1-v
        if not (0<=u<=1 and 0<=v<=1):continue
        px=left+u*(right-left);py=bottom-v*(bottom-top)
        d.ellipse((px-7,py-7,px+7,py+7),fill=profile.get('accent','#62dfb0'),outline='white',width=2)
        d.text((px+12,py-13),player.get('name','Player'),fill='white',font=font,stroke_width=2,stroke_fill='#101c29')
    d.text((60,810),'Coordinates from Palworld REST API • '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),fill='#9eb2c4',font=font)
    out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()

class Controller:
    def __init__(self,store):
        self.store=store;self.locks={};self.listener=lambda *args:None;self.busy=set();self.guard=threading.Lock();self.last_update={};self.last_status={};self.stopping=False;self.welcome_seen={};self.welcome_polling=set();self.welcome_checked={};self.welcome_errors={}
    def remote(self,p):
        from .remote import Remote
        return Remote(p,self.store.credentials(p['id']))
    def emit(self,p,event,message):
        self.listener(p['id'],event,message)
        if p.get('background_enabled') and not p.get('_background_runner') and event in ('chat','crash'):return
        # Channels are explicitly configured by the owner in the Discord page.
        channels=list(p.get('channels',[]));secrets=self.store.credentials(p['id'])
        for channel in channels:
            if event not in channel.get('events',[]):continue
            url=secrets.get('webhooks',{}).get(channel['id'],'')
            if not re.fullmatch(r'https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[A-Za-z0-9_.-]+',url):continue
            def send(url=url):
                try:
                    payload=json.dumps({'content':('**'+p['name']+' · '+event+'**\n'+message)[:1900],'allowed_mentions':{'parse':[]}}).encode()
                    req=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json','User-Agent':'PalworldManager/0.1'},method='POST')
                    with urllib.request.urlopen(req,timeout=10) as response:response.read()
                except Exception as e:self.listener(p['id'],'error','Discord delivery failed: '+type(e).__name__)
            threading.Thread(target=send,daemon=True).start()
    def announce(self,r,message):
        try:return r.api('announce',{'message':message})
        except Exception:return r.rcon('Broadcast '+message.replace('\n',' ')[:500])
    def save(self,r):
        try:return r.api('save',{})
        except Exception:return r.rcon('Save')
    def warning(self,p,r,action):
        seconds=max(0,min(3600,int(p.get('warning_seconds',60))))
        self.announce(r,'Server '+action+' in '+str(seconds)+' seconds. Please find a safe place.')
        self.listener(p['id'],'progress','Players warned. '+action.capitalize()+' in '+str(seconds)+' seconds…')
        end=time.monotonic()+seconds
        while time.monotonic()<end:time.sleep(min(1,end-time.monotonic()))
        self.save(r);time.sleep(2)
    def operate(self,p,action,**kwargs):
        resource=(p['host'],p.get('port',22),p['root'].rstrip('/'))
        with self.guard:
            lock=self.locks.setdefault(resource,threading.Lock())
        if not lock.acquire(False):raise RuntimeError('Another operation is already running for this world')
        self.busy.add(p['id'])
        r=self.remote(p);workflow=None
        try:
            if p.get('background_enabled') and not p.get('_background_runner') and action in ('start','stop','restart','backup','update','restore','broadcast','kick','ban','unban'):
                result=r.background_action(action,kwargs)
                self.listener(p['id'],'done',action.capitalize()+' completed on Ubuntu')
                return result
            if hasattr(r,'acquire_workflow'):workflow=r.acquire_workflow()
            self.listener(p['id'],'progress',action.replace('_',' ').capitalize()+'…')
            if action=='broadcast':result=self.announce(r,kwargs['message'])
            elif action=='start':
                r.control('start');result=r.wait_state({'active'},300);self.emit(p,'start','World started.')
            elif action in ('stop','restart','backup','update','restore'):
                state=r.call('status');was_running=state.get('ActiveState')=='active'
                if state.get('ActiveState') in ('activating','deactivating','reloading'):raise RuntimeError('Service is transitioning. Wait until it settles.')
                if was_running:self.warning(p,r,action);r.control('stop');r.wait_state({'inactive','failed'})
                result={}
                # If any maintenance step fails, leave the world stopped for inspection.
                if action in ('backup','update','restore'):result=r.call('backup',timeout=1800)
                if action=='update':result=r.update_build()
                if action=='restore':result=r.call('restore',{'name':kwargs['name']},timeout=1800)
                if action=='restart' or (was_running and action in ('backup','update','restore')):r.control('start');r.wait_state({'active'},300)
                self.emit(p,action if action in EVENTS else 'backup',action.capitalize()+' completed.'+((' Archive: '+result.get('name','')) if isinstance(result,dict) and result.get('name') else ''))
            elif action=='recover_expedition':
                import base64
                from .save_repair import repair
                state=r.call('status');was_running=state.get('ActiveState')=='active'
                if state.get('ActiveState') not in ('active','inactive','failed'):raise RuntimeError('Service is transitioning. Wait until it settles.')
                if was_running:
                    self.warning(p,r,'expedition recovery');r.control('stop');r.wait_state({'inactive','failed'})
                self.listener(p['id'],'progress','Creating a full world backup before expedition recovery…')
                backup=r.call('backup',timeout=1800)
                self.emit(p,'backup','Pre-repair backup: '+backup['name'])
                self.listener(p['id'],'progress','Reading the stopped world and revalidating selected Pals…')
                snapshot=r.call('read_world_save',{'path':kwargs['path']},timeout=180)
                fixed,result=repair(base64.b64decode(snapshot['data'],validate=True),kwargs['owner'],kwargs['expected'])
                if result['before']!=snapshot['hash']:raise RuntimeError('Save transfer hash mismatch')
                self.listener(p['id'],'progress','Validated recovery of '+str(result['recovered'])+' Pals. Installing save…')
                installed=r.call('write_world_save',{'path':kwargs['path'],'hash':snapshot['hash'],'data':base64.b64encode(fixed).decode()},timeout=180)
                result.update(installed);result['backup']=backup['name']
                if was_running:r.control('start');r.wait_state({'active'},300);self.emit(p,'start','World started after expedition recovery.')
                self.listener(p['id'],'progress','Recovered '+str(result['recovered'])+' Pals for '+result['player']+'. Backup: '+backup['name'])
            elif action=='write_settings':result=r.call('write_settings',kwargs)
            elif action=='guardian':result=r.guardian(kwargs['enabled'],kwargs.get('managed_maintenance',False))
            elif action in ('kick','ban','unban'):result=r.api(action,{'userid':kwargs['userid'],**({'message':kwargs.get('message','Server administration')} if action!='unban' else {})})
            elif action in ('trash','toggle_mod','install_mod','trash_installation'):result=r.call(action,kwargs,timeout=600)
            else:raise ValueError('Unknown action')
            self.listener(p['id'],'done',action.replace('_',' ').capitalize()+' completed')
            return result
        except Exception as e:
            self.emit(p,'error',action.replace('_',' ').capitalize()+' failed: '+str(e));raise
        finally:
            try:
                if workflow:r.release_workflow(workflow)
            finally:self.busy.discard(p['id']);lock.release()
    def monitor_status(self,p,s):
        previous=self.last_status.get(p['id']);self.last_status[p['id']]=s
        if not previous or p['id'] in self.busy:return
        if int(s.get('NRestarts','0'))>int(previous.get('NRestarts','0')):self.emit(p,'crash','Systemd restarted the world after an unexpected exit.')
        elif previous.get('ActiveState')=='active' and s.get('ActiveState')=='failed':self.emit(p,'crash','World entered the failed state.')
    def poll_welcome(self,p):
        world=p['id']
        try:
            players=self.remote(p).api('players')['players']
            current={str(player['userId']):player for player in players if player.get('userId')}
            previous=self.welcome_seen.get(world)
            self.welcome_seen[world]=set(current)
            if previous is None:return  # Establish a baseline; do not greet existing players on startup.
            for uid in current.keys()-previous:
                if not p.get('welcome_enabled') or self.stopping or (p.get('background_enabled') and not p.get('_background_runner')):return
                message=p.get('welcome_message','Welcome, {player}!').replace('{player}',str(current[uid].get('name') or 'Player')).replace('{world}',p['name'])
                self.operate(p,'broadcast',message=message.replace('\n',' ')[:500])
            self.welcome_errors.pop(world,None)
        except Exception as e:
            # Retain the last successful roster across API outages; avoid repeated error spam.
            error=str(e)
            if self.welcome_errors.get(world)!=error:self.listener(world,'error','Welcome message check failed: '+error)
            self.welcome_errors[world]=error
        finally:self.welcome_polling.discard(world)
    def tick(self):
        if self.stopping:return
        now=time.time()
        for p in list(self.store.profiles):
            if p.get('background_enabled') and not p.get('_background_runner'):continue
            if not p.get('welcome_enabled'):self.welcome_seen.pop(p['id'],None)
            elif p['id'] not in self.welcome_polling and p['id'] not in self.busy and now-self.welcome_checked.get(p['id'],0)>=5:
                self.welcome_checked[p['id']]=now;self.welcome_polling.add(p['id'])
                threading.Thread(target=self.poll_welcome,args=(p,),daemon=True).start()
            if p['id'] in self.busy:continue
            for schedule in p.get('schedules',[]):
                if not schedule.get('enabled'):continue
                if not schedule.get('next'):schedule['next']=next_run(schedule,now,p.get('schedule_timezone'));self.store.save()
                if schedule['next']<=now:
                    schedule['next']=next_run(schedule,now,p.get('schedule_timezone'));self.store.save()
                    def scheduled(p=p,schedule=schedule):
                        try:
                            args={}
                            if schedule['action']=='broadcast':
                                message=schedule.get('message','').strip()
                                if not message or len(message)>500:raise ValueError('Scheduled message must contain 1-500 characters')
                                args['message']=message
                            self.operate(p,schedule['action'],**args)
                        except Exception:pass
                    threading.Thread(target=scheduled,daemon=True).start();break
            if p.get('auto_update') and now-self.last_update.get(p['id'],now)>=max(900,int(p.get('update_interval',3600))):
                self.last_update[p['id']]=now
                def update(p=p):
                    try:
                        r=self.remote(p);state=r.call('status')
                        if state['ActiveState']=='active' and state['build']!=r.latest_build():self.operate(p,'update')
                    except Exception as e:self.emit(p,'error','Auto-update check failed: '+str(e))
                threading.Thread(target=update,daemon=True).start()
            self.last_update.setdefault(p['id'],now)
