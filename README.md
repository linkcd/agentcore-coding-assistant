# AgentCore coding runtimes

Build and deploy interactive coding assistants in Amazon Bedrock AgentCore Runtime.
This repository owns the images, TypeScript CDK infrastructure, storage settings, and runtime verification.
The Herdr connector is maintained independently in `herdr-to-agentcore`.

The repositories share a versioned JSON data format, not implementation packages.

## Layout

```text
src/agentcore_runtime/
  agent_images/       Shared image support and assistant adapters
  cdk/                TypeScript CDK and local descriptor producer
  provision_profiles/ Named deployment settings
  tests/              Offline checks and opt-in live probes
contracts/v1/         Checksum-pinned descriptor schema and fixtures
docs/                 Runtime architecture and storage documentation
```

The image adapters currently provide OpenCode 1.18.30 and Codex 0.163.0.
Both images include pinned development tools and use native AWS credential providers.
Conversation state is runtime-local. GitHub credentials are configured separately.

## Install development dependencies

Use Python 3.11+, uv, Node.js 22+, and npm.
Docker with ARM64 build support and AWS deployment credentials are required for deployment.

```bash
uv sync --frozen
npm ci --prefix src/agentcore_runtime/cdk
```

The Python environment contains verification tools only.
It does not install the Herdr plugin or a shared contract package.

## Deployment profiles

| Profile | Assistant | Network and storage |
| --- | --- | --- |
| `codex-agentcore-profile-1` | Codex / GPT-5.6 Sol | PUBLIC; ephemeral home |
| `opencode-agentcore-profile-2` | OpenCode / Kimi K3 | PUBLIC; ephemeral home |
| `opencode-s3filesystem-agentcore-profile-3` | OpenCode / Kimi K3 | Existing VPC; S3 Files at `/mnt/workspace` |

For S3 storage, fill ignored `src/agentcore_runtime/.env` from the adjacent `.sample.env`.
Supply only the existing bucket name, subnet IDs, and security-group IDs.
The storage stack creates an S3 Files filesystem and mount targets on that external network.
Each S3-backed runtime profile creates a dedicated access point.
See [storage mapping](docs/STORAGE_MAPPING.md).

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- synth \
  -c runtimeProfile=opencode-agentcore-profile-2
npm --prefix src/agentcore_runtime/cdk run cdk -- diff \
  -c runtimeProfile=opencode-agentcore-profile-2
```

Deploy only after reviewing the diff:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy \
  -c runtimeProfile=opencode-agentcore-profile-2 \
  --outputs-file "$PWD/.local/deployments/opencode-agentcore-profile-2.json"
```

Use the appropriate profile for another runtime. An S3 deployment also includes its named storage stack.
See [the runtime guide](src/agentcore_runtime/README.md) for detailed configuration and validation.

## Connection output

CDK exports `RuntimeArn`, `RuntimeId`, and a JSON string named `ConnectionDescriptor`.
The descriptor contains required runtime ARN and launch argv, plus an optional endpoint qualifier.
The region is derived by the consumer. Herdr recognition and local profile names are not exported.

The local producer is `src/agentcore_runtime/cdk/connection.ts`.
It has no import from the plugin repository.
The pinned [contract](contracts/v1/README.md) supplies conformance data and release provenance.

A connector can import the CDK output or a standalone descriptor.
For Herdr, configure the local recognition hint separately with `--agent-kind`.

## Export a standalone descriptor

The offline exporter validates a selected CDK output and writes its connection descriptor to a new file:

```bash
npm --prefix src/agentcore_runtime/cdk run export-connection -- \
  --cdk-outputs /path/to/outputs.json --stack RuntimeStack \
  --output /path/to/connection.json
```

The output path must not already exist. Import the resulting file with the connector's `--connection-file` option.
Invalid descriptors and unsupported fields are rejected. The input file is not modified.

## Checks

```bash
uv run --frozen ruff check src scripts
uv run --frozen ruff format --check src scripts
uv run --frozen pytest -q --tb=short
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
uv run --frozen python scripts/check_repository.py
uv run --frozen python scripts/repository_privacy.py
git diff --check
```

Default checks make no AWS calls. Live probes require explicit authorization and use disposable sessions.
Image changes also require the relevant ARM64 image build and container checks.

## Documentation

- [Runtime guide](src/agentcore_runtime/README.md)
- [Design](docs/DESIGN.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Storage mapping](docs/STORAGE_MAPPING.md)
- [Pinned connection contract](contracts/v1/README.md)
- [Contributor instructions](agent.md)

Keep [LICENSE](LICENSE) and [NOTICE](NOTICE) at the repository root and include them in image builds.
