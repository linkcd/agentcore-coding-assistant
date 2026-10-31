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

Idle timeout and maximum lifetime are deployment settings.
Actual work can be reported with `HealthyBusy`; process existence alone is not work.
The maximum compute lifetime is not extended by work reporting.
Use AWS role credential providers rather than static credential snapshots.
The application owner configures authentication for external services such as GitHub.

## Verification

CDK tests synthesize using fictional bindings. They validate resource identity, IAM, image staging, and descriptors.
Contract tests use the pinned valid/invalid fixtures and verify their checksums.
Python tests validate startup, tools, work-health behavior, and disposable-probe cleanup.
Container and AWS probes are opt-in and must not operate on existing user sessions.
