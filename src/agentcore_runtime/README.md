# AgentCore runtime infrastructure

## Purpose

Define and deploy AgentCore infrastructure with the official AWS Cloud Development Kit (CDK).
This folder is a CDK project, not a Python package or an assistant launcher executable.
Use standard `cdk synth`, `cdk diff`, `cdk deploy`, and `cdk destroy` commands.
CDK builds and publishes Docker assets and manages CloudFormation resources.

## Agent images and provision profiles

`-c runtimeProfile=NAME` selects `provision_profiles/NAME.json`.
The existing CDK context key remains `runtimeProfile`. The directory and documentation use **provision profile**.
The name is a pointer to settings, not an assistant enum in the connector.
The three samples are `codex-agentcore-profile-1`, `opencode-agentcore-profile-2`, and `opencode-s3filesystem-agentcore-profile-3`.
Several profiles can use the same assistant with different commands, models, or settings.

| Term | Meaning |
| --- | --- |
| Agent image | Container sources plus one `image.json` definition under `agent_images/NAME/`. |
| Provision profile | Named deployment input that references an image, model, lifecycle, and optional network/storage. |
| Herdr connection profile | Host-local label that stores the deployed ARN and resolved connection fields. |
| `agent_kind` | Herdr recognition hint declared by the image, with an optional profile override. It does not select infrastructure. |
| AWS profile | Host credential selection through CDK's `--profile` or the connector's `--aws-profile`. |

Each sample profile declares only its deployment choices. Build and startup defaults belong to the image definition.
Deployment inputs are self-contained in this component: tracked provision profiles plus `src/agentcore_runtime/.env`.
The env file is ignored by Git. The adjacent tracked [.sample.env](.sample.env) lists the local bindings to fill.
CDK does not read a repository-root `.env` or external profile directories.
The entrypoint resolves the profile and image definition once, then passes the settings into the stack.
Only `-c runtimeProfile=NAME` selects project configuration. Per-field CDK context overrides are rejected.
Actual runtime ARNs are deployment outputs. Provision profiles are inputs, not records of already-created runtimes.
The contract receives resolved command data plus a `runtime_profile` reference. The connector never imports CDK code or resolves a name into an assumed command.

```text
src/agentcore_runtime/
  README.md              This guide and the three sample profiles
  .env                   Local filesystem bindings; ignored by Git
  .sample.env            Tracked env template; no real resource values
  cdk/                   CDK source, npm metadata, configuration, and tests
    app.ts
    profile.ts
    image.ts
    runtime-stack.ts
    tests/cdk.test.ts
    cdk.json
    package.json
    package-lock.json
    tsconfig.json
  provision_profiles/    Deployment inputs
    codex-agentcore-profile-1.json
    opencode-agentcore-profile-2.json
    opencode-s3filesystem-agentcore-profile-3.json
  agent_images/
    common/              Shared Dockerfile, startup, health, and license
    opencode/            image.json, adapter, model catalog, and work-event plugin
    codex/               image.json, adapter, sandbox configuration, and build hook
  tests/                 Python and JavaScript runtime checks and live probes
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

All supplied profiles use `agent_images/` as the build context and `common/Dockerfile` within that context.
The Dockerfile is a shared build template. Each build installs one assistant and produces a separate image.
The profile's `image` reference selects `agent_images/NAME/image.json`.
That definition declares the Dockerfile, package/version build arguments, executable, launch command, and Herdr hint.
CDK derives `ASSISTANT_DIR` from the image reference. The definition must not repeat it.
CDK stages only `common/` and the selected adapter directory. Changes to another adapter do not change this image asset.

The shared image installs the common coding tools and checks the installed assistant version.
It copies shared files to `/app`, then adds the selected adapter as `/app/assistant.py`.
The shared `/app/run.sh` calls `/app/launch.py`, which delegates to that adapter.
The health server remains the container's default process.

Both adapter directories contain `assistant.py`, Python module metadata, and `image.json`.
The shared image sources include `common/LICENSE`. The OpenCode adapter also retains its upstream `NOTICE`.
An adapter supplies the non-secret environment allowlist, required settings, and launch arguments.
The common launcher uses `AGENTCORE_WORKDIR` when supplied, otherwise the image's home directory.
Shared code reads PID 1 settings, preserves explicit values, changes directory, handles startup errors, and replaces the launcher process.
Neither adapter writes credentials or overwrites user configuration.

Optional files reflect real assistant requirements. OpenCode needs `opencode.json`, an event plugin, and a build-time plugin-dependency warmup.
Codex uses native CLI configuration arguments and a native permission preset.
Its build hook creates the initial user configuration. Startup does not replace existing user configuration.
Codex currently has no work-event adapter.
Do not add empty files to make the file counts equal. Keep this comparison in this README; do not add assistant-specific READMEs.

## OpenCode and Codex comparison

The names below refer to the supplied settings. Other named profiles can reuse either adapter.

| Area | OpenCode example | Codex example |
| --- | --- | --- |
| Infrastructure | Shared official CDK stack, ARM64 Docker asset, IAM role, and outputs. | Same. |
| Build and startup | Shared Dockerfile, tools, user, entrypoint, environment inheritance, and error handling. | Same. |
| Assistant adapter | `agent_images/opencode/assistant.py`. | `agent_images/codex/assistant.py`. |
| Package/version | `opencode-ai` 1.18.30. | `@openai/codex` 0.163.0. |
| Inference | Bedrock Runtime by default. The endpoint field selects the startup model's native SDK. | Bedrock Runtime for GPT-5.6 Sol. The endpoint field selects the native Runtime or Mantle provider. |
| Model authentication | Refreshable execution-role provider; no exported snapshot. | Native AWS credential chain; no generated bearer-token snapshot. |
| Model authorization | Sample role allows Bedrock model invocation on all resources; the startup model is not an IAM allowlist. | Same Runtime policy. Mantle selections use regional account-project inference permissions. |
| Configuration | Additional `opencode.json`; explicit updater suppression. | Native provider arguments and an image-installed permission preset; approval policy is not overridden. |
| HTTP health and process checks | Shared health server and live/fresh work-lease reader. | Same implementation. |
| AgentCore work-event source | OpenCode event/tool hooks publish process-bound work leases. | Not implemented. No work lease is produced by this adapter. |
| Herdr native support | Supported by Herdr 0.9.5. | Supported by Herdr 0.9.5. |
| Current remote Herdr status | Host wrapper hint plus Herdr's active screen manifest. | Same mechanism, with Codex-specific screen/title rules. |
| Runtime health while work runs | `HealthyBusy` when a valid work lease exists. | Currently `Healthy` without a work-event reporter, even if Herdr sees working UI. |
| Validation boundary | See the dated cloud and local checks below. | Model changes need fresh native-client and shell-tool checks; see the dated results below. |

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
npm ci --prefix src/agentcore_runtime/cdk
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
aws sts get-caller-identity
docker version
```

If you use a named AWS profile, add `--profile YOUR_AWS_PROFILE` to CDK commands.
Refresh its SSO login first when needed. Do not store credentials in profile JSON or CDK context.

Create an ignored, repo-local location for deployment outputs:

```bash
mkdir -p -m 700 .local/deployments
```

## Step 2: bootstrap the target environment if needed

Check whether the account/region already has a suitable `CDKToolkit` stack.
If it does not, an authorized administrator must bootstrap it:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- bootstrap aws://ACCOUNT_ID/REGION
```

Replace `ACCOUNT_ID` and `REGION` with the intended environment.
Bootstrap is shared account infrastructure. Review its trust and CloudFormation execution policies with the environment owner.
Do not bootstrap another account or delete a shared bootstrap stack as application cleanup.

## Step 3: select a sample profile

| Profile | Agent and startup model | Network | Working directory |
| --- | --- | --- | --- |
| [codex-agentcore-profile-1](provision_profiles/codex-agentcore-profile-1.json) | Codex 0.163.0; `global.openai.gpt-5.6-sol` through Bedrock Runtime | PUBLIC; no VPC or mount | Image home, `/home/agent` |
| [opencode-agentcore-profile-2](provision_profiles/opencode-agentcore-profile-2.json) | OpenCode 1.18.30; `global.moonshotai.kimi-k3` | PUBLIC; no VPC or mount | Image home, `/home/agent` |
| [opencode-s3filesystem-agentcore-profile-3](provision_profiles/opencode-s3filesystem-agentcore-profile-3.json) | Same OpenCode image and Kimi K3 model | VPC with an existing S3 Files access point | Mount root, `/mnt/workspace` |

All three profiles select `"runtime"`. All Runtime and default inference regions are `eu-west-1`.
Both startup models use global cross-Region inference; an Ireland endpoint does not restrict model processing to the EU.
Each profile creates its own stack, execution role, and Runtime ARN. Sessions are instances of that deployment.

| Profile | CloudFormation stack | AgentCore Runtime name |
| --- | --- | --- |
| `codex-agentcore-profile-1` | `HerdrCodexRuntime` | `codex_agentcore_runtime_1` |
| `opencode-agentcore-profile-2` | `HerdrOpenCodeRuntime` | `opencode_agentcore_runtime_2` |
| `opencode-s3filesystem-agentcore-profile-3` | `HerdrOpenCodeS3FilesystemRuntime` | `opencode_s3filesystem_runtime_3` |

Profile filenames may contain hyphens. AgentCore Runtime names use letters, digits, and underscores, with a leading letter and at most 48 characters.

### Profile field review

| Field | Purpose and source of truth |
| --- | --- |
| `stackName` | Identifies the CloudFormation stack. It is separate from the Runtime resource name. |
| `runtimeName` | Names the AgentCore resource. It has different naming constraints and replacement behavior. |
| `region` | Selects the Runtime deployment region. CDK resolves the account from deployment credentials/context. |
| `image` | References one image definition. Package, version, Dockerfile, command, and hint are not copied into every sample. |
| `inference.bedrock-endpoint-type` | Required. Selects the native client and IAM policy. Accepts only `"runtime"` or `"mantle"`. |
| `inference.modelId` | Selects the startup model, not an IAM model allowlist. |
| `inference.region` | Optional. Defaults to the Runtime region. All three samples omit it. |
| `lifecycle` | Sets idle timeout and maximum lifetime in seconds. Both values affect the deployed resource. |
| `vpc` | Optional subnet/security-group bindings. Presence selects VPC mode; absence selects PUBLIC mode. |
| `s3Files.accessPointArn` | Selects the filesystem and mounted root. Requires `vpc`. |
| `s3Files.mountPath` | Declares the mount location and supplies the default working directory. |
| `s3Files.readOnly` | Controls whether the role receives filesystem write permission. |

Advanced overrides are optional and absent from the samples: `command`, `agentKind`, `workingDirectory`, `tags`, and `environment`.
They respectively override image argv, recognition hint, working directory, extra tags, and non-secret environment settings.
The parser rejects unknown fields and environment entries that duplicate derived endpoint, model, region, or working-directory settings.
The samples add no custom tags. Only explicit profile `tags` are applied; there are no automatic `Project`, `AssistantProfile`, or `ProvisionProfile` tags.
AWS-managed `aws:cloudformation:*` tags still appear on deployed resources.

Removed fields include `account`, `networkMode`, `s3Files.bucketName`, `s3Files.prefix`, `inference.project`, and `inference.retainedModelIds`.
CDK resolves the account from the authenticated Toolkit context. VPC presence determines network mode.
The filesystem sample uses access-point permissions. It needs no bucket name, prefix, or bucket lookup.
The old project/retained-model fields did not affect sample IAM and are now rejected.

### Configuration ownership

| Input | Source |
| --- | --- |
| Stack and Runtime names, deployment region, model endpoint/model/region, lifecycle, and optional network/storage | Selected provision profile. |
| Values referenced as `${NAME}` in the profile | Component-root `.env` only. Exported shell variables do not replace these values. |
| Package/version, Dockerfile, build arguments, default command, and recognition hint | Referenced `agent_images/NAME/image.json`. |
| AWS authentication and account identity | Normal CDK credential chain and Toolkit `CDK_DEFAULT_ACCOUNT`. Credentials do not belong in deployment files. |

The stack has no environment-variable lookup or profile-file read. It receives resolved properties.
CDK formats generated ARNs from the selected account, region, and resource names.
Missing bindings, invalid names, and unresolved account identity fail before resource synthesis.
The deployment region always comes from `profile.region`. Inference uses `profile.inference.region` when present, otherwise the deployment region.
ARM64, HTTP health/invocation, AWS IAM action names, and the service-created `DEFAULT` endpoint are implementation contract constants.
They do not contain customer account IDs, regions, model IDs, or network/storage identifiers.

### Bedrock endpoint selection

Use the exact field name and value:

```json
{
  "inference": {
    "bedrock-endpoint-type": "runtime",
    "modelId": "global.openai.gpt-5.6-sol"
  }
}
```

CDK uses this field for two operations. It selects inference permissions and sets the container's `BEDROCK_ENDPOINT_TYPE`.
The values are project-defined identifiers. The CDK application maps them to IAM and environment settings; they are not a built-in CDK enum.
The adapters require that value and select the matching native provider:

| Value | Codex provider | OpenCode SDK for the startup model | IAM |
| --- | --- | --- | --- |
| `"runtime"` | `amazon-bedrock-runtime` | `@ai-sdk/amazon-bedrock` (Converse) | Model invocation, streaming, and inference-profile discovery. |
| `"mantle"` | `amazon-bedrock` | `@ai-sdk/amazon-bedrock/mantle` | `bedrock-mantle:CreateInference` on regional account projects. |

Use Bedrock Runtime and Bedrock Mantle as display names. JSON and `BEDROCK_ENDPOINT_TYPE` use lowercase identifiers.
The parser rejects `inference.api`, `inference.endpoint-type`, missing values, display names, and alternate spellings.
Do not repeat `BEDROCK_ENDPOINT_TYPE` in profile `environment`; CDK derives it from the endpoint field.
For Mantle, choose a Mantle model ID and a supported inference region together. Runtime inference-profile IDs do not select Mantle models.
Endpoint selection does not translate model IDs or automatically switch endpoints after a failure.

OpenCode adds the selected model's SDK setting to `OPENCODE_CONFIG_CONTENT` and retains the other JSON settings.
If supplied, this environment setting must contain a JSON object. User configuration files are preserved.
The pinned Mantle loader uses Responses for normal models. Select a model compatible with that API.
Later model selections use OpenCode's native catalog; choose models compatible with the deployment's endpoint permissions.
Codex disables hosted web search for Runtime because that endpoint does not provide the tool.

### Model registration and limits

The pinned OpenCode catalog is checked for each selected model. Kimi K3 required explicit registration.
The shared OpenCode image registers Kimi K3 once in `agent_images/opencode/opencode.json`.
Its 8,192-token output limit is an application setting, not a claim about the vendor's maximum.
Both OpenCode profiles reuse that catalog entry. The profile chooses the model ID but does not repeat its metadata.

AWS documents a Kimi K3 Converse multi-turn limitation when earlier reasoning content is included again.
The current OpenCode provider uses Converse. Validate multi-turn and tool use before relying on this profile for work.
AWS recommends Chat Completions or Responses for Kimi K3. Changing the provider API needs a separate compatibility check.
The tested OpenCode conversation, attachment, and shell-time flow passed for Kimi K3 without disabling reasoning.
Kimi K2.5 and DeepSeek V3.2 offer regional inference in London and Stockholm, but their published regional lists do not include Ireland.

Ireland's Bedrock Runtime account retention setting is now `default`, as explicitly requested by the user for GPT-5.6 Sol.
Earlier Sol/Astra requests were rejected when that setting was `none`. `default` permits the model's AWS safety/abuse retention policy; it is not zero data retention.
An `ACTIVE` inference profile does not prove that the account's retention mode permits inference.
The managed zero-retention guard has an Ireland-only exception in its retention rules. Its other-region rules and invocation-logging restrictions remain in place.
Ireland's separate Mantle setting remains `none`. Do not add account-retention updates to CDK deployments or change other regions as part of a profile update.
The earlier GLM 5.3 results and superseded GPT-OSS/Mantle configuration are historical evidence, not the current startup model.

### Fill the shared network and storage bindings

Only `opencode-s3filesystem-agentcore-profile-3` requires network/storage variables.
The two PUBLIC profiles need no `.env` bindings. AWS authentication and account selection use the normal CDK credential context.
For the filesystem profile, real resource values belong in `src/agentcore_runtime/.env`, beside this README.

1. If `src/agentcore_runtime/.env` does not exist, run these commands from the repository root:

   ```bash
   cp src/agentcore_runtime/.sample.env src/agentcore_runtime/.env
   chmod 600 src/agentcore_runtime/.env
   ```

2. Fill every `REPLACE_WITH_...` value in `src/agentcore_runtime/.env`. Subnet and security-group variables are comma-separated lists.
3. Keep these variable references in the filesystem profile:

   ```json
   {
     "vpc": {
       "subnetIds": "${SHARED_VPC_SUBNET_IDS}",
       "securityGroupIds": "${SHARED_VPC_SECURITY_GROUP_IDS}"
     },
     "s3Files": {
       "accessPointArn": "${SHARED_S3_FILES_ACCESS_POINT_ARN}",
       "mountPath": "/mnt/workspace",
       "readOnly": false
     }
   }
   ```

CDK finds the component-root `.env` relative to `cdk/profile.ts`, not the caller's working directory.
Deployment bindings come only from that file. A CI job must supply its own ignored component `.env` when the selected profile requires bindings.
Missing filesystem variables, unfilled sample values, null resource bindings, and invalid IDs fail before synthesis.
Subnet/security-group CSV values become arrays. `$MODEL_ID` and `$INFERENCE_REGION` remain runtime-template placeholders.
The synthesized resources use the resolved values directly. There are no separate VPC/S3 CloudFormation parameter defaults that can silently retain old bindings.
Do not put AWS credentials in `.env`; authentication continues to use the normal AWS credential chain.

The access point selects the mounted filesystem and its root directory.
The profile requires only its ARN, mount path, and read/write choice in addition to VPC bindings.
The execution role receives access-point-scoped `s3files:ClientMount` and, for writable mounts, `s3files:ClientWrite`.
It also receives the filesystem metadata reads required for Runtime creation and mount setup.
`SHARED_S3_PREFIX`, direct-S3 read/list grants, and the bucket metadata custom resource have been removed.
There is no lookup Lambda or deployment-time SDK download in the current stack.

AWS recommends direct-S3 object reads for large-I/O performance. Those reads use IAM/bucket policies rather than access-point POSIX permissions.
This sample selects the access-point-only path. Mount readiness, a real model call, and file write/read checks passed after the directory-marker repair below.
Separate runtime sessions wrote and read 4 KiB and 8 MiB files with identical hashes. The test removed only its own files and directory.
These checks establish persistence across the tested session boundary. They do not qualify conversation checkpoints or every cold-read/performance case.

#### Repair an imported directory's ownership

The [AWS coding-agent sample](https://github.com/awslabs/agentcore-samples/blob/abab3d8beb684c79fc827a95a2d015e44e76dbbc/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e/coding_agents/infra/cfn-vpc.yaml) configures UID/GID `1000:1000`, root-directory mode `755`, and a managed S3 Files mount.
Our access point already matched those settings. However, its backing directory existed only through child objects uploaded to S3.
The directory marker was absent. S3 Files applied its documented default ownership `root:root` and mode `0755`, so the non-root agent could traverse the directory but could not create files.

Follow [AWS's POSIX directory-metadata procedure](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-posix-permissions.html):

1. Read the filesystem's bucket/prefix and access point's root path with `get-file-system` and `get-access-point`.
2. Resolve the directory marker key from that prefix and root path. Check it with `s3api head-object` before changing anything.
3. If the marker is absent, create only that zero-byte marker. Set `BUCKET_NAME` and `DIRECTORY_KEY` from the metadata read in step 1:

   ```bash
   aws s3api put-object --bucket "$BUCKET_NAME" --key "$DIRECTORY_KEY" \
     --metadata '{"file-owner":"1000","file-group":"1000","file-permissions":"0040755"}' \
     --if-none-match '*'
   ```

4. If a marker already exists, inspect its metadata and content headers first. Follow AWS's copy-in-place procedure, preserving unrelated metadata and content. Do not replace it with an empty object.
5. Verify the metadata with `head-object`, then test a fresh runtime session as UID 1000.
6. Follow the [AWS sample's separate-session test](https://github.com/awslabs/agentcore-samples/blob/abab3d8beb684c79fc827a95a2d015e44e76dbbc/01-features/01-harness/01-advanced-examples/14-s3-filesystem/README.md): write in session A, stop it, read in session B, and remove only the probe's files.

This is a targeted data-metadata repair by the storage operator. It does not change child-object ownership, the runtime user, or runtime IAM.
No new mount helper or provisioning loop is required. The bucket/prefix used for repair are discovered metadata, not additional CDK profile or `.env` bindings.

The file system, access point, mount targets, and Runtime must be in the same account and VPC.
Runtime subnets must overlap with mount-target Availability Zones. Allow NFS TCP 2049 in both security groups.
Match access-point POSIX ownership to the image's agent user, UID/GID 1000:1000.
The VPC also needs access to the Bedrock endpoint and any required tool services through suitable endpoints or egress.
The deployment principal must be able to create the AgentCore network service-linked role if it does not exist.
The runtime role receives separate, resource-scoped permissions for filesystem metadata reads and NFS client operations.
Do not apply the NFS `s3files:AccessPointArn` condition to metadata lookups. Cloud creation requires `GetAccessPoint` and `ListMountTargets` access.
For a customer-managed KMS key, add the required key-scoped decrypt permission before deployment; the example does not grant arbitrary KMS access.

AgentCore performs the mount when a session is invoked. The image does not install a custom mount daemon.
The launcher requires the configured mount before it starts OpenCode. It does not fall back to ephemeral workspace data.
These profiles mount coding files only. Conversation checkpoints and automatic recovery remain separate work.
Sessions using the same access point share mounted data. Use separate worktrees or directories for concurrent editing.

### Synthesize, review, and deploy

Run from the repository root. All three commands load the selected profile and `src/agentcore_runtime/.env`:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- synth \
  -c runtimeProfile=opencode-agentcore-profile-2
npm --prefix src/agentcore_runtime/cdk run cdk -- diff \
  -c runtimeProfile=opencode-agentcore-profile-2
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy HerdrOpenCodeRuntime \
  -c runtimeProfile=opencode-agentcore-profile-2 \
  --outputs-file "$PWD/.local/deployments/opencode-agentcore-profile-2.json"
```

For the filesystem example, first fill `src/agentcore_runtime/.env`, then synthesize and review `opencode-s3filesystem-agentcore-profile-3` before deployment:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy HerdrOpenCodeS3FilesystemRuntime \
  -c runtimeProfile=opencode-s3filesystem-agentcore-profile-3 \
  --outputs-file "$PWD/.local/deployments/opencode-s3filesystem-agentcore-profile-3.json"
```

To change a binding, edit `src/agentcore_runtime/.env` or the selected profile, then review `cdk diff`.
External `profileDirectory` context is rejected. Do not keep a second active set of profiles in a home-directory configuration folder.
No VPC, bucket, access point, or mount target is created by this stack.

## Step 4: deploy the Codex example profile

The `codex-agentcore-profile-1` settings select the Codex image and PUBLIC networking.
The container adapts the [AWS Codex sample](https://github.com/awslabs/agentcore-samples/tree/abab3d8beb684c79fc827a95a2d015e44e76dbbc/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e/coding_agents/codex).
It pins Codex 0.163.0 and uses Codex's native `amazon-bedrock-runtime` provider with the AWS credential chain.
It does not generate or export a one-time bearer token, disable approvals, or overwrite user configuration.

The example model is `global.openai.gpt-5.6-sol` through Bedrock Runtime in `eu-west-1`.
The adapter passes the inference region through `model_providers.amazon-bedrock-runtime.aws.region`; the native provider selects its endpoint URL.
Verify current model availability and your account's inference access before deployment.
Edit the selected profile's `inference.modelId` and optional `inference.region` to choose another supported model/region pair.

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- synth \
  -c runtimeProfile=codex-agentcore-profile-1
npm --prefix src/agentcore_runtime/cdk run cdk -- diff \
  -c runtimeProfile=codex-agentcore-profile-1
npm --prefix src/agentcore_runtime/cdk run cdk -- deploy HerdrCodexRuntime \
  -c runtimeProfile=codex-agentcore-profile-1 \
  --outputs-file "$PWD/.local/deployments/codex-agentcore-profile-1.json"
```

Codex uses the shared health server but has no work-event reporter. It currently provides readiness health only.
Do not treat process existence as active work. Long-running work can still reach the idle timeout.
Earlier Codex revisions and model selections passed cloud inference, a sandboxed shell tool, and attachment probes.
Long-duration behavior, broader tool and approval cases, and full credential rollover require separate validation.

Local validation built the ARM64 Codex image and started its CLI with networking disabled.
Both shared-image profiles were deployed to disposable test runtimes for cloud E2E validation.

### Codex sandbox configuration

Codex 0.163.0 can fail before it executes a shell tool on AgentCore.
With whole-root read access, its sandbox sees containerd rootfs aliases.
Codex tries to mask its daemon directory at those aliases. AgentCore denies creation of the parent directories.
The resulting `bwrap: Can't mkdir parents` error is not a failed shell command or model-authentication error.

The image uses the native `agentcore-workspace` permission preset in [codex-config.toml](agent_images/codex/codex-config.toml).
This is a Codex permission preset, not a CDK runtime profile or a Herdr connection profile.
It permits reads of `:minimal` system paths and writes in workspace roots and temporary directories.
It marks `.git`, `.agents`, `.codex`, and `.aws` under workspace roots as read-only.
It does not grant whole-root access, enable sandbox networking, or override the approval policy.

The build hook creates `/home/agent/.codex/config.toml` with mode `0600` and exclusive creation.
The launcher does not rewrite this file. A mounted or user-supplied configuration must retain the intended permission preset.
New runtime sessions use the new image. Existing sessions keep their image and process configuration.

The AWS sample's headless path uses `--yolo`. This image instead retains Codex's native sandbox with narrower filesystem permissions.
The shared Dockerfile can install this configuration through its existing adapter build hook.
No separate Codex Dockerfile or privileged container is needed for this fix.

Run the opt-in probe against an authorized deployment:

```bash
uv run --frozen python src/agentcore_runtime/tests/live_codex_sandbox.py \
  --runtime-arn "$RUNTIME_ARN"
```

The probe uses a fresh session and stops it in cleanup.
It checks workspace writes, protected metadata, hidden daemon/containerd paths, and a blocked network probe.
It also confirms that a file outside the workspace remains unchanged.
An unmounted parent can be sandbox-local temporary storage; a successful local write does not imply a host-file change.
The model check requires a completed `command_execution` event with successful `date` output. Model text alone does not pass.

For the interactive Herdr path, run the existing isolated probe with `--agent-kind codex --check-shell-time`.
That option requests `date` after the attachment checks. It does not approve a blocked dialog.

## Step 5: register the deployment in Herdr

Install the connector and link the root plugin manifest if needed:

```bash
uv sync --frozen --no-dev
herdr plugin link "$PWD"
```

Import OpenCode's CDK outputs:

```bash
.venv/bin/herdr-agentcore configure \
  --cdk-outputs .local/deployments/opencode-agentcore-profile-2.json \
  --stack HerdrOpenCodeRuntime \
  --profile opencode-agentcore-profile-2 \
  --config-dir "$(herdr plugin config-dir agentcore)"
```

Import the filesystem sample with its own output file, `--stack HerdrOpenCodeS3FilesystemRuntime`, and `--profile opencode-s3filesystem-agentcore-profile-3`.
For Codex, use its output file, `--stack HerdrCodexRuntime`, and a separate local connection profile name.
Add `--replace` only when replacing a saved connection profile.
The exported `ConnectionDescriptor` includes ARN, endpoint, explicit command, runtime-profile reference, and recognition hint.
Host credentials remain a local connector choice.
Use the numbered provision profile names as local labels when importing the three examples, unless you deliberately choose other labels.
Imports preserve an existing default. Check saved profiles before launching; older labels can still point to retired runtime ARNs.
Use `action new --profile NAME` to select a current profile, or run `set-default NAME` explicitly.
Follow the [existing-runtime guide](../../docs/CONNECT_EXISTING_RUNTIME.md) to open, verify, detach, and reattach a session.

## Launch command selection

The image definition declares the command. A provision profile can override it explicitly.
The contract receives validated, resolved argv. The connector has no default command and does not infer one from an image name.
The shared examples use `/app/run.sh`; this path is not an AgentCore or Herdr requirement.
It starts an assistant when the connector opens a new session; the container's default process is the health service.

Set `command` in the selected provision profile to override the image's argv:

```json
{
  "command": ["/opt/assistant/start", "--project", "/workspace/my project"]
}
```

Use the same profile during synth, diff, and deploy. Per-field context overrides, including `-c command`, are rejected.
The profile command changes connection output, not Docker `CMD` or installed files.
The executable must exist in the image. The recognition hint must match the assistant that it starts.

## Add a runtime for another project

1. Copy an example as `provision_profiles/NAME.json` inside the runtime component.
2. Set distinct `stackName` and `runtimeName`. Set the Runtime `region`; add optional tags only when needed.
3. Select the image with `image: "opencode"` or another repository image reference. Do not copy its build arguments or startup defaults.
4. Set `inference.bedrock-endpoint-type` to `"runtime"` or `"mantle"`, then set `inference.modelId`. Set `inference.region` only when it differs from the Runtime region. Verify model/API availability and retention eligibility.
5. Let CDK derive `AWS_REGION`, `BEDROCK_INFERENCE_REGION`, `BEDROCK_ENDPOINT_TYPE`, and `BEDROCK_MODEL_ID`. Do not repeat them in `environment`.
6. Reuse the shared env references to share VPC/S3 resources. For different resources, add variable names to `src/agentcore_runtime/.sample.env` and their real values to the adjacent `.env`, then reference those names in the new profile.
   Omit `vpc` and `s3Files` for PUBLIC networking. Keep both for a filesystem mount.
7. Omit `workingDirectory` to use the mount root, or the image home without a mount. Set it only for another existing directory.
8. Set `lifecycle` values in seconds. The sample's inference policy permits live model changes without enumerating model IDs.
9. Run type checks, tests, and `cdk synth -c runtimeProfile=NAME` from `cdk/`.
10. Review `cdk diff`, then deploy with the same profile and `.env`, and an outputs file under `.local/deployments/`.
11. Import that descriptor into a separate Herdr connection profile.
12. Test the model, a harmless shell tool, mounted files, multi-turn conversation, and attachment in a disposable session.

Do not copy the OpenCode source directory for each project. Model, region, storage, and lifecycle differences belong in provision profiles.
Adding a genuinely different agent environment requires an adapter and `image.json` under `agent_images/NAME/`, plus a profile that selects it.
Runtime ARN, region, command, and recognition hint still cross the small shared connection contract. The connector does not interpret storage or model settings.

No connector switch statement or assistant-name enum is needed.
The current stack supports Bedrock Runtime and Bedrock Mantle inference policies. Other inference services require an appropriate CDK policy extension.

### Sample model permissions

For the Bedrock Runtime API, the role grants `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on `*`.
It also grants `bedrock:ListInferenceProfiles` for discovery. It does not grant `bedrock:*` or account-retention administration.
`inference.modelId` selects the startup model. A compatible model change on the same endpoint needs no per-model IAM update.
Model availability, subscriptions, service controls, and the account's retention policy still apply.
Unused `inference.retainedModelIds`, `inference.project`, and `retainedModelIds` context values have been removed and are rejected.
Storage, runtime-role trust, ECR, and logging permissions retain their separate resource scopes.
An earlier revision deployed this invocation-policy change to the two then-existing EU stacks. The reviewed changes affected only their execution-role policies.
Two existing OpenCode sessions selected Claude Sonnet 5 (EU) and returned `SONNET5_LIVE_OK` after that update, without restarting their sessions.
The provision profiles' startup models were not changed for that live selection. All three current profiles use the Runtime policy shown above.

## Current validation

The latest completed verification is dated 2026-10-19. Runtime versions, assistant package versions, and descriptor version 1 are separate values.
The dated results record observations, not a live session inventory. Check current state before later operations.

### All profiles and six interactive sessions — 2026-10-19

Both current ARM64 images built successfully. TypeScript, 21 CDK tests, and all 212 Python tests passed with both image-test flags enabled.
Official CDK deploy commands completed for all three numbered profiles and reported no changes.
Codex remained at Runtime/DEFAULT version 4. Both OpenCode runtimes remained at version 1. Each runtime and its `DEFAULT` endpoint reported `READY`.
Final CDK diffs showed no changes. Ireland Runtime retention read back as `default`.

The connector imported the three current CDK output descriptors under their numbered profile names.
At the user's request, Herdr opened three tabs with two independent runtime sessions per profile.
All six assistants executed `date`, reported UID/GID 1000, and completed read-only directory-access checks.
Their measured times were between `2026-10-19T16:15:06Z` and `2026-10-19T16:15:15Z`.

| Profile | Current directory and observed access |
| --- | --- |
| `codex-agentcore-profile-1` | `/home/agent`; home and temporary paths passed write-permission checks. The native tool sandbox exposed read-only system paths and hid `/app`. No S3 Files mount is configured. |
| `opencode-agentcore-profile-2` | `/home/agent`; home and temporary paths passed write-permission checks. `/app`, `/etc`, and `/usr` were readable but not writable. `/root` was inaccessible. No S3 Files mount is configured. |
| `opencode-s3filesystem-agentcore-profile-3` | `/mnt/workspace`; the shared mount passed read, traverse, and write-permission checks in both sessions. Home and temporary paths remain runtime-local. |

These interactive checks inspected permissions without testing writes.
A separate disposable storage probe wrote 4 KiB and 8 MiB files in session A and read matching hashes in session B.
Its cleanup removed the probe's files and directory. All three storage-probe sessions received stop requests.
The six user-requested interactive sessions remained connected and available after verification; they were not disposable cleanup targets.

### Sol on native Bedrock Runtime — 2026-10-19

The Codex profile selects `global.openai.gpt-5.6-sol` through native Bedrock Runtime in `eu-west-1`.
The update replaced version 3's GPT-OSS/Mantle configuration. It changed the image and inference IAM, and removed `CODEX_BEDROCK_BASE_URL`.
The image uses the native `amazon-bedrock-runtime` provider without the earlier GPT-OSS tool-feature overrides.
CloudFormation reached `UPDATE_COMPLETE`. The Runtime and `DEFAULT` endpoint reached version 4 and `READY`.
The final CDK diff showed no changes. Outputs are saved in ignored `.local/deployments/codex-agentcore-profile-1.json`.

Readback before and after deployment confirmed Ireland Runtime retention mode `default`.
The earlier authorized retention change and Ireland-only guard exception remain separate account administration. This deployment did not change retention controls.

Fresh disposable sessions passed these checks:

1. Native sandbox workspace writes succeeded. Protected metadata writes were blocked. The outside host file stayed unchanged.
2. Containerd and daemon paths were hidden, and the network probe was isolated.
3. Sol executed `date` through its shell tool. The headless probe required a successful `command_execution` event.
4. An isolated Herdr server selected the default connection profile, recognized Codex, and received `HERDR-CLOUD=457` from Sol.
5. Process inspection found no static AWS credentials or provider tokens.
6. Detach and attachment preserved the original session. A follow-up returned `RESUMED:HERDR-CLOUD=457`.
7. The interactive tool call displayed `Ran date` and returned `2026-10-19T16:10:37Z`.
8. Both probe sessions received stop requests. The isolated Herdr server stopped.

The ARM64 image build and TypeScript check passed. Local tests passed 21 CDK cases and 203 Python cases.
That Python run enabled both Codex image checks and the isolated Herdr manifest check; nine other opt-in checks were skipped.
Codex work-health reporting, long-duration behavior, and full credential rollover remain unqualified.

## Historical validation

The following results describe earlier revisions and retired deployment instances.
Their retention modes, runtime versions, and pending checks do not replace the current validation above.

### GLM 5.3 and storage repair — 2026-10-19

An earlier Codex profile revision selected `global.zai.glm-5.3` through Bedrock Runtime in `eu-west-1`.
AWS documents Responses support for this model. The account's authorization, entitlement, regional availability, and inference-profile checks passed.
The CDK update changed only `BEDROCK_MODEL_ID`. The Runtime and `DEFAULT` endpoint reached version 2 and READY.
A fresh Codex session returned the expected model response. Another session passed the native sandbox checks and a real model-driven `date` tool call.
No adapter, image, or inference-permission change was needed for GLM 5.3.

Storage used the existing AWS sample-compatible access point. Its missing directory marker caused S3 Files to assign the imported directory default ownership `root:root` and mode `0755`.
The authorized repair created only the missing zero-byte marker with `file-owner=1000`, `file-group=1000`, and `file-permissions=0040755`, using conditional creation.
Fresh sessions then reported root ownership `1000:1000`. File write/read checks passed for 4 KiB and 8 MiB files.
Following the AWS sample's test pattern, session A wrote the files and session B read matching contents after A received a stop request. A cleanup session removed the probe's files and directory.
The S3 stack stayed at version 1; its image, IAM grants, VPC, access point, and mount configuration did not need changes.

During model research, AWS documentation and account-specific metadata showed that GPT-5/6 models did not allow `none`; GPT-OSS models did.
At that stage, the user selected GLM 5.3, so that update did not deploy GPT-OSS. A later version 3 used GPT-OSS/Mantle before Sol version 4 replaced it.
With explicit approval, the separate Ireland Mantle account setting was tightened from `inherit` to `none`.
Readback confirmed `none` on both Runtime and Mantle. The deployed GLM calls used Runtime with `none` enforced.

Local checks passed 21 CDK tests and 212 Python tests. Final Codex and filesystem CDK diffs showed no changes.
All owned model, sandbox, and persistence-test sessions received stop requests. The earlier failure evidence below is retained as history.

### Numbered profile deployments — 2026-10-19

All three numbered profiles deployed through official CDK in `eu-west-1`.
Each stack reached `CREATE_COMPLETE`. Each Runtime and `DEFAULT` endpoint reached version 1 and `READY`.
The Runtime names use underscores because AgentCore rejects hyphens. Profile filenames retain their numbered hyphenated names.
Final CDK diffs showed no differences. Connection outputs are in the matching `.local/deployments/NAME.json` files.

| Profile | Cloud smoke result |
| --- | --- |
| `codex-agentcore-profile-1` | Healthy startup and Codex 0.163.0 verified. Sol inference was rejected by account retention mode `none`. |
| `opencode-agentcore-profile-2` | Healthy startup, OpenCode 1.18.30, and a real Kimi K3 response passed. |
| `opencode-s3filesystem-agentcore-profile-3` | Healthy startup, required mount, and a real Kimi K3 response passed. Directory creation failed on the mounted root's POSIX permissions. |

No static credential snapshots were present in the prepared launcher environments.
All four isolated smoke-test sessions received stop requests. Filesystem tests could not create their temporary directory, so file write/read qualification was not reached.
The account retention setting was re-read as `none`; it was not changed.
AWS reported no custom application tags on any of the three runtimes. Their deployed environment contains no `OPENCODE_CONFIG` or `OPENCODE_CONFIG_CONTENT` entry.
The OpenCode launcher still creates its small process-local SDK-selection overlay, as described above.

Local checks passed 21 CDK tests and 212 Python tests, including both image checks.
CDK built/published the two assistant images; both OpenCode deployments use the same image asset.
An initial concurrent Docker login caused a local keychain collision for Codex. A sequential retry succeeded without changing credential configuration.

### Old deployments retired — 2026-10-19

The user authorized removal of `HerdrCodexRuntime`, `HerdrOpenCodeRuntime`, `HerdrEuKimiK3Runtime`, and `HerdrEuGpt56SolRuntime` in `eu-west-1`.
Four known session stop requests succeeded. Two older sessions were already absent.
Official CDK destroy commands used the saved cloud assemblies, without applying the edited replacement profiles.
All four stacks reached `DELETE_COMPLETE`. Direct AgentCore and IAM reads confirmed that their runtimes and execution roles were absent.
Shared VPC, S3 Files, and CDK bootstrap/asset resources were preserved. The unrelated runtimes remained READY.
Saved outputs for those deployment instances are historical records. The numbered replacements are described above.
The results below describe earlier revisions.

The configuration review passed 20 CDK tests, 212 Python tests with both existing ARM64 images, and synthesis of all three profiles.
Tests verify file-only bindings, rejected context overrides, profile-controlled regions/names/models, stable logical IDs, and IAM-policy dependencies.
The filesystem template has access-point permissions and no direct-S3 grants, bucket lookup, or Lambda function.
Those were local checks. Live file-I/O validation of the access-point-only policy was pending at that stage; the later storage tests passed.

The endpoint-selection revision passed 16 CDK tests, 212 Python tests, and synthesis of all three stacks.
Both ARM64 images built successfully. Tests cover exact endpoint values, rejected aliases, IAM, and container environment wiring.
Offline image checks verify OpenCode's resolved SDK for Runtime and Mantle, Codex CLI startup, and shared health behavior.
Codex provider arguments and Runtime web-search settings had adapter coverage. That revision had not yet received new cloud inference qualification.

The earlier field cleanup passed 14 CDK tests, 190 Python tests, and synthesis of all three stacks.
Both updated ARM64 images built successfully. Native CLI checks verified shared Kimi registration and independent inference-region configuration.
The later access-point-only revision removed that bucket lookup. File-I/O qualification followed in the storage tests recorded above.
The field audit is recorded above; duplicate/unused input fields are rejected rather than silently ignored.

The repo-local configuration migration passed 14 CDK tests and 189 Python tests.
All three profiles synthesized from repo-local env bindings without external profile-directory arguments.
Tests cover missing env values, CSV bindings, account/region validation, rejected external profile directories, and Git/image exclusion of local env files.
This configuration-source change was validated by synthesis and offline checks.

### Earlier profile-named VPC deployments

Earlier profile revisions deployed `HerdrEuKimiK3Runtime` and `HerdrEuGpt56SolRuntime`.
These results predate the current three-sample schema and access-point-only permissions. Renaming a source profile does not migrate an existing stack.
Both used the same verified, existing VPC and S3 Files access point. Local bindings used `src/agentcore_runtime/.env`; outputs were stored under ignored `.local/deployments/`.
Both Runtime/DEFAULT endpoints reached version 1 and READY. Final CDK diffs showed no changes.
The examples in Git contain env references, with a tracked `.sample.env` template.

| Check | Kimi K3 | GPT-5.6 Sol |
| --- | --- | --- |
| CDK deployment and OpenCode startup | Passed. | Passed. |
| Required mount and `/mnt/workspace` working directory | Passed. | Passed. |
| Real model response | Passed. | Rejected by the account's `none` retention policy. |
| Detach, attachment, and conversation follow-up | Passed. | Not reached. |
| Shell time command | Returned `2026-10-18T22:46:25Z`. | Not reached; no time answer was produced. |
| Probe cleanup | Stop request accepted; isolated server stopped. | Stop request accepted; isolated server stopped. |

Kimi's UI showed the actual `date -u '+%Y-%m-%dT%H:%M:%SZ'` tool output and the matching model response.
This short flow did not reproduce the general Kimi Converse reasoning-history limitation. It does not qualify every tool or conversation shape.
No shared S3 files were changed by those prompts. File-write testing had not run at that stage; later separate-session tests passed.

Cloud testing exposed missing S3 Files metadata permissions. The stack now separates metadata reads from mount/write grants.
The initial temporary-name stack and the superseded Astra stack were removed. Those two profile-named deployments were later retired before the numbered replacements were created.
The attempted retention update was denied; the account stayed at `none`. The user required that setting at that stage.
The later Ireland-only authorization changed Runtime retention to `default`; see the current model and retention section above.
That earlier final control-plane check confirmed `none`, identical network/filesystem bindings, and removal of the superseded Astra runtime.
Both a minimal Sol request and its Herdr E2E attempt failed on that policy. Do not interpret an `ACTIVE` model profile or READY Runtime as successful inference.

### Local and earlier validation

The `agent_images/`, `provision_profiles/`, and `cdk/` layout passed 189 Python tests with both rebuilt ARM64 images and ten CDK tests.
The checks cover model registration in the pinned OpenCode CLI, mount readiness, VPC/S3 template wiring, profile defaults, and shared image assets.
Kimi passed a deployed VPC/S3 Files and Herdr E2E flow with private, populated resource bindings. Checked-in bindings remain unpopulated templates.
GPT-5.6 Sol inference was blocked by the regional retention policy at that stage. An earlier Astra deployment reached READY but failed inference for the same reason.

The flat adapter layout built both ARM64 images and passed 184 Python tests with both image flags.
Six CDK tests, TypeScript checks, package checks, and documentation checks passed.
These are local checks of the directory change. The cloud results below describe the earlier deployed images.

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

The initial model prompts prohibited tool use and file changes. Those tests did not qualify sandbox execution or the full approval/keyboard matrix.
Codex also completed a supplemental non-interactive model request with stdin closed.

Codex displayed two startup warnings. Inspection found a missing system `bubblewrap` executable, with a reported bundled fallback, and embedded mode selected by command-line configuration overrides.
Those warnings did not block the tested model/attachment flow. The later sandbox checks are recorded below.
The warning panel opened with the raw `CSI 12~` sequence; the logical F2 probe did not open it. Full function-key compatibility remains unverified.

All probes requested stop for their own sessions and stopped their isolated Herdr servers.
Both temporary stacks were destroyed, and control-plane lookups confirmed that both test runtimes no longer exist.
The OpenCode stack's first deletion timed out in the CloudFormation resource handler. After confirming the runtime was already absent, a second `cdk destroy` completed.
Shared CDK asset storage remains under its normal retention policy. The existing default deployment stayed READY; the temporary test deployments were not promoted to it.

### Persistent deployments after qualification

After committing the implementation, both named profiles were deployed as persistent CDK stacks in `eu-west-1`.
The OpenCode runtime and DEFAULT endpoint reached version 2 and READY. Codex reached version 1 and READY.
That Codex revision used its declared `us-east-2` Mantle inference endpoint. Those deployment instances were later retired; the numbered Codex replacement now uses native Runtime in Ireland.
Herdr was reinstalled and relinked to the committed connector, then registered `opencode-agentcore-runtime` and `codex-agentcore-runtime` from CDK outputs.
OpenCode remained the default connection profile at that stage. Later numbered imports preserve an existing default until it is explicitly changed.

Fresh sessions on both persistent deployments passed real model calls, native recognition, credential inspection, detach/attachment, conversation continuity, and stop requests.
OpenCode also passed work/question/reply and process-death health checks on the persistent deployment.
The probes stopped only their disposable sessions and isolated Herdr servers. Those two deployments stayed available until their later authorized retirement.

### Codex sandbox fix qualification

After the initial deployment, interactive `date` requests reproduced the containerd-alias sandbox failure.
The native permission preset fixed that failure while retaining sandbox restrictions.
The new image passed the following checks on a disposable runtime and on the persistent Codex deployment:

| Check | Result |
| --- | --- |
| Native sandbox loads the image-installed preset | Passed; configuration mode is `0600`. |
| Workspace file write | Passed. |
| `.git/config` write | Denied. |
| File outside the workspace | Hidden inside the sandbox; host contents remained unchanged after a write attempt. |
| containerd and Codex daemon paths | Not accessible. |
| Network probe | Blocked. |
| Real model shell tool | A completed `command_execution` event ran `date` successfully. |
| Herdr interactive tool after detach/attachment | Passed on the persistent deployment; the UI showed `Ran date` and its UTC output. |

The persistent Codex runtime and DEFAULT endpoint reached version 2 and READY.
The deployment diff changed only the Codex container image. OpenCode was not redeployed.
The new image also passed model/role/recognition, attachment, conversation continuity, and stop checks in isolated Herdr servers.
All probe session stop requests were accepted. The isolated servers were stopped, and the disposable sandbox-test stack was destroyed.
Existing user sessions were not replaced; they need a new runtime session to use the updated image.

Local validation passed 184 Python tests with both image flags, six CDK tests, and TypeScript checks.
This qualifies the tested command and isolation cases. It does not qualify every tool, approval dialog, or long-running workload.

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
The sample inference policy does not restrict model IDs. Existing sessions can select other available models without a retained-model list.
CDK does not inspect and merge arbitrary existing IAM policies. Review changes to invocation actions, role trust, and storage access before applying them.

Stop the selected deployment's sessions before destruction:

```bash
npm --prefix src/agentcore_runtime/cdk run cdk -- destroy HerdrOpenCodeS3FilesystemRuntime \
  -c runtimeProfile=opencode-s3filesystem-agentcore-profile-3
```

CDK bootstrap repositories and their asset retention are separate from runtime-stack destruction.
Do not delete a shared asset repository as part of a runtime teardown.

## References

- [AWS CDK application and construct best practices](https://docs.aws.amazon.com/cdk/v2/guide/best-practices.html).
- [AgentCore filesystem configuration and VPC requirements](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html).
- [S3 Files backing-bucket permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-prereq-policies.html).
- [Kimi K3 model, regions, and Converse limits](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-moonshot-ai-kimi-k3.html).
- [GPT-5.6 Sol model and regions](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html).
- [GLM 5.3 APIs, regions, and reasoning settings](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-zai-glm-5-3.html).
- [GPT-OSS 120B endpoints and APIs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-120b.html).
- [Bedrock regional data-retention controls](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html).
- [Official AgentCore CDK resource](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore.CfnRuntime.html).
- [Official Docker image assets](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_ecr_assets.DockerImageAsset.html).
- [CDK bootstrapping](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html).
- [AWS Codex sample collection](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/04-coding-agents/03-code-agents-competition-e2e/coding_agents).
- [Codex with Amazon Bedrock](https://developers.openai.com/codex/amazon-bedrock).
- [Pinned Codex Runtime endpoint and AWS signing](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/model-provider/src/amazon_bedrock/runtime.rs).
- [Pinned OpenCode native Runtime and Mantle providers](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/provider/provider.ts).
- [Pinned Codex permission-profile compiler](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/config/permissions.rs).
- [Pinned Codex daemon mount masking](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/linux-sandbox/src/daemon_mounts.rs).
- [Herdr 0.9.5 status detection](https://herdr.dev/docs/0.9.5/agents/#how-status-works).
- [Herdr integration behavior](https://herdr.dev/docs/0.9.5/integrations/).
- [Pinned Codex detection rules](https://github.com/herdrdev/herdr/blob/v0.9.5/src/detect/manifests/codex.toml).
- [Pinned OpenCode detection rules](https://github.com/herdrdev/herdr/blob/v0.9.5/src/detect/manifests/opencode.toml).
- [Connection contract](../runtime_contract/README.md) and [ASD-STE100-style writing rules](../../agent.md#documentation-style-asd-ste100-style-english).
