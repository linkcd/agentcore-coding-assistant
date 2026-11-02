# AgentCore runtime

## Goal

This component runs interactive coding assistants in Amazon Bedrock AgentCore Runtime.
A person attaches to a running assistant through a terminal connection.
The component builds the container images, deploys them with TypeScript CDK, and checks the result.

The connector that opens these terminals is a separate project: [linkcd/herdr-agentcore](https://github.com/linkcd/herdr-agentcore).
This component does not depend on the connector code.
The two projects share only a [versioned JSON connection contract](../../contracts/1.0.0/README.md).

To host a person's own terminal on EC2 instead, see [`../ec2_herdr_host/`](../ec2_herdr_host/README.md).

## How it works

```text
Provision profile + image definition + external bindings
    -> TypeScript CDK
    -> AgentCore Runtime + execution role
    -> connection descriptor (JSON)
```

- A **provision profile** is a named JSON file in `provision_profiles/`. It selects an image, a model, lifecycle limits, and storage.
- An **image definition** in `agent_images/` holds the Dockerfile, build arguments, and the launch command for one assistant.
- An **adapter** in the image sets up the assistant: its model routing, its tools, and its work-health reports.
- **Storage** is optional. A profile with S3 storage mounts its own S3 Files access point as the workspace. Other profiles keep files on local compute only.
- **Credentials** come from the AWS role of the runtime. The component stores no credentials.
- The **connection descriptor** gives the connector the runtime ARN and the launch command. It gives nothing else.

[Design](../../docs/DESIGN.md) explains these parts in more detail. [Requirements](../../docs/REQUIREMENTS.md) lists the rules that the design follows.

## What you provide

For a profile without S3 storage, you provide nothing except AWS sign-in and a bootstrapped CDK environment.
For a profile with S3 storage, you provide an existing bucket, subnets, and security groups.
Copy `.sample.env` to `.env` in this folder, and enter their IDs. Git ignores `.env`.
[Storage mapping](../../docs/STORAGE_MAPPING.md) explains how a profile maps to a path in the bucket.

## Use it

Run these commands from the repository root. Replace the profile name with a file name from `provision_profiles/`.

```bash
npm ci --prefix src/agentcore_runtime/cdk
npm --prefix src/agentcore_runtime/cdk run cdk -- diff -c runtimeProfile=<profile>
```

Review the diff. Deploy only with explicit authorization:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy -c runtimeProfile=<profile> \
  --outputs-file "$PWD/.local/deployments/<profile>.json"
```

A profile with S3 storage also deploys its storage stack. Add `--all` if CDK asks you to select stacks.

The stack outputs `RuntimeArn`, `RuntimeId`, and `ConnectionDescriptor`.
To write the descriptor to a file for the connector, run the offline exporter.
The output path must not exist yet.

```bash
npm --prefix src/agentcore_runtime/cdk run export-connection -- \
  --cdk-outputs <outputs.json> --stack <stack-name> --output <connection.json>
```

## Know before you change it

- Only files on the mounted S3 workspace persist. The default home directory and conversation state are ephemeral.
- The connector, not this component, decides how Herdr recognizes an assistant and which host credentials it uses.
- Never put credentials or real IDs in Git. Keep them in `.env` or under `.local/`. Git ignores both.
- The deploy does not change connector profiles or account retention settings.

## Where to find details

| Topic | Location |
| --- | --- |
| Profile fields and their meaning | Comments on `RuntimeProfile` in `cdk/profile.ts` |
| Sample profiles and their model, network, and lifecycle values | `provision_profiles/*.json` |
| Image tools, versions, and checksums | `agent_images/*/image.json` |
| Startup, mount checks, and health service | `agent_images/common/` |
| Assistant model routing and work-health reports | `agent_images/<assistant>/` |
| Descriptor producer | `cdk/connection.ts` |
| Storage layout and access boundaries | [Storage mapping](../../docs/STORAGE_MAPPING.md) |
| Lifecycle, credentials, and session state | [Design](../../docs/DESIGN.md) |
| Connection contract and its update steps | [Contract](../../contracts/1.0.0/README.md) |
| Image build and container checks | Docstring of `tests/build_runtime_image.py` |
| Live probes | Docstring and `--help` of each `tests/live_*.py` file |
| Required checks before a change | [Contributor instructions](../../agent.md) |

Live probes use real AWS resources. Run them only with explicit authorization and only in disposable sessions.
