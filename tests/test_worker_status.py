import io,json,shlex,unittest
from contextlib import redirect_stdout
from unittest.mock import patch,MagicMock
from palmanager.remote import Remote
from palmanager.store import DEFAULT_PROFILE
class WorkerStatusTests(unittest.TestCase):
 def query(self,output,files=False):
  remote=Remote(DEFAULT_PROFILE,{});remote.connect=lambda:MagicMock()
  def execute(connection,command,**kwargs):
   buffer=io.StringIO()
   with patch('subprocess.run',return_value=type('Result',(),{'stdout':output,'stderr':'unavailable'})()),patch('pathlib.Path.exists',return_value=files),redirect_stdout(buffer):exec(compile(shlex.split(command)[-1],'<worker-check>','exec'),{})
   return buffer.getvalue()
  remote.execute=execute;return remote.worker_status()
 def test_not_installed(self):self.assertFalse(self.query('LoadState=not-found\nActiveState=inactive\nUnitFileState=\n')['installed'])
 def test_installed_stopped(self):
  status=self.query('LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n');self.assertTrue(status['installed']);self.assertEqual(status['active'],'inactive');self.assertIsNone(status['health'])
 def test_retained_files_detected_without_unit(self):self.assertTrue(self.query('LoadState=not-found\nActiveState=inactive\n',True)['installed'])
 def test_query_failure_is_not_not_installed(self):
  with self.assertRaisesRegex(RuntimeError,'Unable to query'):self.query('')
