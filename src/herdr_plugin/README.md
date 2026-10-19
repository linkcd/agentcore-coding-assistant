# Herdr AgentCore connector

## Purpose

Connect Herdr terminals to provisioned AgentCore runtimes.
The package is `herdr-agentcore`. Its Python module is `herdr_agentcore`.
Its executable is `herdr-agentcore`.

The connector owns profiles, session/shell IDs, terminal transport, reconnect, detach, and stop.
It does not build images, provision infrastructure, choose models, or install assistant skills.
It depends on the shared contract and AgentCore client libraries, not the runtime-definition package.
Named runtime settings such as `opencode-agentcore-profile-2` are references supplied by the runtime owner.
The connector stores that reference and uses the explicit command and Herdr hint. It does not contain an assistant-name enum.

## Configure a runtime

Follow the [step-by-step existing-runtime guide](../../docs/CONNECT_EXISTING_RUNTIME.md) for authentication, launch checks, and troubleshooting.

Run from the repository root. Use macOS or Linux, Python 3.11+, uv, and Herdr 0.9.5+.

1. Install the connector and its dependencies:

   ```bash
   uv sync --frozen --no-dev
   ```

2. Link the plugin:

   ```bash
   herdr plugin link "$PWD"
   ```

3. Import the current OpenCode CDK outputs:

   ```bash
   .venv/bin/herdr-agentcore configure \
     --cdk-outputs .local/deployments/opencode-agentcore-profile-2.json \
     --stack HerdrOpenCodeRuntime \
     --profile opencode-agentcore-profile-2 \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

4. Select the default profile:

   ```bash
   .venv/bin/herdr-agentcore set-default opencode-agentcore-profile-2 \
     --config-dir "$(herdr plugin config-dir agentcore)"
   ```

5. Open the agent:

   ```bash
   herdr plugin action invoke agentcore.new
   ```

Alternatively, register a deployed ARN directly:

```bash
.venv/bin/herdr-agentcore configure \
  --runtime-arn "$RUNTIME_ARN" --agent-kind opencode \
  --runtime-profile opencode-agentcore-profile-2 \
  --profile opencode-agentcore-profile-2 \
  --config-dir "$(herdr plugin config-dir agentcore)" \
  --command /app/run.sh
```

`--command` consumes the remaining arguments. Put it last.
It is required with `--runtime-arn` or the sample ARN import. The connector has no default launcher.
The interactive setup menu also requires explicit JSON argv.
Use `--aws-profile` for host-local credential selection. Omit it to use the normal AWS provider chain.
Deployment credentials do not arrive through the descriptor.
Add `--replace` only when replacing an existing profile.

Direct ARN registration without `--agent-kind` creates an ordinary terminal profile.
Descriptor import uses its declared hint. `--agent-kind terminal` explicitly clears a hint.
The hint does not install Herdr support for a new assistant. Herdr must already recognize that kind.

For an owner-supplied standalone descriptor, replace `--cdk-outputs PATH --stack STACK_NAME` with `--connection-file PATH`.
CDK does not create a separate `.connection.json` file.
The runtime profile reference, Herdr recognition hint, local connection profile label, and AWS credential profile are separate settings.

The current deployment outputs are:

| Provision profile and suggested connection label | File under `.local/deployments/` | Stack |
| --- | --- | --- |
| `codex-agentcore-profile-1` | `codex-agentcore-profile-1.json` | `HerdrCodexRuntime` |
| `opencode-agentcore-profile-2` | `opencode-agentcore-profile-2.json` | `HerdrOpenCodeRuntime` |
| `opencode-s3filesystem-agentcore-profile-3` | `opencode-s3filesystem-agentcore-profile-3.json` | `HerdrOpenCodeS3FilesystemRuntime` |

Use the same configure command with the selected row's file, stack, and profile.
Deployment does not update saved Herdr profiles automatically. Import successful outputs before starting a new deployment's sessions.

## Profiles and session operations

Selection order: explicit `--profile`, then `HERDR_AGENTCORE_PROFILE`, then saved `default_profile`.
The first saved profile becomes default. Later saves preserve it.
An invalid override fails instead of selecting another runtime.

```bash
.venv/bin/herdr-agentcore action new --profile opencode-agentcore-profile-2
herdr plugin action invoke agentcore.attach
herdr plugin action invoke agentcore.sessions
herdr plugin action invoke agentcore.stop
```

Detach with Ctrl+] followed by `d`.
Attachment reuses the original runtime-session and shell IDs. It does not launch a second assistant.
Stop targets the whole runtime session, not one shell. It requires confirmation and a local lock.
The local `stopped` label means the request was accepted; no completion waiter exists.

Profiles and connection records remain in Herdr's external config/state directories.
Existing profile snapshots keep their recorded target, command, and recognition hint.
Damaged records are reported without deleting them or hiding healthy records.
Adding the numbered profiles preserves an older saved default. Use an explicit launch profile or select a verified current default.

## Latest verification — 2026-10-19

The three numbered descriptors were imported into Herdr. Two independent sessions per profile opened in three tabs.
All six passed native recognition, real model-driven date commands, and read-only folder-access checks.
The user-requested sessions were left open. They are not disposable probe sessions; check live state before any later operation.
The Codex/Sol deployment also passed an isolated detach/attachment, context-preserving follow-up, runtime-role, and shell-tool probe.
That probe stopped its own session and server. See the [runtime results](../agentcore_runtime/README.md#current-validation) for versions and test scope.

## Format and command ownership

- Profiles and descriptors are unreleased formats. Their internal version fields do not establish a public compatibility contract.
- Every profile requires explicit `command`. A missing `agent_kind` always means an ordinary terminal.
- The connector executes declared argv. It does not infer an assistant type from an ARN, executable name, or file path.
- Wrapped launch commands work without importing runtime implementation code.
- `--runtime-config` imports an external sample's ARN only. Supply `--command` and any recognition hint explicitly.
- Runtime infrastructure uses official AWS CDK commands in `src/agentcore_runtime/`.
- Import its `ConnectionDescriptor` through `--cdk-outputs`, or use an owner-supplied descriptor/explicit ARN.
- Runtime-specific credential or launcher repairs belong to the image owner, not the connector.

To replace a valid descriptor's command, add `--command` and the complete replacement argv last during configuration.
The command must already exist in the selected runtime. Registration does not install it.

## Checks

Run from the repository root:

```bash
uv sync --frozen
HERDR_TEST_BINARY="$(command -v herdr)" \
  uv run --frozen pytest src/herdr_plugin/tests -q --tb=short
uv build --package herdr-agentcore
```

The optional Herdr test uses an isolated registry. Default tests make no AWS calls.
Live probes in `tests/` require explicit authorization and a selected runtime.

Repository links: [runtime definitions](../agentcore_runtime/README.md), [connection contract](../runtime_contract/README.md), and [writing rules](../../agent.md#documentation-style-asd-ste100-style-english).
These relative links refer to a full repository checkout.
