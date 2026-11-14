#!/usr/bin/env python3
"""Exercise local task behavior and rejected networking without connecting externally."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rag.query import query, QueryError
from rag.providers import OpenAICompatibleClient, ProviderError


class OfflineTests(unittest.TestCase):
    def launch(self, code):
        return subprocess.run([sys.executable, '-I', '-B', str(ROOT/'dsh/offline-exec.py'),
                               '--', sys.executable, '-c', code], text=True, capture_output=True)

    def test_parent_can_create_socket_without_connecting(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
            pass

    def test_ipv4_ipv6_tcp_udp_blocked(self):
        result = self.launch('''import socket,errno
for domain in (socket.AF_INET,socket.AF_INET6):
 for kind in (socket.SOCK_STREAM,socket.SOCK_DGRAM):
  try: socket.socket(domain,kind)
  except OSError as e: assert e.errno==errno.EPERM,(domain,kind,e)
  else: raise AssertionError('network socket was created')
print('blocked')''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'blocked')

    def test_child_exec_inherits_filter_even_if_env_removed(self):
        result = self.launch('''import os,sys
os.environ.pop('MANDIFUEL_TASK_OFFLINE',None)
os.execv(sys.executable,[sys.executable,'-c',"import socket; socket.socket(socket.AF_INET)"])''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Operation not permitted', result.stderr)

    def test_local_io_math_and_unix_socket_work(self):
        result = self.launch('''import tempfile,pathlib,socket,math,os
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d)/'local';p.write_text('输入卡');assert p.read_text()=='输入卡'
a,b=socket.socketpair();a.send(b'ok');assert b.recv(2)==b'ok';a.close();b.close()
assert math.sqrt(144)==12 and os.environ['MANDIFUEL_TASK_OFFLINE']=='1'
print('local ok')''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_local_lookup_under_network_filter(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'dsh/offline-exec.py'),
            '--', sys.executable, str(ROOT/'rag/query.py'), '--query',
            'Cases/Verification/trisoBenchmarks/case_6', '--labels-json',
            '{"geometry":"1D_spherical"}', '--limit', '2', '--compact'], capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['mode'], 'local')
        self.assertEqual(data['provider_telemetry']['network_requests'], 0)
        self.assertEqual(data['candidates'][0]['card_path'], 'Cases/Verification/trisoBenchmarks/case_6')

    def test_local_query_never_calls_http(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP must not be called')):
            data=query('oxidation cladding interface temperature', limit=3)
        self.assertEqual(len(data['candidates']),3)
        self.assertFalse(data['fusion']['embedding_used'])

    def test_invalid_labels_and_no_lexical_hit(self):
        with self.assertRaises(QueryError):
            query('fuel', labels={'geometry':'invented_shape'})
        self.assertEqual(query('zzqnomatch987654321')['candidates'], [])

    def test_maintenance_http_rejected_before_request(self):
        client=OpenAICompatibleClient(base_url='https://example.invalid',model='not-used',api_key='fake')
        with patch.dict(os.environ, {'MANDIFUEL_TASK_OFFLINE':'1'}), patch('urllib.request.urlopen', side_effect=AssertionError('HTTP must not be called')):
            with self.assertRaisesRegex(ProviderError,'disabled'):
                client.embed_texts(['not sent'])


if __name__=='__main__':
    unittest.main(verbosity=2)
