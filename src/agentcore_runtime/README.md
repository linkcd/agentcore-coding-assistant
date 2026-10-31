# AgentCore runtime implementation

## Ownership

This component owns image definitions, startup adapters, TypeScript CDK, storage, and runtime checks.
The connector is maintained in [linkcd/herdr-agentcore](https://github.com/linkcd/herdr-agentcore).
The shared boundary is the [pinned JSON connection contract](../../contracts/1.0.0/README.md).
No plugin or shared contract implementation package is required here.

## Source layout

| Directory or file | Purpose |
| --- | --- |
| `agent_images/common/` | Shared Dockerfile, tools, mount checks, startup support, and health endpoint. |
| `agent_images/opencode/` | OpenCode image settings, model routing, and work-activity hooks. |
| `agent_images/codex/` | Codex image settings, provider configuration, and sandbox preset. |
| `provision_profiles/` | Named runtime settings. |
| `cdk/` | Deployment and storage stacks, input validation, and descriptor producer. |
| `tests/` | Offline tests, image checks, and explicitly selected live probes. |
| `.sample.env` | Template for external bucket/network bindings. |

The deployed command is `/app/run.sh`, which executes the selected adapter's `run.py`.
The shared launcher validates required mounts, configures local caches, and changes to the selected working directory.
The adapter chooses its own CLI and model configuration.

## Profile settings

The samples are `codex-agentcore-profile-1`, `opencode-agentcore-profile-2`, and `opencode-s3filesystem-agentcore-profile-3`.
They are deployment settings references, not an assistant enum in a connector.
The entrypoint accepts only `-c runtimeProfile=NAME` for selecting project configuration.

| Field | Purpose |
| --- | --- |
| `stackName`, `runtimeName`, `region` | Deployment names and AWS region. The CDK Toolkit supplies the authenticated account. |
| `image` | Select a directory under `agent_images/`. |
| `command` | Optional explicit override of the image's launch argv. |
| `inference.modelId` | Startup model identifier. |
| `inference.region` | Optional inference-region override. Defaults to deployment region. |
| `inference.bedrock-endpoint-type` | Optional exact value `runtime` or `mantle`. Native model routing is used when omitted. |
| `lifecycle` | Idle timeout and maximum compute lifetime in seconds. |
| `s3Files` | Storage stack name, mount path, and read-only choice. |
| `vpc` | Optional external VPC bindings for profiles without managed S3 Files storage. |
| `workingDirectory` | Optional absolute path. For S3 profiles, it must remain inside the dedicated mount. |
| `environment` | Additional string settings; derived settings cannot be overridden here. |
| `tags` | Optional explicit tags. No application tags are added automatically. |

Each image definition declares its Dockerfile, build arguments, and command.
It does not declare a Herdr recognition kind.
Model configuration, tool installation, and health reporting are runtime responsibilities.

## External storage bindings

Fill `.env` beside this README using `.sample.env` as the template:

```dotenv
S3_BUCKET_NAME=example-agent-workspaces
VPC_SUBNET_IDS=<first-subnet-id>,<second-subnet-id>
VPC_SECURITY_GROUP_IDS=<security-group-id>
```

Replace the placeholders with existing resources for a real deployment.
The component `.env` is the only source for these deployment bindings.
Do not add an access-point ARN, root prefix, POSIX settings, or storage stack name to `.env`.
The profile selects the storage stack. CDK creates the access point.

The storage stack uses the bucket root and external networking.
Each S3-backed profile owns one access point rooted at `/agent-filesystem/profiles/<profile-name>`.
The runtime mounts and starts directly at `/mnt/workspace` in the sample.
UID/GID are 1000:1000 and directory mode is 755.
No second profile directory is created under the mount.

Worker roles are scoped to their generated access point and have no direct S3 bucket grants.
Networking, subnets, security groups, and the backing bucket remain externally owned.
The operator-owned network deployment source and settings are ignored under `.local/deployments/`.
See [storage mapping](../../docs/STORAGE_MAPPING.md).

## Build and deploy

Run from the repository root:

```bash
uv sync --frozen
npm ci --prefix src/agentcore_runtime/cdk
npm --prefix src/agentcore_runtime/cdk run cdk -- synth \
  -c runtimeProfile=opencode-agentcore-profile-2
npm --prefix src/agentcore_runtime/cdk run cdk -- diff \
  -c runtimeProfile=opencode-agentcore-profile-2
```

Review the diff before deployment. Use official CDK commands, a configured AWS credential chain, and an ARM64-capable Docker builder.
The target account/region needs the standard CDK bootstrap resources.

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy \
  -c runtimeProfile=opencode-agentcore-profile-2 \
  --outputs-file "$PWD/.local/deployments/opencode-agentcore-profile-2.json"
```

For the S3 profile, deploy both selected stacks with `--all` if CDK requests a stack selection.
Deployment does not update connector profiles or change account retention settings.
Synthesize from the current checkout before deploying a change.

## Connection output

The stack exports `RuntimeArn`, `RuntimeId`, and `ConnectionDescriptor`.
The descriptor contains only ARN, explicit launch argv, and an optional endpoint inside its versioned envelope.
CDK ARN tokens resolve during deployment. The consumer derives the region from the resolved ARN.
Local recognition hints, host credential selection, and profile labels belong to the connector.

The producer in `cdk/connection.ts` is implemented locally.
Its output is checked against the schema and fixtures pinned under `contracts/1.0.0/` at the repository root.
`CONTRACT_VERSION` selects the exact SemVer directory used by the producer's exporter and tests.
The runtime does not load a plugin package or import a sibling repository during synthesis or execution.

## Runtime behavior and limits

The samples use a 900-second idle timeout and 28,800-second maximum compute lifetime.
These are platform lifecycle settings, not a timer based only on keyboard input.
WebSocket traffic and work-health reports can affect idle accounting.

OpenCode reports tracked work through short-lived, PID-validated health leases.
Question and permission waits are idle only when no other tracked work remains.
Codex currently supplies readiness health; it does not have the same work reporter.
No advancing `time_of_last_update` is sent to AWS.

The PUBLIC profiles start in `/home/agent`; the S3 profile starts in `/mnt/workspace`.
Only mounted files persist across compute replacement. Default home and conversation state remain ephemeral.
Do not point multiple runtimes at a shared live conversation database without a separate persistence design.

Native AWS role providers handle model credentials. The launcher does not export credential snapshots.
Execution roles permit both Bedrock Runtime and Mantle inference, independently of startup routing.
The image keeps OpenCode auto-update disabled.
Changing model providers in a saved conversation can expose provider-specific history limitations.

## Development tools and MCP

The images include pinned Python, Node.js, uv/uvx, pnpm, Go, Rust, Git, GitHub CLI, AWS CLI, and common build tools.
Exact versions and checksums are in each image definition.
Caches and disposable tool environments use `/tmp/agentcore`.
Persistent MCP source and lockfiles can live in `/mnt/workspace/tools/`.
Native MCP registrations belong in `/mnt/workspace/opencode.json`.
The optional `agentcore-mcp` command rebuilds a locked Python tool project into local runtime storage.
No specific MCP server or GitHub credential broker is installed by default.

## Validation

```bash
uv run --frozen ruff check src scripts
uv run --frozen ruff format --check src scripts
uv run --frozen pytest -q --tb=short
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
uv run --frozen python scripts/check_repository.py
uv run --frozen python scripts/repository_privacy.py
```

Build an image after changing image behavior:

```bash
uv run --frozen python src/agentcore_runtime/tests/build_runtime_image.py \
  opencode --tag agentcore-tools:opencode
uv run --frozen python src/agentcore_runtime/tests/build_runtime_image.py \
  codex --tag agentcore-tools:codex
```

Set `HERDR_RUNTIME_TEST_IMAGE` and `CODEX_RUNTIME_TEST_IMAGE` to those tags to enable the corresponding container checks.
The Docker context uses the repository root and includes root LICENSE and NOTICE.
CDK excludes deployment inputs, credentials, tests, and unrelated image adapters from its assets.

## Live probes

Live probes require explicit authorization. They create disposable sessions and stop only those sessions.
The ARN parser used by probes is local to this repository.

| Probe | Purpose |
| --- | --- |
| `tests/live_runtime_tools.py` | Development tools, native CLI commands, and generic MCP reconstruction. |
| `tests/live_runtime_activity.py` | OpenCode busy/wait/idle and process-death health behavior. |
| `tests/live_codex_sandbox.py` | Native sandbox restrictions and a model-driven command. |
| `tests/live_profile_storage.py` | Empty-root mount and cross-session file persistence. |

Do not run the empty-root storage probe against a workspace that contains user data.
Use each probe's `--help` for required parameters.
Herdr end-to-end attachment tests remain in the independent plugin repository.

See [the repository guide](../../README.md), [design](../../docs/DESIGN.md), and [requirements](../../docs/REQUIREMENTS.md).
