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

`opencode` and `codex` are named example settings under the runtime project's `profiles/` directory.
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

3. Import the runtime owner's descriptor:

   ```bash
   .venv/bin/herdr-agentcore configure \
     --connection-file "$HOME/.config/agentcore/opencode.connection.json" \
     --profile opencode-agentcore-runtime \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

4. Select it as the default:

   ```bash
   .venv/bin/herdr-agentcore set-default opencode-agentcore-runtime \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

5. Open an agent:

   ```bash
   herdr plugin action invoke agentcore.new
   ```

You can also configure an ARN directly:

```bash
.venv/bin/herdr-agentcore configure \
  --runtime-arn "$RUNTIME_ARN" --agent-kind opencode \
  --profile opencode-agentcore-runtime \
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
npm ci --prefix src/agentcore_runtime
npm --prefix src/agentcore_runtime run cdk -- deploy HerdrOpenCodeRuntime \
  -c runtimeProfile=opencode -c region=eu-west-1 \
  --outputs-file "$HOME/.config/agentcore/cdk-outputs-opencode.json"
```

This command needs a local Docker engine, Buildx/ARM64 support, and AWS deployment permissions.
Use `cdk synth` to inspect templates and `cdk diff` to review changes before deployment.
The target account/region needs CDK bootstrap resources. Follow the [runtime README](src/agentcore_runtime/README.md) for the full OpenCode and Codex procedures.
Import the output with `herdr-agentcore configure --cdk-outputs PATH --stack HerdrOpenCodeRuntime` plus the local profile/config options.

## Select, attach, detach, and stop

New-agent selection uses explicit `--profile`, then `HERDR_AGENTCORE_PROFILE`, then saved `default_profile`.
The first saved profile becomes default. Later saves preserve it.
Invalid or ambiguous selection fails without a picker.
Existing connections retain their target and launch settings.

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

The supplied `opencode` profile declares `["/app/run.sh"]` as its current command.
CDK accepts a replacement through `-c 'command=["/custom/start"]'`.
The connector can also override a valid descriptor's command explicitly.
See [command selection](src/agentcore_runtime/README.md#launch-command-selection) for examples and limits.

Deployment uses the official `cdk deploy` command; there is no custom runtime provisioning executable.
The connector imports the resolved CDK output or an explicit connection descriptor.
See the [contract README](src/runtime_contract/README.md) for fields and version rules.

## Status and limits

Version `0.1.0` is experimental.
The selected `opencode` settings were deployed through AWS CDK. The runtime and default endpoint reached READY.
The updated connector imported CDK outputs and passed fresh cloud model, activity, attachment, and conversation-continuity tests.
The previous custom-provisioned runtime and its owned stacks were removed. Its ECR images remain under their retention policy.
Both shared-image examples passed cloud E2E tests on disposable runtimes: real model calls, Herdr recognition, detach/attachment, conversation continuity, and stop requests.
OpenCode also passed cloud work/question/reply health tests. Codex still has no runtime work-event reporter, and sandbox/tool execution remains unverified.
The temporary stacks were removed. These tests did not replace the existing default deployment.
After that qualification, both shared-image profiles were deployed as persistent CDK stacks and passed fresh E2E checks.
Herdr uses the committed connector with `opencode-agentcore-runtime` and `codex-agentcore-runtime`; OpenCode remains the default.
Earlier cloud tests used Herdr 0.9.5, OpenCode 1.18.30, and AgentCore SDK 1.24.1.
They verified deployment/update, role-based Bedrock calls, default selection, attachment, conversation continuity, and activity health.

The current OpenCode definition uses ephemeral coding state, a 900-second idle timeout, and a 28,800-second compute maximum.
Real work produces `HealthyBusy`. An unanswered question can be idle when no other tracked work runs.
Health reporting does not extend the maximum lifetime or preserve files.
Full-duration expiry and credential-rollover tests remain pending.

OpenCode 1.18.30/Bun 1.3.14 crashed at 35×20 in a controlled probe.
Larger/zoomed panes are a workaround; the complete safe-size boundary is unknown.
Ctrl+Z can suspend OpenCode. A live connector and screen-derived idle badge do not prove process health.

S3 Files persistence, automatic resume, multiple helper shells, EC2 management deployment, and host recovery remain planned.
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
Keep credentials, actual deployment identifiers, populated descriptors, records, and transcripts outside the repository.

```bash
uv sync --frozen
uv run --frozen ruff check src
uv run --frozen ruff format --check src
uv run --frozen pytest -q --tb=short
uv run --frozen python src/herdr_plugin/tests/repository_privacy.py
uv build --all-packages
npm run check --prefix src/agentcore_runtime
npm test --prefix src/agentcore_runtime
```

Default tests make no AWS calls. Live probes require a selected runtime and authorization.
The privacy guard checks working files, the index, and history without printing matched values.
