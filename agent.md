# Coding agent instructions

## Read first

1. Read [README.md](README.md) for the project goal and commands.
2. Read [requirements](docs/REQUIREMENTS.md) for scope and acceptance criteria.
3. Read [design](docs/DESIGN.md) for architecture, terminology, and validation evidence.
4. Read [plugin guideline review](docs/PLUGIN_GUIDELINES_REVIEW.md) for the Herdr contract.
5. Read [session management proposal](docs/SESSION_MANAGEMENT_PROPOSAL.md) before you change hosting or recovery design.
6. Read [existing-runtime onboarding](docs/CONNECT_EXISTING_RUNTIME.md) before changing registration or launch behavior.

The project connects Herdr to interactive assistants on AgentCore Runtime.
It contains three components: AWS CDK infrastructure, the connector, and a small shared contract.
Read each component's README before changing that component.
The hosting target is **EC2 management and coordination → AgentCore OpenCode workers**.
The laptop provides access and viewing. Laptop-hosted management remains a development option.

Follow Herdr's workspace, tab, pane, and live-agent model.
Use Jindouyun only as a reference for execution concepts.
Exclude Cognito, end-user accounts, per-user runtime ownership, and a separate customer registry service.
S3 Files persistence for coding files, configuration, skills, and OpenCode state is in scope.
CDK configures an existing S3 Files mount for the filesystem profile. Mount readiness, `/mnt/workspace` startup, and 4 KiB/8 MiB cross-session file tests passed.
Per-binding namespaces, persistent home/configuration, skill discovery, and conversation checkpoints remain pending or unqualified.

## Repository conventions

- Keep exactly three directories under `src/`: `agentcore_runtime/`, `herdr_plugin/`, and `runtime_contract/`.
- Keep runtime modules directly in `src/agentcore_runtime/`. Do not add a second folder with the same name.
- Each component owns its README, implementation, and tests. Infrastructure uses npm/CDK; the connector and contract use Python packaging.
- Both applications may depend on the contract. Neither may import the other application's implementation.
- Keep the contract free of AWS, Docker, Herdr, and filesystem operations. Its Python consumer and TypeScript deployment shape use standard libraries only.
- Keep assistant-specific images, models, health hooks, and deployment behavior in the runtime component.
- Keep image sources under `agent_images/`, with `common/`, `opencode/`, and `codex/` children. Do not add an `image/` subdirectory inside an adapter.
- Keep deployment inputs in `provision_profiles/`. Keep CDK source, npm files, CDK configuration, and CDK tests in `cdk/`.
- Keep assistant comparisons and status-detection evidence in `src/agentcore_runtime/README.md`. Do not add READMEs under `opencode/` or `codex/`.
- Use official AWS CDK constructs and CLI for infrastructure. Do not reintroduce custom Boto3 create/update loops or a runtime provisioning executable.
- Select runtime settings by named JSON provision profiles. The samples are `codex-agentcore-profile-1`, `opencode-agentcore-profile-2`, and `opencode-s3filesystem-agentcore-profile-3`, not an enum. Keep profile references distinct from Herdr recognition hints and local connection labels.
- Keep reusable build arguments, explicit startup argv, and the recognition hint in each image's `image.json`. Profiles reference images and do not repeat those defaults.
- Keep requirements, design, proposals, and reviews in `docs/`.
- Keep `README.md`, `AGENTS.md`, and `agent.md` at the root.
- Keep the manifest, packaging files, and lockfile at the root. Keep CI configuration in `.github/`.
- Use public Herdr plugin, CLI, and socket interfaces. Do not change Herdr core.
- Inspect Git status, diffs, and relevant history before changes. Commit, push, or publish only on request.
- Investigate unfamiliar files before changes. Ask about each file or directory before a cleanup deletion.
- Preserve `.venv/`. The linked plugin uses its entrypoints.
- Keep generated environments, build output, and caches ignored by Git.
- Preserve licenses and attribution, including runtime-image copies.
- The `herdr/`, `agentcore-samples/`, and `agentcore-sdk-python/` research checkouts were removed. They are not dependencies.
- Use official versioned documentation or the installed SDK for research. Keep any future reference checkout ignored and outside distributions.
- Keep deployment inputs in repo provision profiles plus ignored `src/agentcore_runtime/.env`. Keep `.sample.env` beside it and document all three samples in the component-root README. Do not load a repository-root `.env` or external provision profile directories.
- Keep generated deployment outputs under ignored `.local/deployments/`. Herdr continues to manage its own operational connection configuration and state.
- Keep user credentials, connection records, and transcripts out of Git.
- Never commit credentials, real account/resource identifiers, populated deployment files, or signed URLs.
- Use placeholders or standard fictional account IDs in tests and examples.
- Before a commit, run the privacy guard on working files, the index, and history. Do not print matched values.

## Documentation style: ASD-STE100-style English

Apply these rules to all project documentation, including every component README.
They are a project style guide, not a claim of formal ASD-STE100 compliance.

1. Use short sentences. Aim for one main idea per sentence.
2. Prefer active voice. Name the component or person that performs an action.
3. Use imperative verbs in procedures. Put one main action in each numbered step.
4. State a condition before its action. For example: “If the original PTY exists, reattach to it.”
5. Use the same term for the same concept. Keep compute, connection, agent work, and persistent data distinct.
6. Define unfamiliar abbreviations at first use, or refer to the design glossary.
7. Use simple, concrete words. Avoid idioms, vague promises, and unnecessary modifiers.
8. State limits with units. State the scope of a stop, retry, update, or deletion.
9. Label implemented behavior, local tests, cloud tests, and planned work separately.
10. Preserve exact commands, API identifiers, paths, requirement IDs, and technical terms.
11. Preserve useful diagrams and source links. Update relative links when files move.
12. Do not rewrite licenses, third-party notices, or exact quoted error messages to fit this style.

## Implementation map

Version: `0.1.0`, experimental. Supported hosts: macOS and Linux, Python 3.11+, Herdr 0.9.5+.
Python dependencies use uv; the CDK project uses npm. AgentCore SDK is pinned to `1.24.1`.
Image versions are declared in the image definitions: OpenCode `1.18.30` and Codex `0.163.0`.

| File | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Declare five actions and pane entrypoints. |
| `src/herdr_plugin/herdr_agentcore/cli.py` | Parse connection commands, import descriptors, display menus, and confirm stop. |
| `src/herdr_plugin/herdr_agentcore/models.py` | Extend connection data with host identity selection and version-1 records. |
| `src/herdr_plugin/herdr_agentcore/storage.py` | Store configuration and records. Sync atomic writes and enforce local locks. |
| `src/herdr_plugin/herdr_agentcore/sessions.py` | Coordinate create, attach, selection, and stop. |
| `src/herdr_plugin/herdr_agentcore/agentcore.py` | Resolve credentials, sign WebSockets, call stop, and classify errors. |
| `src/herdr_plugin/herdr_agentcore/connector.py` | Process shell frames, launch once, reconnect, and handle termination. |
| `src/herdr_plugin/herdr_agentcore/terminal.py` | Manage raw mode, nonblocking output, input, resize, and detach. |
| `src/herdr_plugin/herdr_agentcore/herdr.py` | Call public Herdr APIs and publish connection metadata. |
| `src/runtime_contract/agentcore_contract/` | Validate and serialize versioned connection descriptors without side effects. |
| `src/agentcore_runtime/cdk/app.ts` | Select a named provision profile and instantiate the CDK stack. |
| `src/agentcore_runtime/cdk/runtime-stack.ts` | Define CfnRuntime, IAM, image assets, storage/network parameters, and connection outputs. |
| `src/agentcore_runtime/provision_profiles/` | Declare deployment settings. New profiles do not require connector branches. |
| `src/agentcore_runtime/agent_images/common/` | Share image build, startup, mount readiness, health, telemetry, and license. |
| `src/agentcore_runtime/agent_images/codex/` | Supply the Codex adapter, native permission preset, build-time configuration, and attribution. |
| `src/agentcore_runtime/agent_images/opencode/` | Supply the OpenCode adapter, configuration, dependency warmup, and activity-event plugin. |
| `src/*/tests/` | Hold each component's tests and applicable live probes. |

## Preserve these contracts

1. **Identity:** use the existing connection UUID as the execution binding. Herdr owns live names and pane organization. Full UUIDs are authoritative.
2. **Unreleased formats:** no profile version has been publicly released. Internal version fields do not impose backward compatibility. Validate the current format without inferring missing fields.
3. **Launch:** sync the launch attempt before sending it. Never replay an uncertain command or user input.
4. **Attach:** require the original PTY after a previous launch. Inspect the shell confirmation's `reconnected` flag. A network failure does not prove process death.
5. **Detach:** close the WebSocket without a shell-shutdown frame. Detach does not stop compute.
6. **Stop:** obtain explicit confirmation and the local lock. Stop targets the whole runtime session. The version-1 `stopped` label means AWS accepted the request; no completion waiter exists.
7. **Errors:** retry classified transient failures within the reconnect window. An explicit `RetryableConflictException` can be retried; an unknown HTTP 409 cannot. Do not display raw AWS responses or signed URLs.
8. **Terminal:** await nonblocking writes. Backpressure must not block timers, resize, or detach. Restore terminal modes without waiting for output to drain.
9. **Herdr responses:** structured success has `id` and `result`, not necessarily `ok: true`. Quiet commands can succeed with empty stdout; use their exit status.
10. **Agent status:** use the explicit `agent_kind`. Clear inherited hints when it is absent or null. Never infer OpenCode from an ARN or command.
11. **Profile selection:** explicit `--profile` takes precedence over `HERDR_AGENTCORE_PROFILE`, then saved `default_profile`. Forward action overrides through Herdr's public `--env` option.
12. **Profile defaults:** the first saved profile becomes default. Later saves preserve that choice. Require explicit selection when no default is saved; do not infer it from names or counts.
13. **Deployment:** use `cdk synth`, `cdk diff`, and `cdk deploy`. CDK owns assets and stack updates. Export connection fields as CloudFormation outputs; never write Herdr profiles from infrastructure code.
14. **Permission updates:** each sample role permits both Bedrock Runtime invocation and Mantle inference, independently of the startup endpoint. Runtime has no model-ID allowlist; Mantle grants target projects in the configured inference region and account. Keep actions limited to inference/discovery. Review IAM changes; CDK does not merge arbitrary existing policies or provide cross-stack transactions.
15. **Runtime credentials:** the OpenCode adapter uses `AWS_PROFILE=default`; both adapters use native role providers. Do not export credential snapshots. Keep `OPENCODE_DISABLE_AUTOUPDATE=1` in the OpenCode launch and warmup environment.
16. **External samples:** accept explicit launch commands. Runtime-specific initialization and credential repair belong to the image owner. Do not add such behavior to the generic connector.
17. **Activity:** track actual work, including concurrent tool calls and known child tasks. Waiting on one tool must not hide other active work. Unknown child activity remains conservatively busy.
18. **Health leases:** write metadata only. Renew every 10 seconds while busy. Accept only live PID/start-tick matches within 45 seconds. Never add an advancing AWS `time_of_last_update`.
19. **Compute limits:** the deployed microVM has 900 seconds idle timeout and 28,800 seconds maximum lifetime. Busy reporting does not extend the maximum or preserve files.
20. **Durability target:** use recorded S3 Files paths for repositories, configuration, skills, and recovery state. Validate mount and SQLite behavior. Keep sockets, PIDs, and live leases ephemeral.
21. **Shared sessions:** one runtime session per independent agent is the default. Before additional shells, implement separate process/shell stop and whole-session stop. Do not mark ordinary build shells as OpenCode agents.
22. **Hosting:** run the manager, connectors, and coordinator on EC2 for unattended use. Retain management state separately from worker state. Start with one active manager; local locks do not coordinate multiple hosts.
23. **Authentication:** EC2 needs IAM/environment setup, not a new plugin protocol. Use `aws_profile: null` and the instance role. Keep human SSO/SSM access and worker execution-role access separate.
24. **Access:** standard SSM can run the Herdr TUI on EC2 without SSH keys. Native Herdr remote-machine access uses SSH. ECS Exec is not a replacement for that SSH protocol.
25. **Contract:** use descriptor version 1 and `agentcore-shell-v1`. Export ARN, region, endpoint, command, and optional agent kind. Keep host credentials and execution IDs local to the connector.
26. **Launch command:** require explicit argv in every contract/connection profile. Image definitions declare the default command; provision profiles can override it. Reject per-field CDK context overrides. Never infer argv or the Herdr hint from the image name. Overrides do not install files or change container `CMD`.
27. **Codex example:** use the native Bedrock AWS credential provider. Do not override approval policy. Install the native restricted permission preset at build time; do not rewrite user configuration at startup. Cloud model/attachment, `date` tool, and scoped isolation checks passed. Its health service reports readiness only; broader tools and long-duration behavior remain unqualified.
28. **Status sources:** Herdr supports both example kinds. Current remote status comes from active screen/title manifests through the host wrapper hint. Codex's missing work reporter is an AgentCore-health gap, not a lack of Herdr native detection.
29. **Provision settings:** keep region, startup model, lifecycle, and optional VPC/S3 bindings in profiles. Derive network mode from VPC presence, account from CDK, inference region from Runtime region unless overridden, and working directory from the mount unless overridden. Reject duplicate derived environment keys and unused legacy model-permission fields.
30. **Storage:** only the filesystem sample requires `src/agentcore_runtime/.env` bindings: subnets, security groups, and the S3 Files access point. The access point selects the mount root. Do not add `SHARED_S3_PREFIX`, direct-S3 grants, or a bucket metadata lookup to this access-point-only sample. It follows the AWS sample's UID/GID 1000 design. For imported root-owned directories, use AWS's documented directory-marker POSIX metadata repair after inspection and authorization; do not add a new mount or privilege mechanism. Separate-session 4 KiB/8 MiB write/read checks passed after that repair; broader recovery/performance qualification remains separate.
31. **Model evidence:** the three samples specify only `inference.modelId`. OpenCode uses native catalog routing, including the image's single Kimi K3 entry and its Runtime SDK metadata. Codex defaults to its native Runtime provider for `global.openai.gpt-5.6-sol`. An optional `inference.bedrock-endpoint-type` override accepts exactly `"runtime"` or `"mantle"`. CDK exports `BEDROCK_ENDPOINT_TYPE` only for an explicit override; IAM permits both endpoints regardless. OpenCode creates its SDK-selection overlay only for that override. Codex has separate endpoint-specific providers and catalogs. Reject invalid explicit values, old field names, and duplicate environment settings. Earlier cloud results do not qualify a different endpoint, model, or image revision.
32. **Retention:** the user explicitly authorized an Ireland-only exception to the zero-retention guard, Runtime mode `default`, and later Mantle mode `default`. A separate agent applied and verified the Mantle change. Managed policy `EnforceBedrockZeroRetention` v2 still excludes `eu-west-1` from its three retention-deny statements; its other-region rules and both logging-deny statements are unchanged. Both Ireland account settings are `default`. Keep account/privacy administration separate from profile deployment. For administrative Bedrock calls, use the authorized IAM identity with SigV4; the ambient Bedrock bearer key has only limited permissions. Do not broaden this exception or change other regions without authorization.
33. **Configuration authority:** resolve component `.env`, the selected profile, and its image definition once at the CDK entrypoint. Pass resolved properties into the stack. Only `runtimeProfile` selects project configuration; reject per-field context overrides. Profile bindings must not fall back to or be overwritten by ambient shell variables. Keep authenticated account selection in the CDK Toolkit and fail if it is unresolved. Preserve construct IDs and the generated IAM-policy dependency when refactoring.
34. **Tags:** add no automatic application tags. Apply custom tags only when explicitly declared in a provision profile. The three samples declare none. AWS-managed CloudFormation tags are separate.

The SDK's `ShellSession.close()` detaches. Its high-level iterator hides confirmation frames.
Inspect the pinned implementation before changing transport behavior.

## Validation

Run from the repository root:

```bash
uv sync --frozen
uv run --frozen ruff check src
uv run --frozen ruff format --check src
HERDR_TEST_BINARY="$(command -v herdr)" uv run --frozen pytest -q --tb=short
uv run --frozen python src/herdr_plugin/tests/repository_privacy.py
uv build --all-packages
uv run --frozen python src/runtime_contract/tests/check_distributions.py --dist dist
npm ci --prefix src/agentcore_runtime/cdk
npm run check --prefix src/agentcore_runtime/cdk
npm test --prefix src/agentcore_runtime/cdk
git diff --check
```

The Herdr test uses isolated config, state, and socket paths. It does not start a server or change the user's registry.
Without `HERDR_TEST_BINARY`, that test is skipped. Default tests make no AWS calls.
Node activity tests run when Node is installed.
The privacy guard checks working files, the index, and history without printing matched values.

Build and test a runtime image after runtime changes:

```bash
docker buildx build --platform linux/arm64 --load \
  -f src/agentcore_runtime/agent_images/common/Dockerfile \
  --build-arg ASSISTANT_DIR=opencode --build-arg NPM_PACKAGE=opencode-ai \
  --build-arg NPM_VERSION=1.18.30 --build-arg EXECUTABLE=opencode \
  -t herdr-agentcore-local:1.18.30 src/agentcore_runtime/agent_images
HERDR_RUNTIME_TEST_IMAGE=herdr-agentcore-local:1.18.30 \
  uv run --frozen pytest src/agentcore_runtime/tests/test_runtime_image.py -q --tb=short
```

The Docker tests verify configuration, native startup, real OpenCode activity, and crash cleanup.
The activity container has no network access and makes no model calls.
The image build preloads the plugin SDK so the default home works offline.
Running OpenCode processes need a restart to load a changed plugin.

`cdk synth` creates templates and asset metadata. `cdk deploy` publishes assets and changes AWS resources.
The manifest build is `uv sync --frozen --no-dev`. It installs the connector and contract, not runtime definitions.
Use `uv sync --frozen` for all development components. Test isolated installations in temporary environments to preserve the linked plugin.
Keep the connector version aligned with the manifest. Keep each package's metadata and module version aligned.
Update the shared lockfile when dependency resolution changes.

## Live probes

Obtain authorization and runtime/profile details before cloud operations.
Do not deploy resources, stop existing user sessions, or modify the user's Herdr setup as an incidental test.
Use disposable test sessions and explicit targets. Do not reuse a user's session as a probe.

| Script or option | Purpose |
| --- | --- |
| `src/herdr_plugin/tests/live_agentcore_smoke.py` | Check shell I/O, resize, and same-session attachment. |
| `src/herdr_plugin/tests/live_herdr_smoke.py` | Use an isolated Herdr server for new/model/attach/follow-up/stop tests. |
| `--connection-file` | Supply a validated descriptor to the Herdr probe. Its ARN must match the explicit test target. |
| `--check-runtime-role` | Check the owned launcher without the shim. |
| `src/agentcore_runtime/tests/live_runtime_activity.py --model-turn` | Check deployed health during work and a controlled question/reply. |
| `src/agentcore_runtime/tests/live_codex_sandbox.py` | Check the installed permission preset, filesystem isolation, and a real model shell-tool event in a fresh session. |
| Herdr probe `--check-shell-time` | Request a read-only `date` tool call after attachment checks. Do not approve blocked dialogs. |
| `src/herdr_plugin/tests/live_layout_probe.py` | Probe startup at selected dimensions in a fresh session. |

Supply `--runtime-arn`; use `--aws-profile` if needed.
Process checks require command-invocation permission and return credential-presence booleans only.
Live probes must stop their own sessions. The Herdr probe must also stop its isolated server.
Reject known update dialogs before sending model prompts. Wait for detached panes to close before targeting a later action.

## Current evidence and next work

### Latest verified state — 2026-10-19

These results are dated observations. Recheck live state before acting on a deployment or session.
AWS runtime versions, assistant package versions, and descriptor version 1 are separate values.

- The user authorized a complete rebuild of the three numbered profiles after removing the mandatory endpoint field. Each sample now contains only `inference.modelId`; Codex defaults to Runtime in its image, and OpenCode uses catalog metadata. An explicit advanced endpoint override remains optional. No sample deployment exports `BEDROCK_ENDPOINT_TYPE`.
- The six former user sessions were detached and received stop requests. Official CDK destroy deleted the three old stacks, and direct reads confirmed their runtimes and roles absent. The same stack names were recreated with new runtime ARNs; all Runtime/DEFAULT endpoints are version 1 and READY. The three saved numbered profiles were replaced from fresh outputs. Shared VPC, S3 Files, and bootstrap resources were preserved.
- Both rebuilt ARM64 images, TypeScript, 21 CDK tests, and 217 Python tests passed. All three core interactive E2E flows passed, including credentials, attachment, context follow-up, real `date`, and stop. Both OpenCode question/activity/process-death probes and the Codex sandbox probe passed. A smoke matcher now accepts whitespace after `RESUMED:`; its live rerun passed.
- Fresh OpenCode Runtime and Mantle calls passed on both profiles without an endpoint override. Same-conversation Kimi-to-Astra recall passed. Continuing that mixed history with GPT-OSS 20B through Mantle returned HTTP 400 Responses input validation. Codex simple-text switching passed; its encrypted-history limitation remains. Do not claim universal seamless cross-model history compatibility.
- Cross-session 4 KiB/8 MiB persistence passed, with probe files removed. All disposable sessions received stop requests and isolated servers stopped. Six new user sessions were opened in three replacement tabs and left connected after date/folder checks. One Kimi turn produced no final answer after about 132 seconds; a shorter follow-up succeeded. Discover current sessions before further operations. Final CDK diffs showed no changes, and both Ireland retention settings remained `default`.

### Earlier same-day verification

These results predate the model-only rebuild. Runtime versions and session identities refer to the previous deployment instances.

- The user authorized both-endpoint inference IAM. All three roles now permit Runtime invocation/streaming and inference-profile discovery plus region/account-project-scoped Mantle inference. The CDK updates changed only the role policies; all stacks reached UPDATE_COMPLETE. Runtime/DEFAULT versions remained 4, 1, and 1 and READY. TypeScript and 21 CDK tests passed.
- The delegated Ireland-only administration changed Mantle retention from `none` to `default`; Runtime remained `default`. The complete managed guard document and default version v2 were unchanged, preserving other-region and logging restrictions. The delegated agent verified both retention readbacks.
- Fresh native calls passed Global Astra through Runtime for all three profiles. Both OpenCode profiles also passed GPT-OSS 20B through Mantle with the Runtime startup environment unchanged. Mantle Astra returned model-not-found 404 in Ireland for both clients; the regional Mantle catalog did not include that model ID. Do not equate client-catalog presence with regional availability. All disposable probe sessions received stop requests.
- Model-switch debugging identified two distinct issues. OpenCode's unqualified Astra entry uses Mantle and was denied by the earlier Runtime-only role; the Global Astra entry uses Runtime and worked. The user subsequently authorized both-endpoint inference IAM and delegated the Ireland-only Mantle retention change. Keep that explicit authorization separate from the earlier diagnosis.
- Codex 0.163.0 retains encrypted reasoning across model changes. Fresh Astra/Luna calls and simple text-history switches passed. Sol tool-history switches to Astra/Luna stalled. A direct synthetic Responses comparison isolated the reasoning item: Sol replay and Astra without that item passed; Astra with that item stalled after HTTP 200 and `response.created`. Returning a disposable conversation to Sol recovered it. Use a fresh conversation for cross-model work until upstream compatibility is fixed; never rewrite the user's live history without explicit authorization.
- The diagnosis changed no runtime image or account control. All disposable probe sessions received stop requests. The six user-requested sessions were left intact, including the stalled Codex turns; do not assume they completed from the model label alone.

- The later all-profile verification ran official CDK deploy for all three numbered profiles; each reported no changes. Codex Runtime/DEFAULT remains version 4; both OpenCode runtimes remain version 1; all are READY. Both ARM64 builds, TypeScript, 21 CDK tests, and all 212 Python tests passed. Final CDK diffs showed no changes, and Ireland Runtime retention remained `default`.
- At the user's request, three Herdr tabs were opened with two independent sessions per current profile. All six passed real date and read-only folder-access checks. Codex and plain OpenCode use `/home/agent`; the filesystem profile uses `/mnt/workspace`. The three current descriptors were imported under their numbered profile names. Imports preserve an older saved default; use an explicit current profile or change the default only on request. These six sessions were left open for the user. Discover their current state before further operations; do not stop them as disposable probes.
- A separate storage recheck passed 4 KiB and 8 MiB writes in session A and matching reads in session B. Cleanup removed the probe's files and directory. All three disposable storage sessions received stop requests.
- Codex now uses `global.openai.gpt-5.6-sol` on native Bedrock Runtime in `eu-west-1`. The update replaced GPT-OSS/Mantle version 3, removed its endpoint/tool overrides, and changed inference IAM and the image. CloudFormation is UPDATE_COMPLETE; Runtime/DEFAULT version 4 is READY. The final CDK diff showed no changes. Outputs remain in ignored `.local/deployments/codex-agentcore-profile-1.json`.
- Fresh version-4 sessions passed Sol inference, native sandbox isolation, real `date` execution, and credential-presence checks. The isolated Herdr flow passed default selection, Codex recognition, detach/attachment, context-preserving follow-up, and an interactive `date` call. Both own sessions received stop requests, and the isolated server stopped. Codex work-health reporting and long-duration behavior remain unqualified.
- Ireland Runtime retention read back as `default` before and after that deployment. No account controls changed during the deployment. The ARM64 build, TypeScript check, 21 CDK tests, and 203 Python tests passed. Both Codex image checks and the isolated Herdr manifest check ran; nine other opt-in Python checks were skipped.
### Historical evidence

The following results describe earlier revisions. Their deployment versions, retention modes, and pending checks are not current instructions or current qualification gaps.

- An earlier Codex revision used `global.zai.glm-5.3` on Bedrock Runtime in `eu-west-1`. The profile-only model update reached Runtime/DEFAULT version 2 and READY. Fresh sessions passed actual GLM inference, native sandbox checks, and model-driven `date` execution. At that stage, the user selected GLM instead of GPT-OSS; both account retention interfaces reported `none`.
- The S3 Files permission repair follows AWS's sample identity and documented POSIX directory-marker procedure. The access point already used UID/GID 1000, but its implied S3 directory had no marker and therefore appeared root-owned. Conditional creation of only that zero-byte marker with owner/group 1000 and directory mode 0040755 fixed the mounted root. Fresh-session 4 KiB/8 MiB writes and reads passed, including matching data across separate runtime sessions. Probe files were removed and all own sessions received stop requests. No root execution, broad permission grant, new mount layer, or S3 stack update was needed.
- The GLM/storage revision passed 21 CDK tests and 212 Python tests. Final Codex and filesystem CDK diffs showed no changes. Persisted conversation/configuration checkpoints and broader cold-read/performance qualification remain separate work.
- All three numbered profiles first deployed in `eu-west-1` on 2026-10-19. Their stacks reached CREATE_COMPLETE; Runtime/DEFAULT versions were 1 and READY. Final CDK diffs showed no changes. The runtime names were `codex_agentcore_runtime_1`, `opencode_agentcore_runtime_2`, and `opencode_s3filesystem_runtime_3`. Outputs used the matching ignored `.local/deployments/*-1.json`, `*-2.json`, and `*-3.json` files. These were replacement instances after the old four were deleted.
- Both OpenCode runtimes passed real Kimi model calls. Initial Codex startup passed, but Sol inference was rejected by retention mode `none`. The initial S3 mount root reported UID/GID 0:0 and mode 0755 while the agent was 1000:1000. Temporary-directory creation was denied. The later authorized directory-marker repair resolved that storage failure; the later Ireland Runtime retention change enabled Sol.
- The numbered-profile revision passed 21 CDK tests and 212 Python tests. Cloud reads confirmed no custom application tags and no deployed OpenCode configuration JSON env entry. Both image assets published; a concurrent Docker keychain login collision was resolved by retrying Codex sequentially. All four own smoke-test sessions received stop requests. The user's root NOTICE deletion was preserved as unrelated work.
- On 2026-10-19, the user authorized removal of all four old project deployments in `eu-west-1`: `HerdrCodexRuntime`, `HerdrOpenCodeRuntime`, `HerdrEuKimiK3Runtime`, and `HerdrEuGpt56SolRuntime`. Stop requests succeeded for four known sessions; two older sessions were already absent. Official CDK destroy commands used saved assemblies. All four stacks reached DELETE_COMPLETE; direct AgentCore and IAM reads confirmed the runtimes and execution roles absent. Shared infrastructure and unrelated runtimes were preserved. Old deployment outputs are historical records, not live targets.
- Replacement profile filenames have suffixes `-1`, `-2`, and `-3`. Their runtimeName values use underscores, as required by AgentCore. Sample-name references are updated and automatic application tags are removed. Earlier local and cloud results describe earlier revisions.
- The CDK configuration review passed 20 CDK tests, 212 Python tests with both existing images, and all three syntheses. The entrypoint resolves file configuration once; the stack consumes properties. Per-field context and ambient binding overrides were removed. Logical IDs and the existing execution-policy dependency were verified. `SHARED_S3_PREFIX`, direct-S3 grants, and the bucket lookup were removed from the access-point-only sample; live file-I/O qualification was pending at that stage.
- The endpoint-selection revision introduced exactly `inference.bedrock-endpoint-type: "runtime" | "mantle"`. All three samples selected Runtime; Codex selected the global Sol ID and Runtime region. CDK and both native adapters consumed the choice. Sixteen CDK tests, 212 Python tests, both ARM64 builds, and all three syntheses passed. That revision had not yet received new cloud inference qualification.
- The field-cleanup revision contained exactly the three requested sample profiles. It removed account, bucket name, network-mode duplication, legacy model-permission fields, and repeated image/startup settings. Local checks passed 14 CDK tests, 190 Python tests, all three syntheses, and both ARM64 builds.
- Account selection is delegated to CDK. An earlier revision used a read-only SDK custom resource for bucket metadata; it was not cloud-qualified and has now been removed. Do not describe earlier cloud results as a test of the new access-point-only permissions or Codex/Sol sample.
- Repo-local configuration passed 14 CDK tests, 189 Python tests, synthesis of all three profiles, package/documentation checks, and a zero-finding privacy audit. `.env` is ignored and `.sample.env` is trackable. The configuration-source migration was validated by synthesis and offline checks.
- Sample Bedrock invocation IAM no longer uses a model-ID allowlist. The two EU stack updates changed execution-role policies only. Both existing OpenCode workers successfully used Claude Sonnet 5 (EU) after the update; profile startup models were not changed.
- Earlier source profiles deployed `HerdrEuKimiK3Runtime` and `HerdrEuGpt56SolRuntime`, both using the existing VPC/S3 Files resources. Those identities belong to the earlier profiles. Current sample names and network choices differ; read the selected profile before deployment.
- Both earlier EU Runtime/DEFAULT endpoints reached version 1 and READY, and both final CDK diffs showed no changes. The account retention mode was re-read as `none` at that stage; the superseded Astra runtime was confirmed absent.
- Kimi passed real model inference, required-mount startup, role inspection, attachment, follow-up, and a shell time command. Sol started on the mounted workspace but inference was rejected by the regional `none` retention policy. All own probe sessions received stop requests and isolated servers stopped.
- Deployment inputs live under `src/agentcore_runtime/`: tracked provision profiles with env references, ignored `.env` with real bindings, and tracked `.sample.env` with placeholders. Deployment outputs use ignored `.local/deployments/`. External `profileDirectory` is rejected.
- Cloud creation required separate S3 Files metadata reads, including `GetAccessPoint` and `ListMountTargets`, without the NFS-only access-point condition. The client mount/write grants retain that condition; no root client access is granted.
- Runtime source is grouped into `agent_images/`, `provision_profiles/`, and `cdk/`. At that earlier revision, samples were Codex/Sol PUBLIC, OpenCode/Kimi PUBLIC, and OpenCode/Kimi with VPC/S3 Files. Older deployed EU profile names remain historical evidence, not current sample files.
- VPC/access-point values resolve from the AgentCore Runtime component's `.env`. CDK supplies the account. The earlier read-prefix binding and bucket lookup have been removed. Legacy retained-model/project fields are rejected. Profiles do not duplicate image settings or derived launch environment.
- The new layout passed 189 Python tests with both ARM64 images and ten CDK tests. Native OpenCode model-catalog checks passed for both selected models. These are local checks, not live VPC/storage or Kimi multi-turn qualification.
- Adapter files now live directly under `opencode/` and `codex/`. Both flat-layout ARM64 images built locally and passed 184 Python tests with both image flags, six CDK tests, TypeScript, package, documentation, and privacy checks.
- The Codex native permission preset fixed AgentCore's containerd-alias bubblewrap failure. Whole-root read access was removed; workspace/temporary writes, protected metadata, and normal sandbox networking restrictions remain.
- A disposable deployment and persistent Codex version 2 passed native sandbox checks and real model `date` execution. An isolated Herdr probe also showed the interactive `Ran date` tool result after attachment. Runtime and DEFAULT endpoint are READY.
- The persistent update changed only Codex's image. Existing user sessions were not replaced. The test stack was destroyed; own probe sessions and servers were stopped.
- The sandbox change passed 184 Python tests with both image flags, six CDK tests, and TypeScript checks. The runtime README records the exact limits and test commands.
- The implementation was committed, then deployed as persistent OpenCode and Codex CDK stacks in `eu-west-1`. OpenCode reached runtime/endpoint version 2; Codex reached version 1; both are READY.
- Herdr was reinstalled/relinked to the committed connector. Both connection profiles were imported from CDK outputs, with OpenCode retained as default.
- Fresh persistent-deployment E2E probes passed both model/role/recognition/attachment/follow-up/stop flows. OpenCode activity health also passed. Only the probe sessions and isolated servers were stopped.
- Final pre-commit checks passed 183 Python tests with both image-test flags, six CDK tests, package checks, and privacy checks.
- The shared-image refactor unifies the example directory layout, Dockerfile, startup, environment handling, and health service. CDK staging isolates each selected adapter.
- Both refactored ARM64 images built successfully. The current change passed 180 Python tests with those images, six CDK tests, and TypeScript checks.
- Herdr 0.9.5 native support for both examples was confirmed from the installed CLI, official integration documentation, and pinned manifests. The runtime README records the exact detection basis and limitations.
- Synthetic Codex screens passed installed-Herdr `agent explain` checks for working and blocked states. This is not Codex cloud or full-UI qualification.
- Both shared images passed cloud model/role/default-selection/attachment/conversation/stop E2E probes on disposable runtimes. OpenCode also passed deployed work/question/reply and process-death health checks.
- Test compute was in `eu-west-1`; Codex retained its declared Mantle inference region `us-east-2`. The primary prompts performed no tool use or file changes.
- Codex startup reported missing system bubblewrap with a bundled fallback, and embedded mode due to CLI configuration overrides. The later sandbox fix qualified a shell tool and isolation cases. Full key handling remains unverified.
- All test-session stop requests and isolated-server cleanup completed. Both temporary stacks/runtimes were confirmed absent. One CloudFormation deletion stabilization timeout required a read-verified retry.
- The existing default deployment stayed READY. Disposable tests were not promoted into its profile.
- The CDK/profile implementation passed 174 Python tests with both image-test flags enabled, five CDK assertion tests, and synthesis for both named examples. Deprecated custom-provisioner tests were removed with that code.
- Runtime tests passed with local ARM64 images, including real OpenCode health transitions and Codex CLI startup without network access.
- The connector and Python contract build independent distributions. Infrastructure is a CDK project and has no Python wheel or console entrypoint.
- Documentation checks passed for 11 project Markdown files, 57 local links, and all 56 requirement IDs. Ruff, lockfile, package, and privacy checks passed.
- The old custom-provisioned runtime and its two owned stacks were deleted. Six saved connections were already expired; their records now show retirement. Old ECR images remain retained.
- The named `opencode` settings were deployed through official CDK. The runtime and DEFAULT endpoint reached READY. The plugin was reinstalled/relinked and imported the new CDK outputs.
- Fresh cloud probes passed model/role checks, question wait/reply health, process-death cleanup, default selection, attachment, and conversation continuity. Both test-session stop requests succeeded and the isolated Herdr server stopped.
- The named `codex` settings passed synthesis, local ARM64 startup, and the later short cloud model/attachment probe. No activity-aware health or long-duration validation is claimed.
- A final CDK diff against the deployed OpenCode stack reported no differences. The Herdr production environment excludes the removed runtime CLI.
- The earlier refactor passed 170 offline Python tests, including isolated Herdr validation. Ruff and the privacy guard passed.
- All nine runtime-image tests passed against the full ARM64 image built and pushed by the provisioner. This includes the three opt-in Docker tests.
- Earlier direct builds timed out during public-base metadata resolution. The full provisioner build later succeeded with its temporary Docker configuration.
- The earlier revision was deployed to the existing owned runtime. The runtime and default endpoint reached READY on the new version.
- Fresh cloud probes passed shell/model activity, question wait/reply/completion, process-death cleanup, role-only model calls, default-profile selection, attachment, and context-aware follow-up.
- Both probe sessions and the isolated Herdr server were stopped. Concurrent/nested-tool permission cases retain offline coverage; live coverage remains pending.
- The saved runtime profile was renamed to `opencode-agentcore-runtime` and retained as default at that stage. Existing connection snapshots retain their original target.
- Earlier cloud tests verified owned-runtime creation/update, role-based Bedrock calls, default-profile selection, same-session attachment, and context-aware follow-up.
- Earlier activity tests verified shell work, model generation, question wait/reply, completion, and process death. Full idle/max-lifetime expiry, live permission dialogs, and full credential rollover remain untested.
- Five independent agents completed parallel retrieval/translation and follow-up work. They were stopped on request. Discover current sessions before any operation.
- OpenCode 1.18.30/Bun 1.3.14 crashed at 35×20 before mouse input. Startup and SGR wheel controls passed at 80×20 and 35×40. The safe-size boundary is unknown.
- A separate suspended process was recovered with identity-checked `SIGCONT`. Distinguish suspension from process exit and stopped AgentCore compute.
- Manual conversation recovery succeeded after a credential snapshot expired, while compute and its database survived. Automated resume and durable compute recovery remain unimplemented.
- EC2/SSM hosting, laptop-disconnect independence, host reconciliation, full coding-state recovery, and additional shells remain planned. The later S3 Files tests qualified mounted file persistence only.
- Linux/macOS Python 3.11/3.13 CI is configured. Remote CI, GitHub-managed install/update, and publication remain pending.

### Remaining work

The next hosting milestone is H01–H10 in the requirements, using the existing authentication path.
Worker persistence is a separate milestone. Extend the P01 mount baseline through P02–P07, then implement L01–L12 recovery and scoped operations.
Capture conversation identity, validate checkpoints, and reconcile uncertain tool outcomes before automatic resume.
Stop completion and bounded provisioning/stop conflict handling still need implementation.

For handoff, state changed behavior, checks that ran, and unresolved limits.
Update this file and the design/requirements when decisions change. Do not add a separate handoff document.
