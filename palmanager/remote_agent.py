"""Python 3 standard-library helper, executed over SSH; no listening agent port."""
import os, sys, json, re, hashlib, tempfile, shutil, subprocess, tarfile, uuid, time, stat, fcntl
from pathlib import Path, PurePosixPath
from datetime import datetime
from urllib.parse import quote

def run(args, timeout=30):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout or 'Command failed')[-3000:])
    return p.stdout

def digest(data): return hashlib.sha256(data).hexdigest()

def checked(root, relative, exists=False):
    if not isinstance(relative,str) or not relative or '\\' in relative: raise ValueError('Invalid relative path')
    p=PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts: raise ValueError('Path escapes installation')
    path=root.joinpath(*p.parts)
    cursor=root
    for part in p.parts:
        cursor=cursor/part
        if cursor.is_symlink(): raise ValueError('Symbolic links are not allowed for this operation')
    result=path.resolve()
    if root not in result.parents: raise ValueError('Path escapes installation')
    if exists and not result.exists(): raise FileNotFoundError(relative)
    return result

def write_atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    with temp.open('wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(str(temp),mode);os.replace(str(temp),str(path))

def trash(path):
    path=Path(path)
    if path.is_symlink(): raise ValueError('Refusing symbolic link')
    path=path.resolve()
    home=Path.home().resolve()
    if path in (Path('/'),home) or home not in path.parents: raise ValueError('Trash is restricted to descendants of the SSH user home')
    base=home/'.local/share/Trash';files=base/'files';info=base/'info'
    files.mkdir(parents=True,exist_ok=True,mode=0o700);info.mkdir(parents=True,exist_ok=True,mode=0o700)
    if files.stat().st_dev != path.stat().st_dev: raise ValueError('Cross-filesystem Trash is unsupported; nothing was removed')
    name=path.name+'.'+uuid.uuid4().hex
    meta=info/(name+'.trashinfo')
    write_atomic(meta,('[Trash Info]\nPath='+quote(str(path),safe='/')+'\nDeletionDate='+datetime.now().strftime('%Y-%m-%dT%H:%M:%S')+'\n').encode())
    try: os.rename(str(path),str(files/name))
    except Exception:
        meta.unlink();raise
    return name

def status(service):
    raw=run(['systemctl','show',service,'--no-pager','-p','LoadState','-p','ActiveState','-p','SubState','-p','MainPID','-p','MemoryCurrent','-p','NRestarts','-p','Restart','-p','ExecStartPre','-p','ExecStart','-p','RuntimeMaxUSec','-p','ActiveEnterTimestamp','-p','User'])
    return dict(line.split('=',1) for line in raw.splitlines() if '=' in line)

def stopped(service):
    if status(service).get('ActiveState') not in ('inactive','failed'): raise RuntimeError('Stop the world before modifying saves, mods, or files')

def main(req):
    root=Path(req['root']).resolve()
    if not root.is_absolute() or root==Path('/') or not (root/'PalServer.sh').is_file(): raise ValueError('Not a verified native Linux PalServer installation')
    service=req['service']
    if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service',service): raise ValueError('Invalid systemd unit name')
    action=req['action'];args=req.get('args',{})
    cfg=checked(root,'Pal/Saved/Config/LinuxServer/PalWorldSettings.ini')
    managed=checked(root,'.palmanager')
    if action=='status':
        s=status(service);d=shutil.disk_usage(str(root));s['disk']={'free':d.free,'total':d.total}
        s['root']=str(root);s['settings_exists']=cfg.exists()
        candidates=[root/'steamapps/appmanifest_2394010.acf',root/'appmanifest_2394010.acf',root.parent.parent/'appmanifest_2394010.acf']
        manifest=next((p for p in candidates if p.is_file()),candidates[0])
        m=re.search(r'"buildid"\s+"(\d+)"',manifest.read_text()) if manifest.exists() else None
        s['build']=m.group(1) if m else 'unknown';return s
    if action=='read_settings':
        data=cfg.read_bytes();default=(root/'DefaultPalWorldSettings.ini').read_text()
        return {'text':data.decode('utf-8-sig'),'hash':digest(data),'defaults':default}
    if action=='logs':
        cmd=['journalctl','-u',service,'--no-pager','-q','-o','json','-n','300']
        if args.get('cursor'): cmd+=['--after-cursor',args['cursor']]
        raw=run(cmd);entries=[]
        for line in raw.splitlines():
            try:
                item=json.loads(line);entries.append({'cursor':item.get('__CURSOR',''),'time':item.get('__REALTIME_TIMESTAMP',''),'message':item.get('MESSAGE','')})
            except ValueError: pass
        return entries
    if action=='chat_log':
        path=checked(root,args['path'],True)
        size=path.stat().st_size;offset=int(args.get('offset',0))
        if offset>size: offset=0
        with path.open('rb') as f:
            f.seek(max(offset,size-262144));data=f.read(262144)
            return {'offset':f.tell(),'text':data.decode('utf-8','replace')}
    if action=='list_backups':
        path=checked(root,'.palmanager/backups')
        return [{'name':p.name,'size':p.stat().st_size,'time':p.stat().st_mtime} for p in sorted(path.glob('*.tar.gz'),reverse=True) if not p.is_symlink()]
    if action=='list_saves':
        path=checked(root,'Pal/Saved/SaveGames')
        return [str(p.relative_to(root)) for p in path.glob('*/*') if p.is_dir() and not p.is_symlink()]
    if action in ('list_world_saves','read_world_save'):
        if action=='list_world_saves':
            path=checked(root,'Pal/Saved/SaveGames')
            return [str(p.relative_to(root)) for p in path.glob('*/*/Level.sav') if not p.is_symlink() and re.fullmatch(r'Pal/Saved/SaveGames/[0-9A-Fa-f]+/[0-9A-Fa-f]+/Level\.sav',str(p.relative_to(root)))]
        rel=args['path']
        if not re.fullmatch(r'Pal/Saved/SaveGames/[0-9A-Fa-f]+/[0-9A-Fa-f]+/Level\.sav',rel):raise ValueError('Invalid world save path')
        target=checked(root,rel,True)
        if target.stat().st_size>64*1024*1024:raise ValueError('World save exceeds the 64 MB transfer limit')
        before=target.stat();data=target.read_bytes();after=target.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise RuntimeError('Save changed while scanning. Try again.')
        import base64
        return {'data':base64.b64encode(data).decode(),'hash':digest(data)}
    if action=='list_mods':
        result=[]
        for kind,rel in [('pak','Pal/Content/Paks/~mods'),('lua','Pal/Binaries/Linux/Mods'),('schema','Pal/Binaries/Linux/Mods/PalSchema/mods')]:
            base=checked(root,rel)
            for enabled,directory in [(True,base),(False,checked(root,'.palmanager/disabled/'+kind))]:
                if not directory.exists(): continue
                for p in directory.iterdir():
                    if p.name in ('mods.txt','PalSchema') or p.is_symlink() or p.name.startswith('.'): continue
                    if kind=='pak' and p.suffix.lower()!='.pak': continue
                    if kind!='pak' and not p.is_dir(): continue
                    result.append({'kind':kind,'name':p.name,'enabled':enabled,'path':str(p.relative_to(root))})
        return result
    if action=='capabilities':
        return {'native_linux':True,'workshop':False,'ue4ss':(root/'Pal/Binaries/Linux/libUE4SS.so').exists(),'palschema':(root/'Pal/Binaries/Linux/Mods/PalSchema/libs/main.so').exists()}
    # Read-only operations above must not create files.
    managed.mkdir(mode=0o700,exist_ok=True);os.chmod(str(managed),0o700)
    lock=managed/'operation.lock'
    with lock.open('a') as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another manager operation is running on this installation')
        if action=='write_world_save':
            stopped(service)
            rel=args['path']
            if not re.fullmatch(r'Pal/Saved/SaveGames/[0-9A-Fa-f]+/[0-9A-Fa-f]+/Level\.sav',rel):raise ValueError('Invalid world save path')
            target=checked(root,rel,True);original=target.read_bytes()
            if digest(original)!=args['hash']:raise RuntimeError('Save changed after validation; repair aborted')
            import base64,struct
            data=base64.b64decode(args['data'],validate=True)
            if len(data)<12 or len(data)>64*1024*1024 or data[8:12]!=b'PlM1' or struct.unpack_from('<I',data,4)[0]!=len(data)-12:raise ValueError('Invalid replacement save')
            recovery=checked(root,'.palmanager/save-recovery/'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex+'/Level.sav')
            write_atomic(recovery,original)
            if digest(recovery.read_bytes())!=args['hash']:raise RuntimeError('Recovery copy verification failed')
            stopped(service)
            if digest(target.read_bytes())!=args['hash']:raise RuntimeError('Save changed; repair aborted')
            write_atomic(target,data)
            if digest(target.read_bytes())!=digest(data):
                write_atomic(target,original);raise RuntimeError('Write verification failed; original restored')
            return {'hash':digest(data),'recovery':str(recovery.relative_to(root))}
        if action=='write_settings':
            # settings.py is prepended by the client; no remote package installation.
            data=cfg.read_bytes()
            if digest(data)!=args['hash']: raise RuntimeError('Settings changed on the server. Reload and reapply your edits.')
            new=patch(data.decode('utf-8-sig'),args['changes'],parse((root/'DefaultPalWorldSettings.ini').read_text()))
            backup=checked(root,'.palmanager/config-history/'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.ini')
            encoded=(b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b'')+new.encode('utf-8')
            write_atomic(backup,data);write_atomic(cfg,encoded)
            return {'changed':len(args['changes']),'hash':digest(encoded),'backup':str(backup)}
        if action=='backup':
            stopped(service)
            saved=checked(root,'Pal/Saved',True)
            required=sum(p.stat().st_size for p in saved.rglob('*') if p.is_file() and not p.is_symlink())
            if shutil.disk_usage(str(root)).free < required+128*1024*1024: raise RuntimeError('Insufficient disk space for a safe backup')
            name=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.tar.gz'
            dest=checked(root,'.palmanager/backups/'+name);dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_suffix('.partial');temp.touch(mode=0o600,exist_ok=False)
            def safe_filter(t):
                if not (t.isfile() or t.isdir()): raise ValueError('Save contains a link or special file; backup aborted')
                return t
            with tarfile.open(str(temp),'w:gz') as t: t.add(str(saved),arcname='Saved',filter=safe_filter)
            with tarfile.open(str(temp),'r:gz') as t:
                for item in t:
                    if item.isfile():
                        stream=t.extractfile(item)
                        while stream.read(1024*1024): pass
            os.replace(str(temp),str(dest));return {'name':name,'size':dest.stat().st_size}
        if action=='restore':
            stopped(service)
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.tar\.gz',args['name']): raise ValueError('Invalid backup name')
            source=checked(root,'.palmanager/backups/'+args['name'],True)
            stage=checked(root,'.palmanager/restore-'+uuid.uuid4().hex);stage.mkdir(mode=0o700)
            with tarfile.open(str(source),'r:gz') as t:
                members=t.getmembers()
                if len(members)>100000: raise ValueError('Too many backup entries')
                if sum(m.size for m in members)>shutil.disk_usage(str(root)).free-128*1024*1024: raise ValueError('Not enough space for restore')
                names=set()
                for m in members:
                    p=PurePosixPath(m.name)
                    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='Saved' or not (m.isdir() or m.isfile()) or m.name in names: raise ValueError('Unsafe backup entry')
                    names.add(m.name)
                for m in members:
                    p=stage.joinpath(*PurePosixPath(m.name).parts)
                    if m.isdir(): p.mkdir(parents=True,exist_ok=True,mode=0o700)
                    else:
                        p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                        with t.extractfile(m) as src,os.fdopen(os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as dst: shutil.copyfileobj(src,dst)
            if not (stage/'Saved/SaveGames').is_dir(): raise ValueError('Backup has no SaveGames directory')
            saved=checked(root,'Pal/Saved',True);recovery=trash(saved)
            try: os.rename(str(stage/'Saved'),str(saved))
            except Exception:
                os.rename(str(Path.home()/'.local/share/Trash/files'/recovery),str(saved));raise
            return {'recovery':recovery,'restored':args['name']}
        if action=='trash':
            stopped(service);rel=args['path']
            allowed=('Pal/Saved/SaveGames/','.palmanager/backups/','Pal/Content/Paks/~mods/','Pal/Binaries/Linux/Mods/','.palmanager/disabled/')
            if not any(rel.startswith(p) for p in allowed): raise ValueError('Path is outside removable areas')
            target=checked(root,rel,True)
            if target.name in ('mods.txt','PalSchema'): raise ValueError('Use framework management for this path')
            return {'trash':trash(target)}
        if action=='trash_installation':
            stopped(service)
            if args.get('confirm') != str(root): raise ValueError('Installation path confirmation does not match')
            return {'trash':trash(root)}
        if action=='toggle_mod':
            stopped(service);kind=args['kind'];name=args['name'];enabled=bool(args['enabled'])
            if kind not in ('pak','lua','schema') or not re.fullmatch(r'[A-Za-z0-9_. -]+',name) or name in ('.','..','PalSchema','mods.txt'): raise ValueError('Invalid mod')
            rel={'pak':'Pal/Content/Paks/~mods','lua':'Pal/Binaries/Linux/Mods','schema':'Pal/Binaries/Linux/Mods/PalSchema/mods'}[kind]
            active=checked(root,rel+'/'+name);inactive=checked(root,'.palmanager/disabled/'+kind+'/'+name)
            src,dst=(inactive,active) if enabled else (active,inactive)
            if dst.exists(): raise ValueError('Destination already exists')
            dst.parent.mkdir(parents=True,exist_ok=True);os.rename(str(src),str(dst))
            if enabled and kind=='lua': write_atomic(dst/'enabled.txt',b'')
            return {'enabled':enabled}
        if action=='install_mod':
            stopped(service);kind=args['kind'];name=args['name']
            if kind not in ('pak','lua','schema') or not re.fullmatch(r'[A-Za-z0-9_ -]+',name): raise ValueError('Invalid mod kind or name')
            if kind=='schema' and not (root/'Pal/Binaries/Linux/Mods/PalSchema/libs/main.so').is_file(): raise ValueError('A compatible native Linux PalSchema framework is required')
            if kind=='lua' and not (root/'Pal/Binaries/Linux/libUE4SS.so').is_file(): raise ValueError('Install a compatible native Linux UE4SS framework first')
            src=checked(root,'.palmanager/uploads/'+args['upload'],True)
            base={'pak':'Pal/Content/Paks/~mods','lua':'Pal/Binaries/Linux/Mods','schema':'Pal/Binaries/Linux/Mods/PalSchema/mods'}[kind]
            dest=checked(root,base+'/'+name+('.pak' if kind=='pak' else ''))
            if dest.exists(): raise ValueError('A mod with this name already exists; remove or rename it first')
            dest.parent.mkdir(parents=True,exist_ok=True)
            if kind=='pak': os.rename(str(src),str(dest))
            else:
                import zipfile
                stage=checked(root,'.palmanager/stage-'+uuid.uuid4().hex);stage.mkdir()
                with zipfile.ZipFile(src) as z:
                    entries=z.infolist()
                    if len(entries)>10000 or sum(e.file_size for e in entries)>1024**3: raise ValueError('Archive too large')
                    seen=set()
                    for e in entries:
                        p=PurePosixPath(e.filename)
                        if p.is_absolute() or '..' in p.parts or '\\' in e.filename or stat.S_ISLNK(e.external_attr>>16) or e.filename in seen: raise ValueError('Unsafe archive')
                        seen.add(e.filename)
                    z.extractall(stage)
                # Accept one enclosing mod folder or files directly at archive root.
                children=list(stage.iterdir());content=children[0] if len(children)==1 and children[0].is_dir() else stage
                if kind=='lua' and not any((content/folder/'main.lua').is_file() for folder in ('Scripts','scripts')): raise ValueError('Expected scripts/main.lua or Scripts/main.lua at the mod root')
                if kind=='schema':
                    jsons=list(content.rglob('*.json'))
                    if not jsons: raise ValueError('No JSON content found')
                    for p in jsons: json.loads(p.read_text('utf-8-sig'))
                    if any(p.suffix.lower() in ('.dll','.so','.exe') for p in content.rglob('*')): raise ValueError('Content mod contains native code; use framework install')
                os.rename(str(content),str(dest))
                if kind=='lua': write_atomic(dest/'enabled.txt',b'')
            return {'installed':str(dest)}
        raise ValueError('Unknown operation: '+action)

if __name__=='__main__':
    try: print(json.dumps({'ok':True,'result':main(json.loads(sys.stdin.read()))}))
    except Exception as e: print(json.dumps({'ok':False,'error':str(e)}))
