# 0.1.0 — early prerelease

Named, loopback-only macOS SSH tunnels with per-user LaunchAgents, persistent
stop/start controls, validated definitions, diagnostics, bounded logs and
ownership-checked CLI installation/upgrades.

Requirements: macOS 14+ intended target, Python 3.11–3.14, existing trusted SSH
access. See README for actual tested versions and migration instructions.
Existing personal installations are never upgraded or migrated automatically.

21 unit tests pass locally on macOS 26.6.2 / Python 3.14.6 and in CI on macOS 15
with Python 3.11 and 3.14. GitHub could not allocate macOS 14 runners, so those
checks remain unverified. Real launchd bootstrap
was blocked/failed in the restricted development session (error 5); this is not
a passed live lifecycle test. Actual SSH forwarding, login/reboot and sleep/wake
remain unverified for this generalized version. See docs/verification.md.

Licensed under the MIT License. Release assets are raw source files; obtain
both lap-tunnel and install.py together and retain LICENSE, or use a checkout.
