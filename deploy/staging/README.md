# Product staging deployment

This deployment is deliberately isolated from the competition Demo.

- Public test origin: `https://staging.47.242.222.177.nip.io`
- API listener: `127.0.0.1:8081`
- Release root: `/opt/socialpilot-staging/releases`
- Current symlink: `/opt/socialpilot-staging/current`
- Runtime data: `/var/lib/socialpilot-staging`
- Runtime configuration: `/etc/socialpilot-staging/runtime.json`
- Services: `socialpilot-staging-api`, `socialpilot-staging-worker`

Nginx serves the built frontend directly from the active release and proxies
only `/api/` requests to the application listener.  This keeps the login page
and hashed assets available while the API is restarted during a release, and
prevents large JavaScript/CSS responses from consuming application-worker
capacity.  `index.html` is always revalidated; hashed assets are cached for one
year.

The runtime configuration must enable user authentication and public
registration, require secure cookies, and contain a newly generated Fernet key.
It must not contain shared Qwen, DashScope, or Wanx provider keys. Customer keys
are stored encrypted per workspace.

Run `configure_runtime.py` with the staging virtual environment to create this
configuration. Re-running it preserves the existing credential-encryption key
and the allowlisted `ACCOUNT_SMTP_*` delivery settings, so stored customer
credentials remain decryptable and configured account email keeps working.
Shared Qwen, DashScope, or Wanx keys are deliberately never preserved: AI
generation continues to require each workspace's independently encrypted Key.

To enable verification and password-recovery email later, run
`configure_account_email.py` interactively on the server. Pass the public
origin, From address, SMTP host/port, username and transport mode as ordinary
options; the SMTP authorization code is requested through hidden terminal
input and is never accepted on the command line or printed. The tool preserves
the rest of the runtime JSON, writes an automatic rollback copy, and does not
send a test message. Restart only `socialpilot-staging-api`, then confirm the
`account_email` item on `/api/v1/system/readiness` before enabling user tests.

Before changing the staging `current` symlink, record its target and create a
SQLite online backup. Rollback consists of restoring the previous symlink,
restarting only the two staging services, and verifying `/api/v1/health`.

Build the release with `build_release_bundle.py` after the product frontend
build completes. The bundle is assembled from the exact Git commit, adds the
three root runtime entrypoints required by the installed services, includes
`frontend-dist`, and writes a non-secret manifest with the commit and hashes.
Do not deploy a hand-assembled source archive: a missing runtime entrypoint can
leave systemd in a restart loop even when the application tests pass.

Never restart or repoint `socialpilot-api`, `socialpilot-worker`, or
`/opt/socialpilot/current` as part of a staging deployment.

After deployment, run `smoke_test.py` against the public staging origin. The
test creates two non-billable validation accounts, uses synthetic provider keys,
verifies one synthetic key through the non-generation model-list endpoint, and
checks secure cookies plus cross-workspace product and credential isolation.
It never starts text, image, audio, or video generation.

`media_smoke_test.py` additionally accepts a verified local MP4 fixture. It
creates an isolated staging artifact without provider calls, then validates
public HTTPS byte ranges, low-bitrate fast-start preview generation, browser
cache headers, shared-CDN denial, and cross-workspace media protection.

After non-billable staging smoke runs, inspect managed test accounts and expired
account tokens with `cleanup_account_records.py --include-smoke-users`. The tool
is dry-run by default. `--apply` first creates a SQLite backup, matches only the
exact timestamped addresses created by `smoke_test.py` and `media_smoke_test.py`,
removes their managed artifact files, checks foreign-key integrity, and never
matches ordinary customer email addresses.
