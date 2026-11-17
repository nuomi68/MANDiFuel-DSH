import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SERVER=Path(__file__).resolve().parents[1]/'server.py'


class StartupTests(unittest.TestCase):
    def test_occupied_port_exits_before_touching_task_storage(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            root=Path(folder)/'tasks'
            result=subprocess.run([sys.executable,str(SERVER),'--port',str(listener.getsockname()[1]),'--data-dir',str(root)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,1)
            self.assertIn('端口',result.stderr)
            self.assertIn('Ctrl+C',result.stderr)
            self.assertNotIn('Traceback',result.stderr)
            self.assertNotIn('MANDiFuel plugin root',result.stdout)
            self.assertFalse(root.exists())

    def test_invalid_port_is_rejected_before_launch(self):
        result=subprocess.run([sys.executable,str(SERVER),'--port','65536'],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('端口必须在',result.stderr)
        self.assertNotIn('Traceback',result.stderr)


if __name__=='__main__':unittest.main()
