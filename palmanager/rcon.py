"""One-command RCON session, including Palworld's ID-zero response variant."""
import struct

def execute(channel,password,command):
    def send(ident,kind,text):
        body=struct.pack('<ii',ident,kind)+text.encode('utf-8')+b'\0\0'
        channel.sendall(struct.pack('<i',len(body))+body)
    def exact(length):
        data=b''
        while len(data)<length:
            part=channel.recv(length-len(data))
            if not part:raise RuntimeError('RCON connection closed before replying')
            data+=part
        return data
    def receive():
        length=struct.unpack('<i',exact(4))[0]
        if not 10<=length<=4*1024*1024:raise RuntimeError('Invalid RCON packet length')
        body=exact(length)
        if body[-2:]!=b'\0\0':raise RuntimeError('Invalid RCON packet terminator')
        return struct.unpack('<ii',body[:8])+(body[8:-2].decode('utf-8','replace'),)
    send(1,3,password)
    for _ in range(8):
        ident,kind,text=receive()
        if ident==-1:raise RuntimeError('RCON authentication failed')
        if ident==1 and kind==2:break
        if not (ident in (0,1) and kind==0 and not text):raise RuntimeError('Unexpected RCON authentication packet')
    else:raise RuntimeError('No RCON authentication response')
    send(2,2,command)
    for _ in range(8):
        ident,kind,text=receive()
        if ident==-1:raise RuntimeError('RCON authentication failed')
        # A delayed empty authentication packet is not a command result.
        if ident in (0,1) and kind==0 and not text:continue
        # Native Palworld 1.0.4 replies with ID 0 instead of echoing ID 2.
        # This socket has only one outstanding command, so it is unambiguous.
        if kind==0 and ident in (0,2):return text
        raise RuntimeError('Unexpected RCON command packet (ID '+str(ident)+', type '+str(kind)+')')
    raise RuntimeError('No RCON command response')
