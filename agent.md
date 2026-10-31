# Coding agent instructions

## Scope

This repository owns AgentCore runtime images, deployment, storage, and verification.
The Herdr connector is maintained separately in `herdr-to-agentcore`.
Read [README.md](README.md), [runtime documentation](src/agentcore_runtime/README.md), and [the contract](contracts/v1/README.md).

## Boundaries

1. Keep implementation under `src/agentcore_runtime/`.
2. Use TypeScript CDK in `cdk/` and image adapters in `agent_images/`.
3. Do not import the Herdr plugin or a shared Python contract package.
4. Export only the versioned connection descriptor: runtime ARN, explicit launch argv, and optional endpoint.
5. Derive the region from the ARN on the consumer side. Do not export Herdr recognition hints or provision-profile names.
6. The plugin repository owns the contract specification. Pin the local schema and fixtures by checksum; do not fetch a moving branch during builds.
7. Keep assistant-specific setup, model routing, tool installation, and work-health reporting in the runtime image.

## Deployment and storage

- Use official CDK commands. Do not replace them with custom create/update loops.
- Select a named JSON provision profile. Resolve image/profile settings and component `.env` once at the CDK entrypoint.
- Keep real bindings in ignored `src/agentcore_runtime/.env`. Its only bindings are the existing bucket, subnet IDs, and security-group IDs.
- Keep generated deployment outputs and operator-owned network definitions under ignored `.local/deployments/`.
- Each S3 profile owns one access point at `/agent-filesystem/profiles/<profile-name>`, mounted directly at `/mnt/workspace`.
- Keep UID/GID 1000:1000 and mode 755. Do not add another profile directory below the mount.
- Preserve external networking, buckets, existing files, and access-point-scoped worker IAM permissions.
- Require explicit authorization before deploying, stopping user sessions, or changing account retention settings.
- Keep `/app/run.sh` as the stable image launcher. Use native AWS role credential providers; never export credential snapshots.
- Work-health leases contain metadata only. Renew busy leases every 10 seconds and accept live PID/start-tick matches within 45 seconds. Do not advance AWS `time_of_last_update` on every ping.
- Lifecycle settings belong to provision profiles. The current samples specify 900 seconds idle and 28,800 seconds maximum compute lifetime.

## Validation

Run from the repository root:

```bash
uv sync --frozen
uv run --frozen ruff check src
uv run --frozen ruff format --check src
uv run --frozen pytest -q --tb=short
npm ci --prefix src/agentcore_runtime/cdk
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
git diff --check
```

Default checks make no AWS calls. Image changes require appropriate ARM64 image builds and container checks.
Live checks require explicit authorization and disposable sessions. Stop only sessions created by the check.

## Repository and documentation rules

- Preserve unrelated edits, local environments, and ignored operational files.
- Commit, push, and create remote repositories only when requested.
- Keep credentials, populated deployment files, session records, and transcripts out of Git.
- Keep the project LICENSE and NOTICE at the repository root. Preserve third-party attribution in images.
- Use short sentences and consistent terms. Distinguish implemented behavior, local tests, live tests, and planned work.
- State limits with units. Use fictional identifiers in examples. Preserve exact API, command, and field names.
