# Herdr → AgentCore

## Goal

A community Herdr plugin for provisioning, managing, viewing, and interacting with **OpenCode agents running inside Amazon Bedrock AgentCore Runtime**. This repository contains both the runtime container/provisioning code and the Herdr connector.

Herdr owns workspaces, tabs, panes, agent identities, and orchestration. The plugin connects those primitives to remote execution. AWS access uses the management host's credential chain or IAM role; there is no Cognito login or separate end-user platform.

## Current status

**Experimental prototype — version 0.1.0.**

| Capability | Status |
| --- | --- |
| Configure an existing runtime; start independent cloud agents | Implemented and live-tested |
| Build OpenCode image, provision ECR/IAM/AgentCore, and save a connector profile | Deployed and live-tested, including image update, role-based Bedrock calls, and reattachment |
| Terminal input/output, resize, detach, and same-PTY reattachment | Implemented and live-tested |
| Herdr agent recognition, prompt/read/wait, and explicit session stop | Implemented and live-tested |
| Five concurrent agents fetching and translating separate news feeds | Live-tested, including follow-up prompts and cleanup |
| Refreshable runtime-role credentials with the sample launcher | Opt-in; fresh model turns and reattachment live-tested; full credential rollover pending |
| Resume a saved conversation after restarting OpenCode in surviving compute | Manually verified; automated resume action is planned |
| Agent status | Screen-derived today; remote OpenCode hook/event bridge is planned |
| Activity-aware AgentCore health | Deployed and cloud-tested: work, question wait, reply, completion, and process death |
| S3 Files-backed repositories, configuration, skills, and OpenCode history | Required by the design; persistent-home integration is not implemented |
| Recovery after compute expiry, automatic manager restart recovery, additional helper shells | Planned |
| Always-on EC2 management deployment | Designed; not deployed or validated by this project |

The live baseline used Herdr **0.9.5**, OpenCode **1.18.30**, and the locked AgentCore SDK **1.24.1**. Validation details and limitations are in [DESIGN.md](DESIGN.md).

## Run a local checkout

Requirements: macOS or Linux, Herdr 0.9.5+, Python 3.11+, uv, and authorized management-host AWS access. Provisioning additionally needs a local Docker engine with Buildx and ARM64 build support. You can provision the included runtime or connect to an existing one.

### Provision the included runtime

The deployment creates an ECR repository, an AgentCore execution role, and an IAM-authenticated runtime. The image installs pinned OpenCode **1.18.30** with runtime self-updates disabled. Bedrock access uses the **runtime execution role** through the SDK credential provider chain: no API key, manual metadata fetch, or exported access-key/session-token snapshot.

```bash
uv sync --frozen
herdr plugin link "$PWD"
uv run herdr-agentcore provision \
  --name opencode --region us-west-2 \
  --model-id anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --profile owned-runtime \
  --config-dir "$(herdr plugin config-dir agentcore)"
herdr plugin action invoke agentcore.new
```

Select `owned-runtime` in the new-agent menu. Choose a model available to your AWS account/region; `--model-id` also accepts geographic system inference-profile IDs. The deployment identity needs CloudFormation, ECR, IAM/PassRole, and AgentCore provisioning permissions. Use `--aws-profile` to select that management-host identity.

Add `--plan` to print the two CloudFormation templates without contacting AWS or Docker. To update this deployment and its saved profile, rerun with `--update --replace`; `--opencode-version` selects another pinned release. Updates require new OpenCode processes to use the new image/configuration. See [provisioning design](DESIGN.md#repository-owned-runtime-and-provisioning) for stack ownership, failure recovery, and cleanup.

The included deployment is a public-network runtime with local, ephemeral coding state. VPC/S3 Files persistence and automatic conversation recovery remain planned. It works without the original sample's gateway, shared infrastructure files, or research checkout.

### Connect to an existing runtime

From the repository root in a Herdr shell pane:

```bash
uv sync --frozen
herdr plugin link "$PWD"
herdr plugin action invoke agentcore.setup
herdr plugin action invoke agentcore.new
```

Setup asks for **your own** runtime ARN, optional management-host AWS profile, endpoint, and whether to enable the legacy sample's credential wrapper. No deployment-specific values are bundled. The default remote launcher is `/app/run.sh`, supported by both the included image and the original AWS sample.

| Action | Purpose |
| --- | --- |
| `herdr plugin action invoke agentcore.new` | Select a profile and start a new cloud agent |
| `herdr plugin action invoke agentcore.attach` | Reattach an existing live remote terminal |
| `herdr plugin action invoke agentcore.sessions` | Inspect saved, last-known session records |
| `herdr plugin action invoke agentcore.stop` | Confirm and stop a detached runtime session |

**Detach:** hold Ctrl and press `]`, release both, then press `d`. Detach leaves remote work subject to AgentCore lifecycle limits. Stop is a separate operation. After the runtime's compute has ended, conversation/workspace reconstruction is not yet supported.

## Resuming an online agent

If the agent's pane is still open and responsive, continue there. After detaching, reopen its terminal with:

```bash
herdr plugin action invoke agentcore.attach
```

Select the saved connection. While its original remote PTY and OpenCode process survive, this reuses the **same runtime session, shell, process, and conversation**. It does not launch another OpenCode instance. A model turn and a context-aware follow-up after reattachment have been live-tested.

| State | Resume path |
| --- | --- |
| Detached, original terminal still alive | Use `agentcore.attach`. |
| OpenCode failed or has expired model credentials, but runtime compute survives | Requires explicit process/conversation recovery; reattaching alone does not repair the process. |
| Runtime compute stopped or expired | Automated recovery is not implemented. S3 Files-backed coding-state persistence is still required. |

**Manual conversation recovery was verified on surviving compute.** We identified the exact OpenCode session, backed up its database, detached the connector, confirmed and stopped the old OpenCode process, then opened a replacement shell in the same runtime session. Launching OpenCode with `--session <saved-conversation-id>` under the same home/working directory and an expiration-aware credential provider restored the conversation. The private connection binding was updated to the new shell, and a new model turn succeeded.

That is an operator-assisted recovery sequence, not a supported `resume` command. It requires checking the actual remote process and saved state before replacement; it preserves saved conversation/files, not in-flight tool execution. Old error messages remain in chat history. See [resume semantics](DESIGN.md#resume-semantics--target) and the [credential recovery findings](DESIGN.md#runtime-credential-expiry-and-conversation-recovery--2026-10-16).

## Runtime-role credentials

**The included image uses the execution role automatically.** Its `/app/run.sh` starts OpenCode with `AWS_PROFILE=default`, enabling the expiration-aware Node provider chain. The image contains no credential files and does not fetch or export temporary credentials. Its runtime-owned OpenCode configuration is separate from user configuration, which startup preserves. The compatibility flag below is only needed for older external sample images.

The upstream sample launcher exports a one-time copy of temporary AWS credentials. After those expire, OpenCode can report `The security token included in the request is expired` even while the terminal is connected and management-host AWS access works. Laptop sleep can expose this elapsed-time issue; reattaching does not refresh the remote process environment.

For a runtime whose default AWS credential chain resolves its execution role, enable **refreshable runtime-role credentials** during setup, or configure a profile with:

```bash
uv run herdr-agentcore configure \
  --config-dir "$(herdr plugin config-dir agentcore)" \
  --profile default --runtime-arn "$RUNTIME_ARN" --runtime-role-credentials
```

Supply your runtime ARN through `RUNTIME_ARN`; add `--replace` to update an existing profile. The opt-in wrapper preserves sample initialization, clears its static credential snapshot immediately before OpenCode starts, and sets runtime `AWS_PROFILE=default` to enable OpenCode's refreshable Node provider chain. Management-host authentication is unchanged. Profile updates affect **new connections only**.

The wrapper requires a launcher that resolves `opencode` through `PATH`. Absolute-binary launchers and Bedrock API-key configurations need runtime-specific setup. Fresh model calls, the credential-free process environment, and detach/reattach passed live validation; rollover across a full credential lifetime remains untested.

## Runtime lifecycle

The owned deployment's current settings were verified through the AgentCore control API:

| Setting or operation | Current behavior |
| --- | --- |
| Idle timeout | **15 minutes** (`900` seconds) of platform-determined inactivity triggers termination. |
| Maximum compute lifetime | **8 hours** (`28,800` seconds) from compute creation; activity and reattachment do not reset this limit. |
| Detach | Disconnects the terminal without requesting compute termination; lifecycle limits still apply. |
| Stop | Terminates that runtime session's compute and processes. The deployment remains available for new sessions. |
| Storage and recovery | Coding files and chat history are ephemeral. Warm reattachment works while the original process survives; automatic recovery after compute termination is not implemented. |

These timers apply independently to each session's compute, not to the deployed runtime as a whole. Local connector records survive, but they cannot restore an expired runtime's files or conversation.

**Activity-aware health is deployed and cloud-tested.** An OpenCode event plugin reports busy/retrying sessions as `HealthyBusy`. Finished turns and sessions waiting on permission/question dialogs are idle; `/ping` returns `Healthy` when no other tracked session is active. Fresh process-bound leases prevent a crashed or suspended process from keeping the runtime busy indefinitely. Merely leaving OpenCode at its prompt does not prevent idle cleanup.

For example, **16 minutes of work followed by an unanswered question** becomes idle at minute 16 and is eligible for the 15-minute idle timeout around minute **31**, assuming no other work is active. The 8-hour maximum still applies. New sessions use the updated image; existing sessions do not hot-reload it. Actual cloud state transitions were verified with a Bedrock question/reply turn; persistent storage, recovery, and a full-duration AWS idle-expiry test remain pending. See [lifecycle details](DESIGN.md#deployed-session-lifecycle).

## Known terminal limitations

- OpenCode 1.18.30/Bun 1.3.14 crashed at **35×20** in a controlled test before mouse input. **80×20** and **35×40** passed that probe. Use adequately sized or zoomed panes; the complete safe-size boundary is unknown.
- Ctrl+Z can suspend remote OpenCode. This launcher leaves no parent shell for `fg`; suspension recovery is not yet a plugin action. Use the detach sequence above instead.
- A connected Python wrapper can outlast a failed or suspended TUI, making a screen-derived idle badge misleading. Hook-based status plus process-liveness reporting remains a priority.

## Unattended cloud management

```text
Laptop Herdr client → SSH → EC2 Herdr server + plugin → AgentCore sessions → OpenCode
```

The proposed EC2 host runs the connectors and coordination independently of the laptop. Install the plugin and configure AWS access on that host. Management-host recovery and AgentCore compute recovery are separate design concerns.

## Private configuration

Herdr stores configuration and connection records outside this checkout in its plugin config/state directories. Locate configuration with `herdr plugin config-dir agentcore`.

Do not commit AWS credentials, personal account/resource identifiers, populated runtime configuration, generated session records, or raw test transcripts. Local deployment/configuration files, credential files, logs, and build artifacts are ignored. Test fixtures use fictional example account IDs only.

## Project files and checks

- [REQUIREMENTS.md](REQUIREMENTS.md): scope and acceptance criteria.
- [DESIGN.md](DESIGN.md): architecture, diagrams, and validation findings.
- [agent.md](agent.md): instructions and context for follow-up coding agents.
- `src/herdr_agentcore/`: implementation; `src/tests/`: offline tests and opt-in live probes.
- `src/herdr_agentcore/runtime_image/`: tracked Dockerfile, launcher, OpenCode configuration, and HTTP health endpoint, adapted from the AWS sample with attribution.
- `src/herdr_agentcore/provision.py`: CloudFormation definitions, ARM64 image build/push, runtime creation/update, and connector-profile registration.
- `herdr-plugin.toml`: community plugin manifest; `pyproject.toml` and `uv.lock`: packaging/dependencies.

```bash
uv run ruff check src
uv run ruff format --check src
uv run pytest
uv run python src/tests/repository_privacy.py
uv build
```

The privacy guard checks the working files, Git index, and history for private configuration filenames, credential patterns, and deployment identifiers without printing matched values. Live probes require an explicitly supplied runtime ARN and are excluded from default pytest execution.
