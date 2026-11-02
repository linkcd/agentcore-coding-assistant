# Coding agent instructions

## Scope

This repository has two independent components:

- `src/agentcore_runtime/` owns AgentCore runtime images, deployment, storage, and verification.
- `src/ec2_herdr_host/` owns the EC2 host for the Herdr TUI and OpenCode.

The source repository is [linkcd/agentcore-coding-assistant](https://github.com/linkcd/agentcore-coding-assistant).
The connector is maintained in [linkcd/herdr-agentcore](https://github.com/linkcd/herdr-agentcore).
Read [README.md](README.md), [runtime documentation](src/agentcore_runtime/README.md), and [the contract](contracts/1.0.0/README.md).
Read the [EC2 host README](src/ec2_herdr_host/README.md) before you change `src/ec2_herdr_host/`.

## Boundaries

1. Keep AgentCore implementation under `src/agentcore_runtime/` and EC2 host implementation under `src/ec2_herdr_host/`.
   The components share no code, CDK app, or `.env` file. Do not import one from the other.
2. In `src/agentcore_runtime/`, use TypeScript CDK in `cdk/` and image adapters in `agent_images/`.
3. Do not import the Herdr plugin or a shared Python contract package.
4. Export only the versioned connection descriptor: runtime ARN, explicit launch argv, and optional endpoint.
5. Derive the region from the ARN on the consumer side. Do not export Herdr recognition hints or provision-profile names.
6. The plugin repository owns the contract specification. Pin the local schema and fixtures by checksum; do not fetch a moving branch during builds.
   Use full SemVer directories such as `contracts/1.0.0/`. The producer and tests select the active directory through `CONTRACT_VERSION`.
7. In `src/agentcore_runtime/`, keep assistant-specific setup, model routing, tool installation, and work-health reporting in the runtime image.
8. In `src/ec2_herdr_host/`, use the existing VPC and subnet from `.env`. Never create a VPC.
   Keep the AMI pinned in the CDK context. Keep first-boot setup in `bootstrap.sh`.
   Rules 2 to 7 apply only to `src/agentcore_runtime/`.

## Deployment and storage

A rule that does not name `src/ec2_herdr_host/` applies to `src/agentcore_runtime/` only.
The `cdk deploy` and `cdk destroy` commands need explicit authorization in both components.

- Use official CDK commands. Do not replace them with custom create/update loops.
- Select a named JSON provision profile. Resolve image/profile settings and component `.env` once at the CDK entrypoint.
- Keep real bindings in ignored `src/agentcore_runtime/.env`. Its only bindings are the existing bucket, subnet IDs, and security-group IDs.
- Keep EC2 host bindings in ignored `src/ec2_herdr_host/.env`. Its only bindings are the existing VPC ID and subnet ID. The EC2 stack never creates a VPC.
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
uv run --frozen ruff check src scripts
uv run --frozen ruff format --check src scripts
uv run --frozen pytest -q --tb=short
npm ci --prefix src/agentcore_runtime/cdk
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
npm ci --prefix src/ec2_herdr_host
npm run check --prefix src/ec2_herdr_host
npm test --prefix src/ec2_herdr_host
uv run --frozen python scripts/check_repository.py
uv run --frozen python scripts/repository_privacy.py
git diff --check
```

Default checks make no AWS calls. Image changes require appropriate ARM64 image builds and container checks.
Live checks require explicit authorization and disposable sessions. Stop only sessions created by the check.

## Repository and documentation rules

- Preserve unrelated edits, local environments, and ignored operational files.
- Commit, push, and create remote repositories only when requested.
- Keep credentials, populated deployment files, session records, and transcripts out of Git.
- Keep the project LICENSE and NOTICE at the repository root. Preserve third-party attribution in images.
- Write all documentation in ASD-STE100 Simplified Technical English (STE). Apply this rule when you create or edit a document.
  - Use short sentences: at most 20 words for steps and 25 words for descriptions.
  - Use the active voice and the imperative form for steps. Use one word for one meaning.
  - Do not use contractions or idioms. Keep one topic in each sentence.
  - Put detail in the document or code comment that it belongs to. Do not copy it to other documents.
- Distinguish implemented behavior, local tests, live tests, and planned work.
- State limits with units. Use fictional identifiers in examples. Preserve exact API, command, and field names.
