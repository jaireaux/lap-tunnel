# Migrating an earlier personal implementation

The old implementation remains an independent installation. Nothing in this
release renames, disables, deletes, or imports its jobs. Keep its source and
operational history privately; do not copy old plists into this repository.

1. Install v1 under a dedicated prefix. Use its full CLI path throughout.
2. Review the old plist locally: identify the SSH alias, local binding/port,
   destination and port. Review any extra SSH flags manually. Never extract or
   copy credentials, private keys, SSH config, logs or unrelated project files.
3. Use v1 `add` to reproduce only the reviewed values. This saves a stopped
   definition. Run `show` and `doctor` and verify host trust/key availability.
4. For a nondisruptive trial, use a different local port. Start, check the managed
   listener, and separately check destination application access. Stop/remove
   the trial when finished.
5. Schedule the real cutover: stop the old job with the old CLI, then start the
   v1 definition at the original local endpoint. Verify listener ownership,
   application access, persistent stop/start and failure recovery.
6. If verification fails, stop the v1 job first, then restart the old job using
   the old CLI. Never have both own the same endpoint.
7. Keep the old source/plists until logout/login and sleep/wake are verified and
   you accept the migration. Remove old files only after stopping their exact
   jobs and reviewing the old recovery instructions.

No production cutover has been performed as part of preparing this release.
