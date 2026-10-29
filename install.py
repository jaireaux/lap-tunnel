#!/usr/bin/env python3
"""Install or upgrade only the CLI; never migrate or restart existing tunnels."""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys


def load_cli():
    loader = importlib.machinery.SourceFileLoader('lap_tunnel', str(Path(__file__).with_name('lap-tunnel')))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cli = load_cli()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(prefix, upgrade=False, uninstall=False):
    prefix = Path(prefix).expanduser().absolute()
    dest = prefix / 'bin/lap-tunnel'
    manifest = prefix / 'share/lap-tunnel/install.json'
    if dest.is_symlink() or manifest.is_symlink():
        raise cli.Error('Refusing symlink destination/manifest')
    backup = dest.with_name('lap-tunnel.previous')
    previous = None
    meta = None
    if dest.exists() or manifest.exists():
        if not (dest.is_file() and manifest.is_file()):
            raise cli.Error('Unmanaged or incomplete installation; no files changed')
        meta = json.loads(manifest.read_text())
        previous = dest.read_bytes()
        if meta.get('owner') != cli.MARKER or meta.get('sha256') != digest(previous):
            raise cli.Error('Unmanaged or modified executable; no files changed')
        if not (upgrade or uninstall):
            raise cli.Error('Already installed; use --upgrade')
    elif upgrade or uninstall:
        raise cli.Error('No managed installation exists at this prefix')
    if backup.exists() or backup.is_symlink():
        if backup.is_symlink() or not meta or not backup.is_file() or meta.get('previous_sha256') != digest(backup.read_bytes()):
            raise cli.Error('Unmanaged or modified backup; no files changed')
    if uninstall:
        # Never leave jobs with an executable we are about to remove.
        agents = Path.home() / 'Library/LaunchAgents'
        for path in agents.glob(cli.PREFIX + '*.plist'):
            raise cli.Error('Remove all v1 tunnels first: lap-tunnel remove NAME')
        dest.unlink()
        manifest.unlink()
        if backup.is_file():
            backup.unlink()
        print('CLI removed; private definitions/logs retained. See README for optional cleanup.')
        return
    executable = str(Path(sys.executable).absolute())
    if any(c.isspace() for c in executable):
        raise cli.Error('Python executable path must not contain whitespace')
    body = Path(__file__).with_name('lap-tunnel').read_bytes().split(b'\n', 1)[1]
    payload = ('#!' + executable + '\n').encode() + body
    old_backup = backup.read_bytes() if backup.exists() else None
    # Backup is the exact former executable and can be restored manually.
    if previous is not None:
        cli.atomic(dest.with_name('lap-tunnel.previous'), previous, 0o755)
    old_manifest = manifest.read_bytes() if meta else None
    try:
        cli.atomic(dest, payload, 0o755)
        cli.atomic(manifest, (json.dumps({'owner': cli.MARKER, 'version': cli.VERSION,
                                        'sha256': digest(payload), 'python': executable,
                                        'previous_sha256': digest(previous) if previous is not None else None}, indent=2) + '\n').encode())
    except Exception:
        if previous is not None:
            cli.atomic(dest, previous, 0o755)
            cli.atomic(manifest, old_manifest)
        if old_backup is not None:
            cli.atomic(backup, old_backup, 0o755)
        else:
            backup.unlink(missing_ok=True)
        if previous is None:
            dest.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
        raise
    print('Installed:', dest)
    print('No tunnels changed or started. Add this bin directory to PATH if needed.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--upgrade', action='store_true')
    group.add_argument('--uninstall', action='store_true')
    a = p.parse_args()
    try:
        if sys.platform != 'darwin' or os.getuid() == 0:
            raise cli.Error('Install as the logged-in macOS user, without sudo')
        with cli.Manager().lock():
            install(a.prefix, a.upgrade, a.uninstall)
        return 0
    except (cli.Error, OSError, ValueError) as e:
        print('install: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
