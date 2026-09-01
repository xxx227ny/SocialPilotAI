# Product staging deployment

This deployment is deliberately isolated from the competition Demo.

- Public test origin: `https://47.242.222.177:8443`
- API listener: `127.0.0.1:8081`
- Release root: `/opt/socialpilot-staging/releases`
- Current symlink: `/opt/socialpilot-staging/current`
- Runtime data: `/var/lib/socialpilot-staging`
- Runtime configuration: `/etc/socialpilot-staging/runtime.json`
- Services: `socialpilot-staging-api`, `socialpilot-staging-worker`

The runtime configuration must enable user authentication and public
registration, require secure cookies, and contain a newly generated Fernet key.
It must not contain shared Qwen, DashScope, or Wanx provider keys. Customer keys
are stored encrypted per workspace.

Before changing the staging `current` symlink, record its target and create a
SQLite online backup. Rollback consists of restoring the previous symlink,
restarting only the two staging services, and verifying `/api/v1/health`.

Never restart or repoint `socialpilot-api`, `socialpilot-worker`, or
`/opt/socialpilot/current` as part of a staging deployment.
