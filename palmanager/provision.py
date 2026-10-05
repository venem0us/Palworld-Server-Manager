"""Client-side installer transport. Passwords only cross the encrypted SSH stream."""
import base64,json,shlex,socket,time
from pathlib import Path
import paramiko
from .remote import Remote,fingerprint,normalize_fingerprint

def discover_key(host,port):
    sock=socket.create_connection((host,int(port)),timeout=12)
    transport=paramiko.Transport(sock)
    try:
        transport.start_client(timeout=12)
        return fingerprint(transport.get_remote_server_key())
    finally:transport.close();sock.close()

def provision(profile,credentials,options,progress):
    normalize_fingerprint(profile.get('fingerprint',''))
    if not profile.get('fingerprint'):raise ValueError('Read and verify the Ubuntu SSH fingerprint before connecting')
    remote=Remote(profile,credentials);client=remote.connect()
    try:
        folder=Path(__file__).parent
        source=(folder/'settings.py').read_text('utf-8')+'\n'+(folder/'server_install.py').read_text('utf-8')
        script="import base64;exec(compile(base64.b64decode('"+base64.b64encode(source.encode()).decode()+"'),'<palworld-install>','exec'))"
        command='sudo -S -p "" -- python3 -u -c '+shlex.quote(script)
        stdin,stdout,stderr=client.exec_command(command,timeout=30)
        stdin.write(credentials.get('admin_password','')+'\nPALMANAGER_REQUEST_V1\n'+json.dumps(options));stdin.flush();stdin.channel.shutdown_write()
        channel=stdout.channel;buffer=b'';errors=bytearray();result=None;failure=None;deadline=time.monotonic()+10800
        while True:
            while channel.recv_ready():
                buffer+=channel.recv(65536)
                if len(buffer)>1024*1024:raise RuntimeError('Unexpected installer response')
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('event')=='progress':progress(event['message'])
                    elif event.get('event')=='error':failure=event['message']
                    elif event.get('event')=='result':result=event['result']
            while channel.recv_stderr_ready():errors.extend(channel.recv_stderr(65536));errors=errors[-8192:]
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():break
            if time.monotonic()>deadline:channel.close();raise TimeoutError('Installation timed out. Re-run the check to inspect the retained partial installation.')
            time.sleep(.05)
        code=channel.recv_exit_status()
        if failure:raise RuntimeError(failure)
        if code or result is None:raise RuntimeError(errors.decode('utf-8','replace')[-2000:] or 'Installer disconnected before completion. Check Ubuntu before retrying.')
        return result
    finally:client.close()
