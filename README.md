# lap-tunnel

Named SSH tunnels for macOS, managed by per-user LaunchAgents. Start a tunnel
once, keep it available after SSH failures, and stop it persistently when you
no longer need it. No Terminal window, administrator privileges, daemon,
third-party Python package, or private-key copying required.

**Release candidate 0.1.0. License selection is pending the owner's decision.**
No open-source license is granted until a LICENSE file is added. Do not treat
this staging version as an open-source release.

## Requirements and support

- macOS 14 or later is the intended target; a logged-in graphical user session
  is required. Local unit tests ran on macOS 26.6.2 with Python 3.14.6.
  Other supported-version combinations require CI confirmation.
- Python 3.11–3.14, installed by you (for example from python.org or Homebrew).
  Keep that interpreter installed at the same path. macOS does not need to
  ship Python. No pip dependencies.
- macOS `/usr/bin/ssh`, `launchctl`, `lsof`, and `pgrep`.
- An existing SSH config alias with noninteractive key authentication and a
  trusted host key. Verify the server fingerprint independently and connect
  interactively before using background tunnels. Encrypted keys must be
  available to the login session's SSH agent/Keychain; no password prompt can
  be answered by a LaunchAgent.

The tool does not provision keys, edit SSH configuration, accept unknown host
keys, install a server, or change router/firewall rules. The alias must not
supply additional LocalForward, RemoteForward or DynamicForward directives.
Use a dedicated alias if needed. Existing ProxyJump/ProxyCommand settings are
trusted user configuration and still apply.

## Install

Review the source, then from a checkout:

```sh
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
lap-tunnel --version
```

The installer uses the absolute path of the Python that runs it. It installs
only the CLI and an ownership/hash manifest under `~/.local`. It creates no
LaunchAgents and starts no tunnels. Put the PATH change in your shell profile
if desired. Run without sudo.

**Existing personal installations are never overwritten.** If a binary already
exists without this installer's matching manifest, installation fails without
changing it. For side-by-side evaluation:

```sh
python3 install.py --prefix "$HOME/.local/opt/lap-tunnel-v1"
"$HOME/.local/opt/lap-tunnel-v1/bin/lap-tunnel" --help
```

Use the full path during evaluation so your shell keeps using the original CLI.
The v1 job namespace is `org.lap-tunnel.v1.`. It neither discovers nor migrates
older LaunchAgents. Never start two tunnels on the same local endpoint.

## Define and manage a tunnel

Assume `dev-server` is an alias already configured in `~/.ssh/config`.

```sh
lap-tunnel add dashboard --ssh-host dev-server --local-port 18080 --remote-port 8080
lap-tunnel show dashboard
lap-tunnel doctor dashboard
lap-tunnel start dashboard
lap-tunnel status dashboard
lap-tunnel logs dashboard --lines 60
lap-tunnel stop dashboard
lap-tunnel edit dashboard --remote-port 8081
lap-tunnel start dashboard
lap-tunnel restart dashboard
lap-tunnel list
lap-tunnel remove dashboard
```

| Command | Behavior |
| --- | --- |
| `add NAME` | Validate and save a stopped definition; no job is loaded |
| `edit NAME` | Update supplied fields; requires the tunnel to be stopped |
| `show NAME` | Print the complete private JSON definition |
| `list [NAME]` | Show listener ownership, job and login state |
| `status [NAME]` | Same report; exit 1 if a requested tunnel is not listening |
| `start NAME` | Enable login startup and bootstrap now; connection is asynchronous |
| `stop NAME` | Disable login startup, then unload; repeated stop is safe |
| `restart NAME` | Enable/start if stopped; replace the runner if loaded |
| `logs NAME [--lines N]` | Show recent SSH diagnostics from the current log |
| `doctor NAME` | Show paths, effective SSH settings and diagnostic commands; no connection |
| `remove NAME` | Stop, disable and delete that definition/plist; keep logs |

Use `--remote-host HOST` when the destination is not the SSH server's loopback.
The destination is resolved and contacted **from the SSH server**. `--bind ::1`
selects IPv6 loopback; the default is `127.0.0.1`. Wildcard/LAN binding is not
supported. Local ports must be 1024–65535; remote ports may be 1–65535. SSH users,
ports, identity files and jump hosts belong in SSH config, not CLI arguments.

Exit codes: 0 = command accepted (or all requested statuses listening);
1 = status contains a non-listening tunnel; 2 = validation/operation failure.
Argument-parser errors also return 2. An empty list/status returns 0.

## Recovery, diagnostics and security

LaunchAgents run after GUI login, not before login or while the Mac sleeps.
Enabled jobs use `KeepAlive` and a 30-second restart throttle. SSH uses a
10-second connect timeout and 30-second server-alive checks, exiting after
three unanswered probes. Network recovery can take longer than these settings;
there is no fixed application-availability deadline.

A small Python runner owns foreground SSH, rotates its diagnostic output, and
exits when SSH exits so launchd can retry. SSH multiplexing/backgrounding is
disabled to keep job ownership clear. Strict host-key checking and BatchMode
are enforced even if the alias has weaker defaults. Agent/X11 forwarding and
local commands are disabled. The existing SSH configuration is still trusted
code; this utility is not a sandbox for untrusted aliases or ProxyCommands.

`listening` means a direct child of the managed runner owns the exact local
endpoint. It does **not** verify destination HTTP/TCP health. For example, SSH
can keep a local listener while the destination application is down.

- `connecting/retrying`: inspect `logs`, then `doctor`. Common causes include
  unavailable network, locked/unavailable key, changed host key, or server refusal.
- Port conflict: inspect `lsof -nP -iTCP:PORT -sTCP:LISTEN`. Stop the other owner
  or choose another port; the tool never kills an unrelated listener.
- Unknown/changed host key: compare the fingerprint with an independently
  trusted source and repair SSH trust yourself. Do not disable verification.
- Bootstrap failure: check `launchctl print gui/$(id -u)` and macOS background
  item settings. Run from your GUI login account. Do not retry as root.
- Python moved/removed: reinstall with the intended Python and `--upgrade`,
  then stop/start each affected job so its plist references the new interpreter.
- SSH config changed: restart the tunnel to re-evaluate it. Additional forwards
  are rejected on start and by the runner. `doctor` can reveal private hostnames,
  usernames and identity paths; redact diagnostics and logs before sharing.

## Private files

| Location | Content |
| --- | --- |
| `~/Library/Application Support/lap-tunnel/tunnels/NAME.json` | Versioned private definitions, mode 0600 |
| `~/Library/LaunchAgents/org.lap-tunnel.v1.NAME.plist` | Generated owned LaunchAgent, mode 0600 |
| `~/Library/Logs/lap-tunnel-v1/NAME.log` | Current diagnostic log |
| `~/.local/share/lap-tunnel/install.json` | Installed executable hash, interpreter and owner marker |

Each tunnel keeps a current log plus up to three rotated backups (`.log.1`–`.3`),
about 4 MiB total. A single diagnostic chunk may exceed the size threshold
slightly. Logs contain connection metadata and errors, not application bodies.
Config and log directories are created private. Keep operational files outside
source control. No secret values are needed in definitions or public examples.

## Upgrade and rollback

```sh
python3 install.py --upgrade
```

Use the same `--prefix` used at installation. Upgrades validate the ownership
manifest and current executable hash, save the exact previous CLI as
`bin/lap-tunnel.previous`, then replace files atomically. Exceptions during
installation restore the prior executable/manifest. Definitions, logs, SSH
settings and running jobs are unchanged. Existing runners continue their loaded
version until restarted. Stop/start jobs after an interpreter-path change;
`restart` alone uses the already-loaded plist.

This is not a crash-proof multi-file filesystem transaction: power loss between
binary and manifest replacement can leave a mismatched installation. It refuses
subsequent overwrite rather than guessing. Keep the previous checkout available;
verify the installed/backup files before repairing a mismatched manifest. To
roll back a healthy managed installation, run that previous checkout's
`install.py --upgrade` with its supported Python. Do not blindly copy a binary
over the manifest or use `--upgrade` on an older personal installation.

## Migration and uninstall

See [the migration guide](docs/migration.md). Automatic import of legacy plists
is intentionally unsupported: labels, private paths and forwarding semantics
must be reviewed. Side-by-side installation is the safe evaluation route.

For removal, use the installed CLI to run `remove NAME` for each entry in `list`,
then run from a retained checkout:

```sh
python3 install.py --uninstall
# Include --prefix PATH if installed under a custom prefix.
```

Uninstall refuses while any v1 LaunchAgent plists remain. It removes only its
verified managed executable, manifest and previous executable. Definitions/logs
are retained for recovery. After reviewing them, optionally delete the exact
`~/Library/Application Support/lap-tunnel` and
`~/Library/Logs/lap-tunnel-v1` directories. Remove a PATH entry only if it was
added solely for a dedicated prefix. Shared `~/.local/bin` must stay on PATH
if used by other programs. Existing SSH keys/configuration remain yours.

## Tests and verification limits

```sh
python3 -m unittest discover -s tests -v
python3 tests/launchd_smoke.py   # opt-in, logged-in macOS desktop only
```

Unit tests cover validation/injection rejection, IPv6, inherited-forward guards,
command exit codes, lifecycle order, port collisions, ownership checks,
installation/upgrade rollback/uninstall, child failure and bounded log rotation.
They use temporary homes, test-only names and mocked platform/network actions.

The opt-in smoke test uses a temporary `test-recovery-*` label and `/bin/sleep`,
no SSH or ports. It checks actual launchd start/stop/restart and process recovery,
then unloads its exact label and removes temporary files. It does not claim SSH
connectivity. See [verification](docs/verification.md) for observed outcomes.
Actual SSH forwarding, logout/login, reboot and sleep/wake must be checked on a
normal Mac session before claiming those scenarios passed.

Implementation references: [Apple launchd guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
and [OpenSSH ssh_config](https://man.openbsd.org/ssh_config).

Development timing baseline: [development record](docs/development.md).
Publication review: [audit scope](docs/release-audit.md).
