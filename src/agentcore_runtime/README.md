# AgentCore runtime infrastructure

## Purpose

Define and deploy AgentCore infrastructure with the official AWS Cloud Development Kit (CDK).
This folder is a CDK project, not a Python package or an assistant launcher executable.
Use standard `cdk synth`, `cdk diff`, `cdk deploy`, and `cdk destroy` commands.
CDK builds and publishes Docker assets and manages CloudFormation resources.

## Named runtime profiles

`-c runtimeProfile=NAME` selects `profiles/NAME.json`.
The name is a pointer to settings, not an assistant enum in the connector.
`opencode` and `codex` are supplied examples. Add another JSON profile to define another configuration.
Several profiles can use the same assistant with different commands, models, or settings.

| Term | Meaning |
| --- | --- |
| Runtime profile | Named CDK settings file, such as `profiles/opencode.json`. |
| Herdr connection profile | Host-local label that stores the deployed ARN and resolved connection fields. |
| `agent_kind` | Herdr recognition hint read from runtime profile settings. It does not select infrastructure. |
| AWS profile | Host credential selection through CDK's `--profile` or the connector's `--aws-profile`. |

Each runtime profile declares image context/build arguments, command, recognition hint, inference settings, and environment.
The contract receives resolved command data plus a `runtime_profile` reference. The connector never imports CDK code or resolves a name into an assumed command.

```text
src/agentcore_runtime/
  app.ts                 Load the selected named settings
  profile.ts             Read and validate settings
  runtime-stack.ts       Official CDK constructs
  profiles/              Example named settings
    opencode.json
    codex.json
  common/                Shared Dockerfile, startup, health, work-lease reader, and license
  opencode/image/        OpenCode adapter, configuration, and work-event plugin
  codex/image/           Codex adapter and attribution
  tests/                 CDK assertions and runtime-image checks
  cdk.json
  package.json
```

## Required AWS libraries and tools

| Dependency | Purpose |
| --- | --- |
| `aws-cdk-lib` 2.273.0 | Official `aws_bedrockagentcore.CfnRuntime`, IAM, outputs, and Docker assets. |
| `constructs` 10.8.1 | CDK construct base library. |
| `aws-cdk` CLI 2.1145.0 | Standard synthesis, difference review, deployment, and destruction. |
| Node.js 22+ and npm | Run the CDK application and install locked dependencies. |
| TypeScript and `tsx` | Type-check and run the CDK application. |
| Docker with ARM64 support | Build the selected assistant image. |
| AWS credentials | Authorize CDK deployment and role assumption. |
| AWS CLI v2, recommended | Check identity and refresh SSO credentials. |
| CDK bootstrap resources | Store/publish assets and supply deployment roles in the target account/region. |

The npm lockfile pins dependencies. CLI and construct-library version numbers are independent.
No custom Boto3 create/update deployment loop is used.

## Shared image structure

Both supplied profiles use the same `common/Dockerfile` and runtime-root build context.
Profile build arguments select the npm package, pinned version, executable, and `ASSISTANT_DIR`.
CDK stages only `common/` and the selected adapter directory. Changes to another adapter do not change this image asset.

The shared image installs the common coding tools and checks the installed assistant version.
It copies shared files to `/app`, then adds the selected adapter as `/app/assistant.py`.
The shared `/app/run.sh` calls `/app/launch.py`, which delegates to that adapter.
The health server remains the container's default process.

Both adapter directories contain `assistant.py`, Python module metadata, and `NOTICE`.
An adapter supplies the non-secret environment allowlist, required settings, launch arguments, and working-directory setting.
Shared code reads PID 1 settings, preserves explicit values, changes directory, handles startup errors, and replaces the launcher process.
Neither adapter writes credentials or overwrites user configuration.

Optional files reflect real assistant requirements. OpenCode needs `opencode.json`, an event plugin, and a build-time plugin-dependency warmup.
Codex uses native CLI configuration arguments and currently has no work-event adapter.
Do not add empty files to make the file counts equal. Keep this comparison in this README; do not add assistant-specific READMEs.

## OpenCode and Codex comparison

The names below refer to the supplied settings. Other named profiles can reuse either adapter.

| Area | OpenCode example | Codex example |
| --- | --- | --- |
| Infrastructure | Shared official CDK stack, ARM64 Docker asset, IAM role, and outputs. | Same. |
| Build and startup | Shared Dockerfile, tools, user, entrypoint, environment inheritance, and error handling. | Same. |
| Assistant adapter | `opencode/image/assistant.py`. | `codex/image/assistant.py`. |
| Package/version | `opencode-ai` 1.18.30. | `@openai/codex` 0.163.0. |
| Inference | Bedrock Runtime through OpenCode's native provider. | Bedrock Mantle through Codex's native provider. |
| Model authentication | Refreshable execution-role provider; no exported snapshot. | Native AWS credential chain; no generated bearer-token snapshot. |
| Configuration | Additional `opencode.json`; explicit updater suppression. | Native `--config` and `--model` arguments; normal approvals remain enabled. |
| HTTP health and process checks | Shared health server and live/fresh work-lease reader. | Same implementation. |
| AgentCore work-event source | OpenCode event/tool hooks publish process-bound work leases. | Not implemented. No work lease is produced by this adapter. |
| Herdr native support | Supported by Herdr 0.9.5. | Supported by Herdr 0.9.5. |
| Current remote Herdr status | Host wrapper hint plus Herdr's active screen manifest. | Same mechanism, with Codex-specific screen/title rules. |
| Runtime health while work runs | `HealthyBusy` when a valid work lease exists. | Currently `Healthy` without a work-event reporter, even if Herdr sees working UI. |
| Validation boundary | Shared image passed cloud model, activity, and Herdr attachment probes on a disposable deployment. | Shared image passed cloud model and Herdr attachment probes. Work-health reporting and sandbox/tool execution remain unvalidated. |

### How Herdr checks state

Herdr 0.9.5 lists both `opencode` and `codex` as supported kinds.
For remote assistants, the connector sets the profile's `agent_kind` as `HERDR_AGENT` on its host-visible process.
Herdr uses that hint to select an existing detection manifest. It reads the live terminal detection region and, where supported, the terminal OSC title.
The connector forwards those terminal bytes; it does not implement a second screen detector or report guessed lifecycle states.

The pinned Herdr 0.9.5 bundled rules use these signals:

| State evidence | OpenCode manifest | Codex manifest |
| --- | --- | --- |
| Working | Interrupt hints such as `esc to interrupt`, or recognized progress-bar glyphs. | A spinner in the OSC title, or a live elapsed-time status line with supported interrupt/timer patterns. |
| Blocked | Known permission prompts or confirm/submit controls in the recent screen region. | `Action Required` in the OSC title; known directory-trust, update-picker, approval, or question UI. |
| Idle | Known-agent idle fallback when no stronger rule matches. | Non-working title rule, or known-agent idle fallback when no stronger rule matches. |

These rules are versioned evidence, not proof that arbitrary new UI is recognized.
An unfamiliar approval prompt can fall back to idle. A connected wrapper can also outlive a failed remote assistant.
Inspect unexpected UI before sending input. A Herdr idle badge is not permission to approve an action or proof that all background work ended.

Herdr can load newer compatible remote manifests or local overrides. Inspect the running server's actual rule source and match:

```bash
herdr agent list
herdr agent explain <agent-name-or-pane-id> --json
herdr agent read <agent-name-or-pane-id> --source detection --lines 80
```

An installed Herdr 0.9.5 check with synthetic Codex screen text matched `screen_working_fallback` to `working` and `live_strong_blocker` to `blocked`.
The active manifest reported version `2026.10.11.1`. This verifies those detection rules, not a Codex cloud conversation or every possible prompt.

The optional native Herdr OpenCode integration can report lifecycle state and session identity directly when it can reach the local Herdr socket.
The native Codex integration reports session identity; its lifecycle status still uses screen detection.
This project does not relay either integration's local socket from AgentCore to the management host.
Our OpenCode activity plugin reports to AgentCore health, not to Herdr. Installing a host integration does not create that remote relay.

### Herdr state and AgentCore health are separate

Herdr's state controls viewing, waits, and notifications. AgentCore's `/ping` status affects runtime activity accounting.
The shared health reader accepts only fresh leases from matching live processes. It returns `Healthy` when no valid lease exists.
This means Codex can be working according to Herdr while AgentCore receives only readiness health.
Codex needs a real runtime-side work reporter before long work can reliably report `HealthyBusy`; it does not need another Herdr detector.
Do not replace missing telemetry with a permanent busy flag or an advancing `time_of_last_update`.

## Step 1: prepare tools and authentication

Run the following commands from the repository root:

```bash
npm ci --prefix src/agentcore_runtime
npm run check --prefix src/agentcore_runtime
npm test --prefix src/agentcore_runtime
aws sts get-caller-identity
docker version
```

If you use a named AWS profile, add `--profile YOUR_AWS_PROFILE` to CDK commands.
Refresh its SSO login first when needed. Do not store credentials in profile JSON or CDK context.

Create a private location for deployment outputs:

```bash
mkdir -p -m 700 "$HOME/.config/agentcore"
```

## Step 2: bootstrap the target environment if needed

Check whether the account/region already has a suitable `CDKToolkit` stack.
If it does not, an authorized administrator must bootstrap it:

```bash
npm --prefix src/agentcore_runtime run cdk -- bootstrap aws://ACCOUNT_ID/REGION
```

Replace `ACCOUNT_ID` and `REGION` with the intended environment.
Bootstrap is shared account infrastructure. Review its trust and CloudFormation execution policies with the environment owner.
Do not bootstrap another account or delete a shared bootstrap stack as application cleanup.

## Step 3: deploy the OpenCode example profile

The `opencode` settings select the bundled image, pinned OpenCode 1.18.30, and `command: ["/app/run.sh"]`.
The launcher uses the runtime execution role for Bedrock. It does not export static credentials.

Synthesize without deploying:

```bash
npm --prefix src/agentcore_runtime run cdk -- synth \
  -c runtimeProfile=opencode -c region=eu-west-1
```

Review the infrastructure changes:

```bash
npm --prefix src/agentcore_runtime run cdk -- diff \
  -c runtimeProfile=opencode -c region=eu-west-1
```

Deploy the selected stack:

```bash
npm --prefix src/agentcore_runtime run cdk -- deploy HerdrOpenCodeRuntime \
  -c runtimeProfile=opencode -c region=eu-west-1 \
  --outputs-file "$HOME/.config/agentcore/cdk-outputs-opencode.json"
```

Choose a region and model available to your account. Override the profile's model with `-c modelId=MODEL_ID` when needed.
CDK owns image publication, IAM resources, and the `AWS::BedrockAgentCore::Runtime` resource.

## Step 4: deploy the Codex example profile

The `codex` settings point to a different image and command configuration using the same CDK stack implementation.
The container adapts the [AWS Codex sample](https://github.com/awslabs/agentcore-samples/tree/abab3d8beb684c79fc827a95a2d015e44e76dbbc/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e/coding_agents/codex).
It pins Codex 0.163.0 and uses Codex's native `amazon-bedrock` provider with the AWS credential chain.
It does not generate or export a one-time bearer token, disable approvals, or overwrite user configuration.

The example model is `openai.gpt-5.5` through Bedrock Mantle in `us-east-2`, following the sample.
Verify current model availability and your account's inference access before deployment.
Use `-c modelId=MODEL_ID -c inferenceRegion=REGION` to select another supported model/region pair.

```bash
npm --prefix src/agentcore_runtime run cdk -- synth \
  -c runtimeProfile=codex -c region=us-east-2
npm --prefix src/agentcore_runtime run cdk -- diff \
  -c runtimeProfile=codex -c region=us-east-2
npm --prefix src/agentcore_runtime run cdk -- deploy HerdrCodexRuntime \
  -c runtimeProfile=codex -c region=us-east-2 \
  --outputs-file "$HOME/.config/agentcore/cdk-outputs-codex.json"
```

Codex uses the shared health server but has no work-event reporter. It currently provides readiness health only.
Do not treat process existence as active work. Long-running work can still reach the idle timeout.
Codex cloud inference and attachment passed the short E2E probe. Long-duration behavior, sandbox/tool execution, and full credential rollover require separate validation.

Local validation built the ARM64 Codex image and started its CLI with networking disabled.
Both shared-image profiles were deployed to disposable test runtimes for cloud E2E validation.

## Step 5: register the deployment in Herdr

Install the connector and link the root plugin manifest if needed:

```bash
uv sync --frozen --no-dev
herdr plugin link "$PWD"
```

Import OpenCode's CDK outputs:

```bash
.venv/bin/herdr-agentcore configure \
  --cdk-outputs "$HOME/.config/agentcore/cdk-outputs-opencode.json" \
  --stack HerdrOpenCodeRuntime \
  --profile opencode-agentcore-runtime \
  --config-dir "$(herdr plugin config-dir agentcore)"
```

For Codex, use its output file, `--stack HerdrCodexRuntime`, and a separate local connection profile name.
Add `--replace` only when replacing a saved connection profile.
The exported `ConnectionDescriptor` includes ARN, endpoint, explicit command, runtime-profile reference, and recognition hint.
Host credentials remain a local connector choice.
Follow the [existing-runtime guide](../../docs/CONNECT_EXISTING_RUNTIME.md) to open, verify, detach, and reattach a session.

## Launch command selection

The command belongs to `profiles/NAME.json`; neither the contract nor connector has a default command.
The shared examples use `/app/run.sh`; this path is not an AgentCore or Herdr requirement.
It starts an assistant when the connector opens a new session; the container's default process is the health service.

Override the selected profile's command with JSON argv:

```bash
npm --prefix src/agentcore_runtime run cdk -- synth \
  -c runtimeProfile=opencode -c region=eu-west-1 \
  -c 'command=["/opt/assistant/start","--project","/workspace/my project"]'
```

Use the same context during diff/deploy. The override changes connection output, not Docker `CMD` or installed files.
The executable must exist in the image. The recognition hint must match the assistant that it starts.

## Add another named profile

1. Add `profiles/NAME.json`, or copy an example under a new name.
2. Set its stack/runtime names to avoid replacing another deployment.
3. Select its image directory, Dockerfile, and pinned build arguments.
   For the shared template, use `common/Dockerfile` and set `ASSISTANT_DIR`, `NPM_PACKAGE`, `NPM_VERSION`, and `EXECUTABLE`.
4. Declare the command, Herdr hint, inference settings, and non-secret environment.
5. Run type checks, tests, and `cdk synth -c runtimeProfile=NAME`.
6. Review `cdk diff`, then deploy with the same profile/context.

No connector switch statement or assistant-name enum is needed.
The current stack supports Bedrock Runtime and Bedrock Mantle inference policies. Other inference services require an appropriate CDK policy extension.

## Current validation

The shared-image refactor passed 180 Python tests with both newly built ARM64 images, six CDK tests, and TypeScript checking.
The image tests cover shared HTTP health for both adapters, native CLI startup, OpenCode work transitions, and process-death cleanup.
CDK tests confirm that the staged asset contains shared files and the selected adapter only.
The refactored images were then deployed through CDK to separate disposable runtimes in `eu-west-1`.
Codex used the profile's declared Mantle inference region, `us-east-2`.

### Cloud E2E results for the shared images

| Check | OpenCode | Codex |
| --- | --- | --- |
| CDK deploy and runtime startup | Passed. | Passed. |
| Herdr new-agent action and native recognition | Passed in an isolated server. | Passed in an isolated server. |
| Real model turn through `agent prompt --wait` | Passed; generated the expected arithmetic response. | Passed; generated the expected arithmetic response. |
| Process credential inspection | No static AWS keys or provider tokens. | No static AWS keys or provider tokens. |
| Detach and original-session attachment | Passed without a second connection record. | Passed without a second connection record. |
| Follow-up conversation continuity | Passed after attachment. | Passed after attachment. |
| Explicit plugin stop action | Request accepted. | Request accepted. |
| Work/question/reply/completion health | Passed against the deployed `/ping` service. | No work-event reporter is implemented. |
| Process-death health cleanup | Passed. | Not qualified as work tracking. |

The model prompts prohibited tool use and file changes. These tests do not qualify sandbox execution or the full approval/keyboard matrix.
Codex also completed a supplemental non-interactive model request with stdin closed.

Codex displayed two startup warnings. Inspection found a missing system `bubblewrap` executable, with a reported bundled fallback, and embedded mode selected by command-line configuration overrides.
Those warnings did not block the tested model/attachment flow. Sandbox behavior remains a separate check.
The warning panel opened with the raw `CSI 12~` sequence; the logical F2 probe did not open it. Full function-key compatibility remains unverified.

All probes requested stop for their own sessions and stopped their isolated Herdr servers.
Both temporary stacks were destroyed, and control-plane lookups confirmed that both test runtimes no longer exist.
The OpenCode stack's first deletion timed out in the CloudFormation resource handler. After confirming the runtime was already absent, a second `cdk destroy` completed.
Shared CDK asset storage remains under its normal retention policy. The existing default deployment stayed READY; the temporary test deployments were not promoted to it.

### Earlier deployed baseline

The `opencode` settings were deployed through official CDK in place of the old custom-managed runtime.
The runtime and default endpoint reached READY. The updated connector imported the resolved CDK outputs.
Fresh cloud probes passed model/role checks, work/question/reply health, process-death cleanup, attachment, and conversation continuity.
The probes stopped their own sessions and isolated Herdr server.
CDK assertions and synthesis cover the `codex` example. Later shared-image cloud evidence is recorded above.
That baseline passed 174 Python tests, five CDK assertions, and a no-change CDK diff before the shared-image refactor.
Those cloud results predate the shared-image refactor. Do not treat them as a deployment of the new common image files.

## Updates and cleanup

Use the same profile, stack, account, and region for `cdk diff` and `cdk deploy`.
When old sessions need an earlier Bedrock model, declare its ID through `-c 'retainedModelIds=["previous.model"]'`.
CDK does not inspect and merge arbitrary existing IAM policies. Its declared configuration is authoritative.
Removing model access can affect surviving sessions, so review IAM changes before applying them.

Stop the selected deployment's sessions before destruction:

```bash
npm --prefix src/agentcore_runtime run cdk -- destroy HerdrOpenCodeRuntime \
  -c runtimeProfile=opencode -c region=eu-west-1
```

CDK bootstrap repositories and their asset retention are separate from runtime-stack destruction.
Do not delete a shared asset repository as part of a runtime teardown.

## References

- [Official AgentCore CDK resource](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore.CfnRuntime.html).
- [Official Docker image assets](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_ecr_assets.DockerImageAsset.html).
- [CDK bootstrapping](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html).
- [AWS Codex sample collection](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e/coding_agents).
- [Codex with Amazon Bedrock](https://developers.openai.com/codex/amazon-bedrock).
- [Herdr 0.9.5 status detection](https://herdr.dev/docs/0.9.5/agents/#how-status-works).
- [Herdr integration behavior](https://herdr.dev/docs/0.9.5/integrations/).
- [Pinned Codex detection rules](https://github.com/herdrdev/herdr/blob/v0.9.5/src/detect/manifests/codex.toml).
- [Pinned OpenCode detection rules](https://github.com/herdrdev/herdr/blob/v0.9.5/src/detect/manifests/opencode.toml).
- [Connection contract](../runtime_contract/README.md) and [ASD-STE100-style writing rules](../../agent.md#documentation-style-asd-ste100-style-english).
