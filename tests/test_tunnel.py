import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('tunnel', str(ROOT / 'lap-tunnel'))
spec = importlib.util.spec_from_loader(loader.name, loader)
t = importlib.util.module_from_spec(spec)
loader.exec_module(t)
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def definition(**changes):
    return dict(schema=1, name='test-service', ssh_host='example.invalid', local_port=18451,
                remote_host='127.0.0.1', remote_port=8080, bind='127.0.0.1', **changes) if not changes else dict(definition(), **changes)


def result(code=0, out='', err=''):
    return subprocess.CompletedProcess([], code, out, err)


class Validation(unittest.TestCase):
    def test_invalid_definitions(self):
        for key, values in {'name': ['../x', '-flag', '', 'UPPER', 'a' * 49],
                            'ssh_host': ['-oProxyCommand=x', 'a b', 'user@host', 'a\nx'],
                            'local_port': [True, 0, 1023, 65536, '8080', None],
                            'remote_port': [False, 0, 65536, 1.5],
                            'bind': ['0.0.0.0', '*', 'localhost'],
                            'remote_host': ['x:80:bad', 'a b', '-flag', 1],
                            'schema': [2, True]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(t.Error):
                    t.validate(definition(**{key: value}))
        with self.assertRaises(t.Error):
            t.validate(dict(definition(), unexpected=True))

    def test_ipv6_and_ssh_security(self):
        args = t.ssh_args(definition(bind='::1', remote_host='::1'))
        self.assertIn('[::1]:18451:[::1]:8080', args)
        for value in ['StrictHostKeyChecking=yes', 'BatchMode=yes', 'ControlPath=none',
                      'ForkAfterAuthentication=no', 'GatewayPorts=no', 'ExitOnForwardFailure=yes']:
            self.assertIn(value, args)
        self.assertEqual(args[-1], 'example.invalid')

    def test_inherited_forwards_rejected(self):
        good = 'localforward [127.0.0.1]:18451 [127.0.0.1]:8080\n'
        for output in [good + 'localforward *:8000 localhost:80\n', good + 'remoteforward 9000 localhost:80\n', '', good + 'dynamicforward 9000\n']:
            with patch.object(t, 'run', return_value=result(out=output)), self.assertRaises(t.Error):
                t.check_ssh_config(definition())
        with patch.object(t, 'run', return_value=result(out=good)):
            t.check_ssh_config(definition())


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.m = t.Manager(self.temp.name)
        self.d = definition()
        self.m.save(self.d)
        self.calls = []
        self.active = False
        self.failure = None

    def fake(self, *args, check=False):
        self.calls.append(args)
        if args[1] == 'print':
            return result(0 if self.active else 1, 'pid = 1234\n')
        if args[1] == 'bootstrap' and self.failure:
            raise t.Error('bootstrap failed')
        if args[1] == 'print-disabled':
            return result(out='"org.lap-tunnel.v1.test-service" => true')
        return result()

    def test_duplicate_and_edit_guard(self):
        with self.assertRaises(t.Error):
            self.m.save(self.d)
        with self.assertRaises(t.Error):
            self.m.save(definition(name='other'))
        with patch.object(t, 'run', self.fake):
            self.active = True
            with self.assertRaises(t.Error):
                self.m.save(definition(remote_port=9000), edit=True)
        self.assertEqual(self.m.read('test-service')['remote_port'], 8080)

    def test_start_stop_restart_order_and_plist(self):
        with patch.object(t.socket, 'socket'), patch.object(t, 'run', self.fake), patch.object(t, 'check_ssh_config'), contextlib.redirect_stdout(io.StringIO()):
            self.m.start('test-service')
            data = plistlib.loads(self.m.plist_path('test-service').read_bytes())
            self.assertEqual(data['ProgramArguments'][-2:], ['_run', 'test-service'])
            self.assertTrue(data['KeepAlive'])
            self.assertEqual(data['ThrottleInterval'], 30)
            self.active = True
            self.m.start('test-service', restart=True)
            self.m.stop('test-service')
        actions = [x[1] for x in self.calls]
        self.assertLess(actions.index('enable'), actions.index('bootstrap'))
        self.assertIn('kickstart', actions)
        self.assertLess(actions.index('disable'), actions.index('bootout'))
        self.assertEqual(self.m.plist_path('test-service').stat().st_mode & 0o777, 0o600)

    def test_bootstrap_failure_disables_login(self):
        self.failure = True
        with patch.object(t.socket, 'socket'), patch.object(t, 'run', self.fake), patch.object(t, 'check_ssh_config'), self.assertRaises(t.Error):
            self.m.start('test-service')
        self.assertEqual(self.calls[-1][1], 'disable')

    def test_port_collision_does_not_enable(self):
        with patch.object(t.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('address in use')
            with patch.object(t, 'run', self.fake), patch.object(t, 'check_ssh_config'), self.assertRaises(t.Error):
                self.m.start('test-service')
        self.assertNotIn('enable', [x[1] for x in self.calls])

    def test_unmanaged_files_never_overwritten(self):
        p = self.m.plist_path('test-service')
        p.parent.mkdir(parents=True)
        p.write_bytes(plistlib.dumps({'Label': t.PREFIX + 'test-service'}))
        before = p.read_bytes()
        with patch.object(t, 'run', self.fake), self.assertRaises(t.Error):
            self.m.stop('test-service')
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_loaded_collision_without_plist_never_stopped(self):
        self.active = True
        with patch.object(t, 'run', self.fake), self.assertRaises(t.Error):
            self.m.stop('test-service')
        self.assertNotIn('disable', [x[1] for x in self.calls])

    def test_status_never_claims_application_health(self):
        def fake(*args, **kwargs):
            if args[0].endswith('pgrep'):
                return result(out='5678\n')
            if args[0].endswith('lsof'):
                return result(out='p5678\nn127.0.0.1:18451\n')
            return self.fake(*args, **kwargs)
        self.active = True
        output = io.StringIO()
        with patch.object(t, 'run', fake), contextlib.redirect_stdout(output):
            self.assertTrue(self.m.status('test-service'))
        self.assertIn('listening', output.getvalue())
        self.assertIn('login=disabled', output.getvalue())

    def test_remove_only_owned_definition_and_preserve_logs(self):
        self.m.logs.mkdir(parents=True)
        log = self.m.log('test-service')
        log.write_text('historical diagnostic')
        with patch.object(t, 'run', self.fake), contextlib.redirect_stdout(io.StringIO()):
            self.m.remove('test-service')
        self.assertFalse(self.m.definition('test-service').exists())
        self.assertEqual(log.read_text(), 'historical diagnostic')

    def test_cli_add_show_unknown_and_exit_codes(self):
        out = io.StringIO()
        with patch.object(t, 'Manager', return_value=self.m), patch.object(t.sys, 'platform', 'darwin'), patch.object(t.os, 'getuid', return_value=501), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(t.main(['add', 'second', '--ssh-host', 'example.invalid', '--local-port', '18452', '--remote-port', '80']), 0)
            self.assertEqual(t.main(['show', 'second']), 0)
            self.assertEqual(t.main(['show', 'absent']), 2)
            with patch.object(t, 'run', self.fake):
                self.assertEqual(t.main(['status', 'test-service']), 1)
        self.assertEqual(self.m.read('second')['remote_port'], 80)
        self.assertNotIn('bootstrap', [x[1] for x in self.calls])

    def test_symlink_definition_refused(self):
        p = self.m.definition('linked')
        p.symlink_to(self.m.definition('test-service'))
        with self.assertRaises(t.Error):
            self.m.read('linked')


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name)

    def test_fresh_upgrade_and_modified_refusal(self):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.prefix)
            dest = self.prefix / 'bin/lap-tunnel'
            original = dest.read_bytes()
            self.assertTrue(original.startswith(('#!' + sys.executable).encode()))
            with self.assertRaises(installer.cli.Error):
                installer.install(self.prefix)
            installer.install(self.prefix, upgrade=True)
            self.assertEqual(dest.with_name('lap-tunnel.previous').read_bytes(), original)
            dest.write_bytes(original + b'\n# modification\n')
            with self.assertRaises(installer.cli.Error):
                installer.install(self.prefix, upgrade=True)

    def test_unmanaged_backup_refused(self):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.prefix)
            dest = self.prefix / 'bin/lap-tunnel'
            before = dest.read_bytes()
            backup = dest.with_name('lap-tunnel.previous')
            backup.write_text('unrelated file')
            with self.assertRaises(installer.cli.Error):
                installer.install(self.prefix, upgrade=True)
            self.assertEqual(dest.read_bytes(), before)
            self.assertEqual(backup.read_text(), 'unrelated file')

    def test_legacy_install_refused(self):
        dest = self.prefix / 'bin/lap-tunnel'
        dest.parent.mkdir()
        dest.write_text('personal implementation')
        with self.assertRaises(installer.cli.Error):
            installer.install(self.prefix, upgrade=True)
        self.assertEqual(dest.read_text(), 'personal implementation')

    def test_upgrade_rollback_on_manifest_write_failure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.prefix)
            dest = self.prefix / 'bin/lap-tunnel'
            before = dest.read_bytes()
            real = installer.cli.atomic
            failed = False
            def atomic(path, data, *args):
                nonlocal failed
                if path.name == 'install.json' and not failed:
                    failed = True
                    raise OSError('simulated disk failure')
                return real(path, data, *args)
            with patch.object(installer.cli, 'atomic', atomic), self.assertRaises(OSError):
                installer.install(self.prefix, upgrade=True)
            self.assertEqual(dest.read_bytes(), before)
            meta = json.loads((self.prefix / 'share/lap-tunnel/install.json').read_text())
            self.assertEqual(meta['sha256'], installer.digest(before))

    def test_uninstall_preserves_unrelated_files(self):
        home = self.prefix / 'home'
        home.mkdir()
        unrelated = self.prefix / 'bin/other'
        with patch.object(installer.Path, 'home', return_value=home), contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.prefix)
            unrelated.write_text('keep')
            agents = home / 'Library/LaunchAgents'
            agents.mkdir(parents=True)
            managed = agents / (t.PREFIX + 'test-service.plist')
            managed.write_text('placeholder')
            with self.assertRaises(installer.cli.Error):
                installer.install(self.prefix, uninstall=True)
            managed.unlink()
            installer.install(self.prefix, uninstall=True)
        self.assertTrue(unrelated.exists())
        self.assertFalse((self.prefix / 'bin/lap-tunnel').exists())


class RunnerTests(unittest.TestCase):
    def test_runner_child_failure_logged_and_propagated(self):
        with tempfile.TemporaryDirectory() as temp:
            m = t.Manager(temp)
            m.save(definition())
            with patch.object(t, 'check_ssh_config'), patch.object(t, 'ssh_args', return_value=[sys.executable, '-c', 'import sys; print("authentication failed", file=sys.stderr); sys.exit(255)']):
                self.assertEqual(t.runner(m, 'test-service'), 255)
            self.assertIn('authentication failed', m.log('test-service').read_text())
            self.assertIn('SSH exited: 255', m.log('test-service').read_text())

    def test_runner_termination_reaps_child(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            m = t.Manager(temp)
            m.save(definition())
            code = """
import importlib.machinery,importlib.util,sys
from unittest.mock import patch
loader=importlib.machinery.SourceFileLoader('child_runner', sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name, loader)
t=importlib.util.module_from_spec(spec); loader.exec_module(t)
with patch.object(t, 'check_ssh_config'), patch.object(t, 'ssh_args', return_value=[sys.executable, '-u', '-c', 'import os,time; print(os.getpid(), flush=True); time.sleep(60)']):
    sys.exit(t.runner(t.Manager(sys.argv[2]), 'test-service'))
"""
            proc = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'lap-tunnel'), temp])
            try:
                deadline = time.monotonic() + 10
                child_pid = None
                while time.monotonic() < deadline:
                    if m.log('test-service').exists():
                        lines = m.log('test-service').read_text().splitlines()
                        for line in lines:
                            last = line.rsplit(' ', 1)[-1]
                            if last.isdigit():
                                child_pid = int(last)
                    if child_pid:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(child_pid, 'child PID was not logged')
                proc.terminate()
                self.assertEqual(proc.wait(timeout=10), 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_logs_rotate_under_repeated_failure_output(self):
        with tempfile.TemporaryDirectory() as temp:
            m = t.Manager(temp)
            m.save(definition())
            with patch.object(t, 'check_ssh_config'), patch.object(t, 'ssh_args', return_value=[sys.executable, '-c', 'import sys; sys.stdout.write("x" * (6 * 1024 * 1024)); sys.exit(1)']):
                self.assertEqual(t.runner(m, 'test-service'), 1)
            files = list(m.logs.glob('*.log*'))
            self.assertLessEqual(len(files), 4)
            self.assertGreater(len(files), 1)
            self.assertLess(sum(p.stat().st_size for p in files), 4 * 1024 * 1024 + 20000)


if __name__ == '__main__':
    unittest.main()
