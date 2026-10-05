import base64, ctypes, json, os, uuid, zipfile, shutil
from pathlib import Path

DEFAULT_PROFILE = dict(id='default-world',name='My Palworld server',host='',port=22,user='steam',admin_user='ubuntu',
    fingerprint='',
    root='/home/steam/.steam/steam/steamapps/common/PalServer',service='palworld.service',
    steamcmd='/usr/games/steamcmd',api_port=8212,accent='#62dfb0',icon='',banner='',map_image='',
    map_bounds=[-1000,1000,-1000,1000],map_swap=False,map_flip_x=False,map_flip_y=False,
    welcome_enabled=False,welcome_message="Welcome, {player}! Enjoy your time on {world}.",warning_seconds=60,schedules=[],auto_update=False,update_interval=3600,channels=[],permissions={},guild_id='',chat_log='',chat_regex=r'\[CHAT\]\s*(?P<name>[^:]+):\s*(?P<message>.*)')
DEFAULT_PROFILE.update(coordinate_space="world",bot_enabled=False,background_enabled=False,schedule_timezone='America/New_York')

class Blob(ctypes.Structure):
    _fields_=[('cbData',ctypes.c_uint32),('pbData',ctypes.POINTER(ctypes.c_ubyte))]

def protect(data, decrypt=False):
    if os.name != 'nt': raise RuntimeError('Credential storage requires Windows DPAPI')
    buf = ctypes.create_string_buffer(data); src=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte))); dest=Blob()
    api=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dest)): raise ctypes.WinError()
    try: return ctypes.string_at(dest.pbData,dest.cbData)
    finally: ctypes.windll.kernel32.LocalFree(dest.pbData)

def atomic(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_bytes(data);os.replace(temp,path)

def recycle(path):
    path=Path(path).resolve()
    if os.name != 'nt': raise RuntimeError('Local recycle currently requires Windows')
    class Op(ctypes.Structure):
        _fields_=[('hwnd',ctypes.c_void_p),('wFunc',ctypes.c_uint),('pFrom',ctypes.c_wchar_p),('pTo',ctypes.c_wchar_p),('fFlags',ctypes.c_ushort),('aborted',ctypes.c_int),('mappings',ctypes.c_void_p),('title',ctypes.c_wchar_p)]
    op=Op(None,3,str(path)+'\0',None,0x40|0x10|0x400,0,None,None)
    code=ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.aborted: raise RuntimeError('Recycle Bin operation did not complete')

class Store:
    def __init__(self, directory=None):
        self.directory=Path(directory or os.environ.get('PALMANAGER_DATA') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'PalworldManager')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'profiles.json'
        self.profiles=json.loads(self.path.read_text('utf-8')) if self.path.exists() else [dict(DEFAULT_PROFILE)]
        self.secrets={};self.persisted={}
        secret=self.directory/'credentials.dpapi'
        if secret.exists(): self.secrets=json.loads(protect(secret.read_bytes(),True))
        self.persisted=json.loads(json.dumps(self.secrets))
    def save(self): atomic(self.path,json.dumps(self.profiles,indent=2).encode())
    def credentials(self, world): return self.secrets.get(world,{}).copy()
    def set_credentials(self,world,value,remember=True):
        self.secrets[world]=value
        if remember:self.persisted[world]=value
        else:self.persisted.pop(world,None)
        if remember or (self.directory/'credentials.dpapi').exists():atomic(self.directory/'credentials.dpapi',protect(json.dumps(self.persisted).encode()))
    def export_profile(self,p,path,settings=''):
        safe=json.loads(json.dumps(p));safe['channels']=[];safe['permissions']={};safe['guild_id']='';safe['schedules']=[];safe['auto_update']=False;safe['welcome_enabled']=False;safe['background_enabled']=False;safe['bot_enabled']=False
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for key in ('icon','banner','map_image'):
                if safe.get(key) and Path(safe[key]).is_file():
                    file=Path(safe[key]); name='assets/'+key+file.suffix.lower();z.write(file,name);safe[key]=name
                else: safe[key]=''
            z.writestr('profile.json',json.dumps({'format':1,'profile':safe},indent=2))
            if settings:
                from .settings import parse,patch
                fields=parse(settings);settings=patch(settings,{k:'""' for k in ('AdminPassword','ServerPassword') if k in fields})
                z.writestr('PalWorldSettings.ini',settings)
            z.writestr('README.txt','Credentials, Discord routing, schedules, and game passwords are excluded. Settings are included for review/import; saves and server binaries are not included. Use Backups to transfer saves.')
    def import_profile(self,path):
        with zipfile.ZipFile(path) as z:
            if len(z.infolist())>20 or sum(i.file_size for i in z.infolist())>30*1024*1024: raise ValueError('Profile archive is too large')
            obj=json.loads(z.read('profile.json'))
            if obj.get('format') != 1: raise ValueError('Unsupported profile format')
            p=dict(DEFAULT_PROFILE);p.update({k:v for k,v in obj['profile'].items() if k in p})
            p['id']=uuid.uuid4().hex;p['name']+=' (imported)';p['schedules']=[];p['auto_update']=False;p['welcome_enabled']=False;p['channels']=[];p['permissions']={};p['background_enabled']=False;p['bot_enabled']=False
            for key in ('icon','banner','map_image'):
                name=p.get(key,'')
                if name:
                    if not name.startswith('assets/') or Path(name).suffix.lower() not in ('.png','.jpg','.jpeg','.webp'): raise ValueError('Invalid profile asset')
                    dest=self.directory/'assets'/p['id']/(key+Path(name).suffix.lower());atomic(dest,z.read(name));p[key]=str(dest)
            self.profiles.append(p);self.save();return p
