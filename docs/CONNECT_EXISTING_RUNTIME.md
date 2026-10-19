# Connect an existing AgentCore runtime to Herdr

## Goal

Register a deployed runtime with the Herdr connector and open its interactive assistant.
This procedure does not provision or update the runtime.
The `new` action creates a new runtime session under the existing deployment.
To reconnect to an existing process, use its saved connection record and `attach` instead.

## Before you start

Obtain these details from the runtime owner:

| Detail | What to confirm |
| --- | --- |
| Runtime ARN | Use the deployed runtime ARN, not an endpoint ARN or an invocation URL. |
| Endpoint | Use `DEFAULT` unless the owner supplies another qualifier. |
| Shell access | The deployment must accept AgentCore Shell connections from the management identity. |
| Launch command | Obtain the exact executable and arguments for the installed interactive assistant. |
| Runtime profile reference | Obtain the provision profile reference, if available, such as `opencode-agentcore-profile-2`. It is not a connector enum. |
| Herdr recognition hint | Read `agent_kind` from those settings. This hint identifies a Herdr-supported interface; it is separate from the profile name. |
| Worker access | The runtime must already have model/tool credentials, dependencies, and required network access. |

The management identity needs permission to invoke the runtime's Shell API.
It also needs `StopRuntimeSession` permission if you use the stop action.
Use your normal AWS credential chain or an explicitly selected host AWS profile.
The runtime execution role supplies worker model/tool access; it is a separate identity.

A provision profile points to image, command, model, and environment settings.
The repository supplies `codex-agentcore-profile-1`, `opencode-agentcore-profile-2`, and `opencode-s3filesystem-agentcore-profile-3`. You can add other named profiles.
All three use Bedrock Runtime in `eu-west-1`. Codex selects GPT-5.6 Sol; both OpenCode profiles select Kimi K3.
The filesystem profile starts at `/mnt/workspace`. The PUBLIC profiles start at `/home/agent`.
The Herdr connection profile created below is a local ARN binding, not the runtime settings file.
The connector uses resolved fields from the owner or deployment outputs; it does not guess them from a profile name.

An existing runtime with an interactive assistant and a valid launcher normally needs no source change for terminal access.
A runtime with only an HTTP agent API needs a terminal adapter before this connector can present it as an assistant.
Installing the connector does not install an assistant inside the runtime.

## Step 1: use the management host

Run the commands on the host that runs the Herdr server.
Use a shell pane in that Herdr session and open this repository's root directory.
For an EC2-hosted server, install and configure the plugin on EC2, not only on the viewing laptop.

Required tools are Herdr 0.9.5+, Python 3.11+, and uv on macOS or Linux.
Docker and AWS deployment permissions are not required for this procedure.

## Step 2: install and link the connector

Install the connector and its dependencies:

```bash
uv sync --frozen --no-dev
```

Link the repository to Herdr:

```bash
herdr plugin link "$PWD"
```

Record the plugin configuration directory:

```bash
HERDR_CONFIG_DIR="$(herdr plugin config-dir agentcore)"
CONNECTION_NAME="existing-opencode"
```

The connection name is a local profile label. It is not an AWS credential profile or a runtime name.

## Step 3: confirm host authentication

If the AWS CLI is installed, check the default host identity:

```bash
aws sts get-caller-identity
```

For a named host profile, use:

```bash
aws sts get-caller-identity --profile host-access
```

Refresh that profile's SSO login first if required by your organization.
An STS success verifies the identity, not its permission to invoke this runtime.
If you select a named profile, add `--aws-profile host-access` when registering the connector profile below.
Do not copy worker credentials into Herdr configuration.

## Step 4: choose a registration method

Use **method A** if the owner gives you an ARN and launch command.
Use **method B** if the owner gives you a connection descriptor.
Use **method C** for this repository's standard CDK deployment outputs.
All three methods store the same explicit connection fields. Registration makes no AWS calls and starts no remote process.

### Method A: register the ARN and command

Set the ARN supplied by the owner:

```bash
RUNTIME_ARN='<your-runtime-arn>'
```

For an OpenCode runtime that provides `/app/run.sh`, register it explicitly:

```bash
.venv/bin/herdr-agentcore configure \
  --runtime-arn "$RUNTIME_ARN" \
  --endpoint DEFAULT \
  --runtime-profile opencode-agentcore-profile-2 \
  --agent-kind opencode \
  --profile "$CONNECTION_NAME" \
  --config-dir "$HERDR_CONFIG_DIR" \
  --command /app/run.sh
```

Replace the command with the actual launcher if it differs.
For example, an existing custom launcher can receive separate arguments:

```bash
.venv/bin/herdr-agentcore configure \
  --runtime-arn "$RUNTIME_ARN" \
  --agent-kind terminal \
  --profile custom-runtime \
  --config-dir "$HERDR_CONFIG_DIR" \
  --command /opt/assistant/start --project "/workspace/my project"
```

`--command` consumes all remaining arguments. Put it last.
Here, `--runtime-profile opencode-agentcore-profile-2` records the example provision profile reference.
`--agent-kind opencode` is the recognition hint specified by that profile, not a special connector value.
Omitting the kind, or using `terminal`, selects an ordinary terminal without an agent-recognition hint.
Herdr must already support a kind before its agent APIs can use that hint.

The connector has no default command. Missing or empty argv is an error, even when the kind is `opencode`.
The command must exist and be executable inside the selected runtime.
Registration does not install the executable or change the container's `CMD`.

### Method B: import a connection descriptor

Use the private file supplied by the runtime owner:

```bash
.venv/bin/herdr-agentcore configure \
  --connection-file .local/deployments/owner-provided.connection.json \
  --profile "$CONNECTION_NAME" \
  --config-dir "$HERDR_CONFIG_DIR"
```

Set that path to the standalone descriptor supplied by the runtime owner. CDK does not generate this file; use method C for CDK outputs.
The descriptor must include an explicit `command`. It can also specify the endpoint and agent kind.
Its region must match the ARN. It must not contain host credentials or a host AWS profile.
See the [connection contract](../src/runtime_contract/README.md) for the complete format.

To override a valid descriptor's command, append `--command` and the complete replacement argv last.
An override does not repair an invalid descriptor that omits its required command; use method A or obtain a valid file.
Only import trusted descriptors: their command runs remotely when you start a new session.

For any registration method, use `--replace` before `--command` only when replacing an existing local profile.
A profile replacement affects future connections, not commands in saved session snapshots.

### Method C: import AWS CDK outputs

The deployment owner runs `cdk deploy --outputs-file PATH`. The standard output file contains the stack's resolved `ConnectionDescriptor`.

```bash
.venv/bin/herdr-agentcore configure \
  --cdk-outputs .local/deployments/opencode-agentcore-profile-2.json \
  --stack HerdrOpenCodeRuntime \
  --profile "$CONNECTION_NAME" \
  --config-dir "$HERDR_CONFIG_DIR"
```

Select the file and stack for the intended current deployment:

| Provision profile | File under `.local/deployments/` | Stack |
| --- | --- | --- |
| `codex-agentcore-profile-1` | `codex-agentcore-profile-1.json` | `HerdrCodexRuntime` |
| `opencode-agentcore-profile-2` | `opencode-agentcore-profile-2.json` | `HerdrOpenCodeRuntime` |
| `opencode-s3filesystem-agentcore-profile-3` | `opencode-s3filesystem-agentcore-profile-3.json` | `HerdrOpenCodeS3FilesystemRuntime` |

You can use the provision profile name as `CONNECTION_NAME`, or choose another local label.
If an output file contains multiple stacks, `--stack` is required. The connector does not choose one arbitrarily.
The imported runtime-profile reference is descriptive metadata. Command and recognition fields are already resolved in the descriptor.
See the [runtime deployment steps](../src/agentcore_runtime/README.md) for all three profiles.

## Step 5: check the saved configuration

```bash
.venv/bin/herdr-agentcore profiles --config-dir "$HERDR_CONFIG_DIR"
```

Check the ARN, region, endpoint, full command array, and agent kind.
This command reads local configuration. It is not a remote readiness check.
Retired output files and older saved connection profiles can still contain obsolete ARNs. Compare the selected profile with the current stack's outputs.
Keep populated deployment outputs under ignored `.local/deployments/`. Herdr manages its saved connection configuration and state.

## Step 6: open a new assistant session

Use the selected profile explicitly:

```bash
.venv/bin/herdr-agentcore action new --profile "$CONNECTION_NAME"
```

Herdr opens a pane. The connector signs a Shell connection, creates new session/shell IDs, and sends the declared command once.
Expected results are connected transport metadata and the assistant's interactive screen.
For OpenCode, confirm that the input widget is ready before entering a prompt.
Do not treat an update dialog, error screen, or cached output as a ready assistant.

A valid ARN alone cannot locate an existing conversation or take over an arbitrary running process.
The `new` action creates fresh work; it is not a recovery action.

## Step 7: optionally choose the default profile

```bash
.venv/bin/herdr-agentcore set-default "$CONNECTION_NAME" \
  --config-dir "$HERDR_CONFIG_DIR"
```

Future default launches can use:

```bash
herdr plugin action invoke agentcore.new
```

An explicit profile override has priority over the saved default.
The first profile saved into an empty configuration becomes default. Later saves preserve that choice.
Importing the numbered profiles does not update an older saved default. Select the current profile explicitly before launching it.
If configuration has no saved default, select one explicitly. The connector does not infer it from a name or profile count.

## Step 8: verify detach and attachment

1. Complete a small, non-destructive interaction with the assistant.
2. Press Ctrl+] and then `d` to detach.
3. Open the attachment action:

   ```bash
   herdr plugin action invoke agentcore.attach
   ```

4. Select the saved connection.
5. Confirm that the original terminal and conversation remain available.

Attachment uses the saved runtime-session ID and shell ID. It does not resend the launch command.
If the original PTY has ended, attachment reports failure rather than launch another assistant silently.
Automatic recovery after compute termination is not implemented.

## Step 9: stop a test session when finished

Detach first. Open the stop action:

```bash
herdr plugin action invoke agentcore.stop
```

Select the test connection and enter its name at the confirmation prompt.
Stop targets the entire runtime session and all its processes. It does not delete the runtime deployment.
The local `stopped` label means the API accepted the request; there is no stop-completion waiter.

## Does the runtime need changes?

### Verified current examples — 2026-10-19

The three model-only profiles were destroyed and redeployed with new runtime ARNs. Every runtime and `DEFAULT` endpoint reached version 1 and READY.
The numbered saved profiles were replaced from the new CDK outputs. Two independent sessions per profile opened in three replacement Herdr tabs and returned date and folder-access results.
The filesystem sessions used the shared `/mnt/workspace` mount; the PUBLIC sessions used runtime-local home directories.
Those six user-requested sessions were left open. The separate disposable verification probes stopped their own sessions.
See the [rebuild verification](../src/agentcore_runtime/README.md#model-only-profile-rebuild--2026-10-19) for storage checks and model-history limits.

### Adaptation cases

| Existing runtime | Required adaptation |
| --- | --- |
| Installed interactive assistant and usable Shell access | Usually configuration only. Supply the actual launch command. |
| Different launcher path | Change the command in the definition, descriptor, or connector configuration. |
| No interactive assistant | Install one or add a terminal adapter. An HTTP-only API is not enough for this connector. |
| Static temporary credentials exported by a launcher | Use a suitable startup wrapper or correct that launcher. Reattachment cannot refresh an existing process's environment. |
| Long work not reported to AgentCore | Add real `HealthyBusy` reporting in the runtime. An open terminal is not proof of active work. |
| Recovery needed after compute termination | Implement persistent files and application-state recovery separately. |

`/app/run.sh` comes from the AWS OpenCode sample and is also supplied by this project's OpenCode definition.
It is not an AgentCore or Herdr requirement. In our images, it starts the shared launcher, then the selected image's assistant adapter.
The container's default process is the health service, not this assistant launcher.
See the [sample attribution](../src/agentcore_runtime/agent_images/opencode/NOTICE).

For a sample launcher that exports a static credential snapshot, ask its owner to supply a refreshable startup path or a reviewed wrapper command.
The connector does not implement that runtime-specific repair. Reattachment cannot change an already-running process's environment.
The supplied OpenCode and Codex example images use native AWS credential providers instead of exporting credential snapshots.

## Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `command is required` | Supply `--command` last, or obtain a descriptor with explicit argv. |
| Missing/expired host credentials | Refresh the host credential chain or select the correct `--aws-profile`. |
| Access denied | Check Shell permission for the selected runtime and endpoint. STS success alone is insufficient. |
| Command not found | Confirm the path inside the runtime. Registration cannot create it. |
| Assistant opens but Herdr shows a normal terminal | Check the explicit `agent_kind` and Herdr support for it. The connector does not infer a kind. |
| Model call fails but the terminal works | Inspect the worker's model/endpoint selection, role, credentials, network access, and account retention eligibility. Host and worker identities are separate. |
| Original PTY missing | The saved shell ended or compute expired. Do not expect attachment to restore ephemeral files or conversation state. |
| Very small OpenCode pane crashes | Use a larger or zoomed pane. The tested OpenCode version has a known small-viewport failure. |

See the [connector README](../src/herdr_plugin/README.md) and [design](DESIGN.md) for full behavior and current limits.
For native Herdr detection and AgentCore health differences, see the [runtime comparison](../src/agentcore_runtime/README.md#opencode-and-codex-comparison).
