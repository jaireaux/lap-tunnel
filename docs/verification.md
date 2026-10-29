# Release candidate verification

Version: 0.1.0. Checked 2026-10-29 on macOS 26.6.2 / Python 3.14.6.

- Unit suite: 21 tests passed, including subprocess failure and actual log
  rotation. Platform operations and socket binding are simulated in unit tests.
- `ssh -G` output format was checked locally; IPv4 endpoints are bracketed by
  this macOS OpenSSH. The parser accepts bracketed and unbracketed formatting.
- Actual launchd smoke attempt: **not passed**. Bootstrap returned error 5
  (Input/output error) in the restricted development session. The test's
  exact temporary label was unloaded/cleaned up. The reason for error 5 was
  not independently established; no root retry was made.
- Socket binding in the development shell: denied by session policy
  (Operation not permitted). No live network forwarding test of v1 is claimed.
- No reboot/login, logout/login or real sleep/wake check has been performed.
- CI workflows are supplied; a green CI result must be checked separately.

Before promoting broader compatibility claims, run the opt-in launchd test from
an ordinary macOS GUI terminal. Then use an existing trusted SSH alias and an
unused high local port to test listener ownership, destination access, child
exit recovery, stop/start/restart, logout/login and sleep/wake. Do not kill or
replace an unrelated SSH process to test recovery.
