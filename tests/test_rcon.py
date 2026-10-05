import struct,unittest
from palmanager.rcon import execute

def packet(ident,kind,text=''):
 body=struct.pack('<ii',ident,kind)+text.encode()+b'\0\0';return struct.pack('<i',len(body))+body
class Channel:
 def __init__(self,data):self.data=data;self.sent=[]
 def sendall(self,data):self.sent.append(data)
 def recv(self,n):result=self.data[:min(n,3)];self.data=self.data[len(result):];return result
class RconTests(unittest.TestCase):
 def test_palworld_zero_id(self):
  ch=Channel(packet(1,2)+packet(0,0,'Complete Save'));self.assertEqual(execute(ch,'secret','Save'),'Complete Save')
 def test_standard_response_and_delayed_auth(self):
  ch=Channel(packet(1,0)+packet(1,2)+packet(1,0)+packet(2,0,'OK'));self.assertEqual(execute(ch,'secret','Save'),'OK')
 def test_auth_failure_does_not_send_command(self):
  ch=Channel(packet(-1,2))
  with self.assertRaisesRegex(RuntimeError,'authentication failed'):execute(ch,'secret','Save')
  self.assertEqual(len(ch.sent),1)
 def test_unrelated_response_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'Unexpected RCON command'):execute(Channel(packet(1,2)+packet(9,0,'Other')),'secret','Save')
 def test_truncated_packet_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'closed'):execute(Channel(packet(1,2)+packet(0,0,'OK')[:-1]),'secret','Save')
