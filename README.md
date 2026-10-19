# Herdr → AgentCore

## Goal

Connect Herdr to interactive assistants in Amazon Bedrock AgentCore Runtime.
Keep terminal connection logic separate from assistant definitions and deployment.
Herdr owns workspaces, tabs, panes, and live-agent identity.
The connector uses AWS Identity and Access Management (IAM), not a separate end-user platform.

## Three components

```text
src/
  agentcore_runtime/   Runtime definitions, deployment tools, and tests
  herdr_plugin/        Herdr connector and tests
  runtime_contract/    Shared connection data and validation
```

| Component | Purpose | Package |
| --- | --- | --- |
| [Runtime infrastructure](src/agentcore_runtime/README.md) | Use AWS CDK to deploy the selected named runtime settings. | Private CDK project |
| [Herdr connector](src/herdr_plugin/README.md) | Connect terminals and manage saved sessions against existing runtimes. | `herdr-agentcore` |
| [Connection contract](src/runtime_contract/README.md) | Validate ARN, endpoint, launch arguments, and agent recognition hint. | `agentcore-contract` |

The CDK project and connector use the shared contract. Neither imports the other's implementation.
Each folder has its own README and tests. The connector and contract are Python packages; infrastructure uses npm/CDK.
The root is a Python workspace for those two packages. The Herdr manifest remains at the root.

Agent image sources live in `src/agentcore_runtime/agent_images/`.
Deployment inputs live in `provision_profiles/`; CDK code and npm configuration live in `cdk/`.
The three provision profiles are:

| Profile | Startup model | Network |
| --- | --- | --- |
| `codex-agentcore-profile-1` | GPT-5.6 Sol through Codex | PUBLIC |
| `opencode-agentcore-profile-2` | Kimi K3 through OpenCode | PUBLIC |
| `opencode-s3filesystem-agentcore-profile-3` | Kimi K3 through OpenCode | VPC and S3 Files |

Each profile references one shared image definition rather than repeating build and startup settings.
Deployment bindings are read from ignored `src/agentcore_runtime/.env`; the adjacent `.sample.env` is the tracked template.
See the [AgentCore Runtime README](src/agentcore_runtime/README.md#step-3-select-a-sample-profile) for all three samples, their setup, and deployment commands.
These names point to configuration; they are not hardcoded assistant types in the connector.
Add other profiles without changing terminal transport. A profile's Herdr recognition hint can differ from its name.
The examples share image build, startup, and health code. Their adapters and genuine capability differences are described in the [runtime comparison](src/agentcore_runtime/README.md#opencode-and-codex-comparison).
A runtime ARN identifies the target, but does not prove it has an interactive assistant.
The runtime must provide a valid launch command and meet AgentCore's service requirements.
It does not need Herdr installed inside it.

## Connect to a provisioned runtime

Use macOS or Linux, Python 3.11+, uv, and Herdr 0.9.5+.
Authorize the management host for the selected runtime.
Docker and deployment permissions are not needed to use an existing runtime.
For prerequisites, registration, verification, and troubleshooting, follow the [existing-runtime guide](docs/CONNECT_EXISTING_RUNTIME.md).

1. Install the connector:

   ```bash
   uv sync --frozen --no-dev
   ```

2. Link the plugin:

   ```bash
   herdr plugin link "$PWD"
   ```

3. Import the current OpenCode deployment outputs:

   ```bash
   .venv/bin/herdr-agentcore configure \
     --cdk-outputs .local/deployments/opencode-agentcore-profile-2.json \
     --stack HerdrOpenCodeRuntime \
     --profile opencode-agentcore-profile-2 \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

4. Select it as the default:

   ```bash
   .venv/bin/herdr-agentcore set-default opencode-agentcore-profile-2 \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

5. Open an agent:

   ```bash
   herdr plugin action invoke agentcore.new
   ```

If a runtime owner supplies a standalone descriptor, use `--connection-file PATH` instead of `--cdk-outputs` and `--stack`.
CDK writes its standard outputs document; it does not create a separate `.connection.json` file.
You can also configure an ARN directly:

```bash
.venv/bin/herdr-agentcore configure \
  --runtime-arn "$RUNTIME_ARN" --agent-kind opencode \
  --runtime-profile opencode-agentcore-profile-2 \
  --profile opencode-agentcore-profile-2 \
  --config-dir "$(herdr plugin config-dir agentcore)" \
  --command /app/run.sh
```

Set `RUNTIME_ARN` to a deployed runtime ARN. Put `--command` last.
Use `--aws-profile` only to select host-local credentials. Omit it for the normal AWS credential chain.
Add `--replace` to replace an existing profile.
For an ordinary terminal, omit `--agent-kind` during ARN registration or use `--agent-kind terminal`.
A recognition hint requires support for that assistant in Herdr; it does not add support by itself.

## Deploy a named runtime profile with AWS CDK

The runtime component contains CDK constructs, named settings, and Docker contexts.
AWS CDK builds/publishes assets and deploys CloudFormation. The stack exports a connection descriptor without writing Herdr configuration.

```bash
npm ci --prefix src/agentcore_runtime/cdk
npm --prefix src/agentcore_runtime/cdk run cdk -- synth \
  -c runtimeProfile=opencode-agentcore-profile-2
```

This command needs a local Docker engine, Buildx/ARM64 support, and AWS deployment permissions.
Use `cdk synth` to inspect templates and `cdk diff` to review changes before deployment.
The target account/region needs CDK bootstrap resources. Follow the [runtime README](src/agentcore_runtime/README.md) to fill resource bindings, review, deploy, and register each project.
All Runtime regions are `eu-west-1`. Only the filesystem example needs `src/agentcore_runtime/.env` for subnet, security-group, and access-point bindings.
CDK resolves the account through the authenticated Toolkit. The filesystem sample uses access-point permissions without a bucket/prefix input or metadata lookup.
The selected profile and component `.env` control deployment settings. Per-field CDK context overrides and ambient shell binding overrides are rejected or ignored, respectively.
For the S3 example, copy `src/agentcore_runtime/.sample.env` to `src/agentcore_runtime/.env` if needed and fill its bindings. External profile directories are not supported.
All three samples use `inference.bedrock-endpoint-type: "runtime"`.
CDK uses this field for inference IAM and native client selection. Both startup models use global cross-Region inference from Ireland.
Earlier Sol requests were rejected by zero-retention policy. The user later authorized an Ireland-only guard exception and set Runtime retention there to `default`. Profile deployment itself does not change retention settings.
Import each stack's output with `herdr-agentcore configure --cdk-outputs PATH --stack STACK_NAME` plus local connection options.

## Select, attach, detach, and stop

New-agent selection uses explicit `--profile`, then `HERDR_AGENTCORE_PROFILE`, then saved `default_profile`.
The first saved profile becomes default. Later saves preserve it.
Invalid or ambiguous selection fails without a picker.
Existing connections retain their target and launch settings.
Importing the numbered profiles does not retarget an older saved default or existing connection records.
Use an explicit profile for launch, or select a verified current default with `set-default`.

| Command | Purpose |
| --- | --- |
| `.venv/bin/herdr-agentcore action new --profile NAME` | Override the profile for one new agent. |
| `herdr plugin action invoke agentcore.attach` | Reattach an original live terminal. |
| `herdr plugin action invoke agentcore.sessions` | Show last-known records. |
| `herdr plugin action invoke agentcore.stop` | Confirm a whole-runtime-session stop request. |

Detach with Ctrl+] followed by `d`.
Attachment preserves the original runtime session, shell, process, and conversation while they survive.
It does not replay the launch or uncertain input.
Stop affects the whole runtime session. The local `stopped` label records acceptance, not confirmed completion.

## Explicit launch contract

Profiles have not been released as a public versioned API. Internal version fields are not a backward-compatibility promise.
Every connection must contain explicit launch argv. Missing `command` fails validation.
The connector does not supply `/app/run.sh` or infer OpenCode from the command or ARN.
Missing `agent_kind` selects an ordinary terminal.

The selected image definitions declare `["/app/run.sh"]` as their current command. A provision profile can override it explicitly.
Set `command: ["/custom/start"]` in the selected provision profile to replace the image's default argv.
The connector can also override a valid descriptor's command explicitly.
See [command selection](src/agentcore_runtime/README.md#launch-command-selection) for examples and limits.

Deployment uses the official `cdk deploy` command; there is no custom runtime provisioning executable.
The connector imports the resolved CDK output or an explicit connection descriptor.
See the [contract README](src/runtime_contract/README.md) for fields and version rules.

## Status and limits

The latest verification was on 2026-10-19.
The three numbered profiles were deployed in `eu-west-1` and READY. Codex Runtime/DEFAULT was version 4; both OpenCode runtimes were version 1.
These are AWS runtime versions, not assistant package or descriptor versions.
Codex with GPT-5.6 Sol passed native Bedrock Runtime inference, sandbox checks, attachment, a context-preserving follow-up, and a real shell-tool call. Ireland Runtime retention is `default`.
Both OpenCode profiles passed real Kimi model calls.
The filesystem permission issue is fixed using AWS's documented directory-marker metadata procedure. Separate sessions wrote and read 4 KiB and 8 MiB files successfully.
All three profiles passed a later CDK deploy check with no changes. Two fresh interactive sessions per profile passed real date and folder-access checks.
See the [latest all-profile verification](src/agentcore_runtime/README.md#all-profiles-and-six-interactive-sessions--2026-10-19) and [Codex deployment results](src/agentcore_runtime/README.md#sol-on-native-bedrock-runtime--2026-10-19) for details.

Version `0.1.0` is experimental. Images pin OpenCode 1.18.30 and Codex 0.163.0; the connector pins AgentCore SDK 1.24.1.
Herdr 0.9.5 validated all three profiles. Their descriptors were imported under their numbered profile names.
Six user-requested sessions were left open after the latest checks. They remain subject to the runtime lifecycle limits; discover live state before further operations.
The older custom-managed and pre-numbered deployments were retired. Their output files and test results are historical records.

All profiles use a 900-second idle timeout and a 28,800-second compute maximum.
The PUBLIC profiles use ephemeral coding files. The filesystem profile mounts shared coding files at `/mnt/workspace`; its home and conversation state remain ephemeral.
OpenCode's tracked work produces `HealthyBusy`. An unanswered question can be idle when no other tracked work runs.
Earlier cloud activity tests and current local image tests cover that bridge. Codex has readiness health only; its work-event reporter is not implemented.
Health reporting does not extend the maximum lifetime or preserve files.
Full-duration expiry and credential-rollover tests remain pending.

OpenCode 1.18.30/Bun 1.3.14 crashed at 35×20 in a controlled probe.
Larger/zoomed panes are a workaround; the complete safe-size boundary is unknown.
Ctrl+Z can suspend OpenCode. A live connector and screen-derived idle badge do not prove process health.

S3 Files mount readiness, the mounted working directory, and cross-session file persistence passed on the filesystem profile.
Per-binding storage paths, persistent home/configuration, skill discovery, and conversation checkpoints remain planned or unqualified.
Automatic resume, multiple helper shells, EC2 management deployment, and host recovery remain planned.
The hosting target is **EC2 management/coordination → AgentCore workers**, with the laptop used for access and viewing.
Standard SSM access and native Herdr SSH access are separate options. Neither changes connector authentication.

## Documentation and checks

- [Requirements](docs/REQUIREMENTS.md): scope and acceptance criteria.
- [Connect an existing runtime](docs/CONNECT_EXISTING_RUNTIME.md): step-by-step setup and verification.
- [Design](docs/DESIGN.md): architecture, glossary, and validation evidence.
- [Session proposal](docs/SESSION_MANAGEMENT_PROPOSAL.md): hosting, identity, and durable recovery.
- [Plugin review](docs/PLUGIN_GUIDELINES_REVIEW.md): Herdr's public extension contract.
- [Agent instructions](agent.md): repository conventions and ASD-STE100-style writing rules.

All project documentation follows those style rules. Legal notices retain their original wording.
Keep credentials, records, and transcripts out of Git. Keep local deployment bindings in ignored `src/agentcore_runtime/.env` and generated descriptors under ignored `.local/`.

```bash
uv sync --frozen
uv run --frozen ruff check src
uv run --frozen ruff format --check src
uv run --frozen pytest -q --tb=short
uv run --frozen python src/herdr_plugin/tests/repository_privacy.py
uv build --all-packages
uv run --frozen python src/runtime_contract/tests/check_distributions.py --dist dist
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
```

Default tests make no AWS calls. Live probes require a selected runtime and authorization.
The privacy guard checks working files, the index, and history without printing matched values.
