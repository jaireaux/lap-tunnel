#!/usr/bin/env python3
"""Opt-in real launchd lifecycle/recovery check. No SSH, ports or personal jobs.

Creates a test-only label and plist in a temporary directory. The child is
/bin/sleep; this checks launchd behavior, not actual SSH or application access.
"""
import contextlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('tunnel_smoke', str(ROOT / 'lap-tunnel'))
spec = importlib.util.spec_from_loader(loader.name, loader)
t = importlib.util.module_from_spec(spec)
loader.exec_module(t)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('macOS only')
    name = 'test-recovery-' + str(os.getpid())
    with tempfile.TemporaryDirectory(prefix='lap-tunnel-smoke-') as tmp:
        m = t.Manager(tmp)
        m.save(dict(schema=1, name=name, ssh_host='example.invalid', local_port=18459,
                    remote_host='127.0.0.1', remote_port=80, bind='127.0.0.1'))
        original = m.plist
        def plist(d):
            p = original(d)
            p['ProgramArguments'] = ['/bin/sleep', '120']
            p['ThrottleInterval'] = 2
            return p
        def pid():
            r = m.loaded(name)
            match = re.search(r'^\s*pid = (\d+)', r.stdout, re.M)
            return int(match[1]) if match else None
        def wait_new(old=None):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                current = pid()
                if current and current != old:
                    return current
                time.sleep(0.25)
            raise AssertionError('No replacement PID within 20 seconds')
        try:
            # No socket bind is needed for a non-network lifecycle fixture.
            with patch.object(m, 'plist', plist), patch.object(t, 'check_ssh_config'), patch.object(t.socket, 'socket'):
                m.start(name)
                first = wait_new()
                os.kill(first, signal.SIGKILL)
                second = wait_new(first)
                print('PASS: launchd replaced killed process', first, second)
                m.start(name, restart=True)
                third = wait_new(second)
                print('PASS: restart replaced process', third)
                m.stop(name)
                assert m.loaded(name).returncode != 0
                disabled = t.run('/bin/launchctl', 'print-disabled', m.domain, check=True).stdout
                assert re.search(r'"' + re.escape(t.PREFIX + name) + r'"\s*=>\s*true', disabled)
                print('PASS: stopped/unloaded; login startup disabled')
                m.start(name)
                wait_new()
                print('PASS: start re-enabled and bootstrapped')
        finally:
            # Only our exact temporary label is touched.
            subprocess.run(['/bin/launchctl', 'bootout', m.service(name)], capture_output=True)
            subprocess.run(['/bin/launchctl', 'enable', m.service(name)], capture_output=True)
    print('PASS: temporary plist removed; no login or sleep/wake claim')


if __name__ == '__main__':
    main()
