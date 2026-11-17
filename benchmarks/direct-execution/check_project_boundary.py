"""Exercise actual kernel denials with disposable files, never a solver run."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / 'dsh/offline-exec.py'


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.TemporaryDirectory(prefix='mandifuel-project-')
        self.outside_dir = tempfile.TemporaryDirectory(prefix='mandifuel-outside-')
        self.project = Path(self.project_dir.name)
        self.outside = Path(self.outside_dir.name)
        self.protected = self.outside / 'original.txt'
        self.protected.write_text('protected')
        (self.project / 'escape').symlink_to(self.outside, target_is_directory=True)

    def tearDown(self):
        self.project_dir.cleanup()
        self.outside_dir.cleanup()

    def launch(self, code, cwd=None):
        return subprocess.run([sys.executable, '-I', '-B', str(LAUNCHER),
            '--project-root', str(self.project), '--', sys.executable, '-c', code],
            cwd=cwd or self.project, capture_output=True, text=True, timeout=10)

    def test_whole_project_writable_and_dependencies_readable(self):
        result = self.launch(f'''from pathlib import Path
p=Path('a/b');p.mkdir(parents=True);q=p/'value';q.write_text('ok');q.rename(p/'renamed');(p/'renamed').unlink()
assert Path({str(self.protected)!r}).read_text()=='protected'
import tempfile,os
assert Path(tempfile.mkdtemp()).is_relative_to(Path.cwd())
assert Path(os.environ['XDG_CACHE_HOME']).is_relative_to(Path.cwd())
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_outside_write_create_delete_move_truncate_and_links_denied(self):
        result = self.launch(f'''import os,errno
from pathlib import Path
p=Path({str(self.protected)!r});outside=p.parent
Path('inside').write_text('inside')
operations=[lambda:p.write_text('bad'), lambda:p.open('a'), lambda:os.truncate(p,0),
 lambda:p.unlink(),lambda:(outside/'new').mkdir(),lambda:(outside/'new').write_text('bad'),
 lambda:os.rename('inside',outside/'moved'),lambda:os.rename(p,'stolen'),
 lambda:os.link(p,'hardlink'),lambda:Path('escape/original.txt').write_text('bad'),
 lambda:Path('escape/new').write_text('bad'),lambda:os.symlink('x',outside/'symlink')]
for operation in operations:
 try: operation()
 except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM,errno.EXDEV),e
 else: raise AssertionError('outside operation succeeded')
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.protected.read_text(), 'protected')
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['original.txt'])

    def test_children_cannot_widen_boundary_by_changing_environment(self):
        result = self.launch(f'''import subprocess,sys,os
os.environ['MANDIFUEL_PROJECT_ROOT']='/'
os.environ['TMPDIR']={str(self.outside)!r}
p=subprocess.run([sys.executable,'-c',"from pathlib import Path; Path({str(self.protected)!r}).write_text('bad')"],capture_output=True,text=True)
assert p.returncode!=0 and 'Permission denied' in p.stderr,p.stderr
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.protected.read_text(), 'protected')

    def test_cwd_outside_boundary_fails_before_command(self):
        result = self.launch("print('SHOULD NOT RUN')", cwd=self.outside)
        self.assertEqual(result.returncode, 126)
        self.assertEqual(result.stdout, '')

    def test_symlinked_temporary_directory_cannot_create_outside_files(self):
        (self.project / '.mandifuel-tmp').symlink_to(self.outside, target_is_directory=True)
        result = self.launch("print('SHOULD NOT RUN')")
        self.assertEqual(result.returncode, 126)
        self.assertEqual(result.stdout, '')

    def test_unsupported_kernel_fails_closed(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('boundary_launcher', LAUNCHER)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with patch.object(launcher.platform, 'machine', return_value='unsupported'):
            with self.assertRaises(RuntimeError):
                launcher.restrict_filesystem(str(ROOT))


if __name__ == '__main__':
    unittest.main(verbosity=2)
