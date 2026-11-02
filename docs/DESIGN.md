# Runtime design

## Ownership

This repository builds and deploys coding runtimes. A separate connector operates their interactive terminals.
The runtime has no dependency on the connector implementation.

```text
Provision profile + image definition + external bindings
    -> TypeScript CDK
    -> AgentCore Runtime + execution role
    -> versioned JSON connection descriptor
```

## Configuration

The CDK entrypoint resolves the selected profile, image, and component `.env` once.
It rejects per-field context overrides and duplicate derived environment settings.
The authenticated CDK Toolkit supplies the AWS account.
Image definitions contain build arguments and explicit launch argv.
Profiles select images and lifecycle, inference, environment, and storage settings.

## Runtime image

The image starts its health service as the container entrypoint.
An interactive Shell connection invokes the published launch command.
`/app/run.sh` starts the selected adapter's `run.py`.
Shared startup validates the required mount, sets local cache paths, and selects the working directory.
Adapters own native CLI settings and AWS credential-provider integration.
The image includes development tools. Each image definition holds their exact versions and checksums.
Caches and disposable tool environments use `/tmp/agentcore`.
Persistent MCP source and lockfiles can live in `/mnt/workspace/tools/`. Native MCP registrations belong in `/mnt/workspace/opencode.json`.
The optional `agentcore-mcp` command rebuilds a locked Python tool project into local runtime storage.
The image installs no MCP server and no GitHub credential broker.

## Persistent storage

The storage stack manages S3 Files resources using an externally owned bucket and VPC.
Each S3 runtime profile owns a distinct access point and mount authorization.
Sessions of that profile share its mounted files, but have independent compute and local caches.
See [storage mapping](STORAGE_MAPPING.md) for paths and boundaries.

## Connection contract

The plugin repository owns the [versioned contract](../contracts/1.0.0/README.md).
This repository contains checksum-pinned schema/fixtures and an independent TypeScript producer.
The producer exports only runtime ARN, launch command, and an optional endpoint.
It does not export Herdr recognition hints or provision-profile labels.
No contract implementation is included in the running agent container.

## Lifecycle and credentials

Idle timeout and maximum lifetime are deployment settings in the provision profile.
Both are platform lifecycle settings. They are not a timer based only on keyboard input.
WebSocket traffic and work-health reports can affect idle accounting.
Actual work can be reported with `HealthyBusy`; process existence alone is not work.
The maximum compute lifetime is not extended by work reporting.
OpenCode reports tracked work through short-lived, PID-validated health leases.
A question or permission wait counts as idle only when no other tracked work remains.
Codex supplies readiness health only. It has no work reporter.
The runtime sends no advancing `time_of_last_update` to AWS.
Use AWS role credential providers rather than static credential snapshots.
The launcher does not export credential snapshots.
Execution roles permit both Bedrock Runtime and Mantle inference, independently of startup routing.
The application owner configures authentication for external services such as GitHub.

## Session state

A profile without S3 storage starts in `/home/agent`. A profile with S3 storage starts in `/mnt/workspace`.
Only mounted files persist when compute is replaced. The default home directory and conversation state are ephemeral.
Do not point multiple runtimes at one shared live conversation database without a separate persistence design.
The image keeps OpenCode auto-update off.
A saved conversation can show provider-specific history limits after you change the model provider.

## Verification

CDK tests synthesize using fictional bindings. They validate resource identity, IAM, image staging, and descriptors.
Contract tests use the pinned valid/invalid fixtures and verify their checksums.
Python tests validate startup, tools, work-health behavior, and disposable-probe cleanup.
Container and AWS probes are opt-in and must not operate on existing user sessions.
