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
S3 Files persistence for coding files, configuration, skills, and OpenCode state is in scope. It is not implemented yet.

## Repository conventions

- Keep exactly three directories under `src/`: `agentcore_runtime/`, `herdr_plugin/`, and `runtime_contract/`.
- Keep runtime modules directly in `src/agentcore_runtime/`. Do not add a second folder with the same name.
- Each component owns its README, implementation, and tests. Infrastructure uses npm/CDK; the connector and contract use Python packaging.
- Both applications may depend on the contract. Neither may import the other application's implementation.
- Keep the contract free of AWS, Docker, Herdr, and filesystem operations. Its Python consumer and TypeScript deployment shape use standard libraries only.
- Keep assistant-specific images, models, health hooks, and deployment behavior in the runtime component.
- Keep both example adapters under `<assistant>/image/`. Share image build, startup, and health code in `common/`.
- Keep assistant comparisons and status-detection evidence in `src/agentcore_runtime/README.md`. Do not add READMEs under `opencode/` or `codex/`.
- Use official AWS CDK constructs and CLI for infrastructure. Do not reintroduce custom Boto3 create/update loops or a runtime provisioning executable.
- Select runtime settings by named JSON profiles. `opencode` and `codex` are examples, not an enum. Keep profile references distinct from Herdr recognition hints and local connection labels.
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
- Keep user configuration, connection records, and transcripts outside the checkout.
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
Example image versions are declared in named settings: OpenCode `1.18.30` and Codex `0.163.0`.

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
| `src/agentcore_runtime/app.ts` | Select a named runtime profile and instantiate the CDK stack. |
| `src/agentcore_runtime/runtime-stack.ts` | Define official CfnRuntime, IAM, DockerImageAsset, and connection outputs. |
| `src/agentcore_runtime/profiles/` | Declare named settings. New profiles do not require connector branches. |
| `src/agentcore_runtime/common/` | Share the Dockerfile, launch entrypoint, environment inheritance, HTTP health, lease reader, and license. |
| `src/agentcore_runtime/codex/image/` | Supply the Codex-specific environment/argv adapter and attribution. |
| `src/agentcore_runtime/opencode/image/` | Supply the OpenCode adapter, configuration, dependency warmup, and activity-event plugin. |
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
14. **Permission updates:** declare models still needed by surviving sessions through CDK settings. Review IAM changes; CDK does not merge arbitrary existing policies or provide cross-stack transactions.
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
26. **Launch command:** require explicit argv in every contract/connection profile. Named settings supply the example command. CDK context and connector `--command` can override it without installing files or changing container `CMD`.
27. **Codex example:** use the native Bedrock AWS credential provider. Keep tool approvals enabled. Short cloud model/attachment checks passed, but its health service reports readiness only. Do not claim sandbox/tool or long-duration qualification.
28. **Status sources:** Herdr supports both example kinds. Current remote status comes from active screen/title manifests through the host wrapper hint. Codex's missing work reporter is an AgentCore-health gap, not a lack of Herdr native detection.

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
npm ci --prefix src/agentcore_runtime
npm run check --prefix src/agentcore_runtime
npm test --prefix src/agentcore_runtime
git diff --check
```

The Herdr test uses isolated config, state, and socket paths. It does not start a server or change the user's registry.
Without `HERDR_TEST_BINARY`, that test is skipped. Default tests make no AWS calls.
Node activity tests run when Node is installed.
The privacy guard checks working files, the index, and history without printing matched values.

Build and test a runtime image after runtime changes:

```bash
docker buildx build --platform linux/arm64 --load \
  -f src/agentcore_runtime/common/Dockerfile \
  --build-arg ASSISTANT_DIR=opencode/image --build-arg NPM_PACKAGE=opencode-ai \
  --build-arg NPM_VERSION=1.18.30 --build-arg EXECUTABLE=opencode \
  -t herdr-agentcore-local:1.18.30 src/agentcore_runtime
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
| `src/herdr_plugin/tests/live_layout_probe.py` | Probe startup at selected dimensions in a fresh session. |

Supply `--runtime-arn`; use `--aws-profile` if needed.
Process checks require command-invocation permission and return credential-presence booleans only.
Live probes must stop their own sessions. The Herdr probe must also stop its isolated server.
Reject known update dialogs before sending model prompts. Wait for detached panes to close before targeting a later action.

## Current evidence and next work

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
- Codex startup reported missing system bubblewrap with a bundled fallback, and embedded mode due to CLI configuration overrides. Model flow passed; sandbox/tool behavior and full key handling remain unverified.
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
- The saved runtime profile was renamed to `opencode-agentcore-runtime` and remains the default. Existing connection snapshots retain their original target.
- Earlier cloud tests verified owned-runtime creation/update, role-based Bedrock calls, default-profile selection, same-session attachment, and context-aware follow-up.
- Earlier activity tests verified shell work, model generation, question wait/reply, completion, and process death. Full idle/max-lifetime expiry, live permission dialogs, and full credential rollover remain untested.
- Five independent agents completed parallel retrieval/translation and follow-up work. They were stopped on request. Discover current sessions before any operation.
- OpenCode 1.18.30/Bun 1.3.14 crashed at 35×20 before mouse input. Startup and SGR wheel controls passed at 80×20 and 35×40. The safe-size boundary is unknown.
- A separate suspended process was recovered with identity-checked `SIGCONT`. Distinguish suspension from process exit and stopped AgentCore compute.
- Manual conversation recovery succeeded after a credential snapshot expired, while compute and its database survived. Automated resume and durable compute recovery remain unimplemented.
- EC2/SSM hosting, laptop-disconnect independence, host reconciliation, S3 Files coding-state persistence, and additional shells remain planned.
- Linux/macOS Python 3.11/3.13 CI is configured. Remote CI, GitHub-managed install/update, and publication remain pending.

The next hosting milestone is H01–H10 in the requirements, using the existing authentication path.
Worker persistence is a separate milestone: P01–P07, then L01–L12 recovery and scoped operations.
Capture conversation identity, validate checkpoints, and reconcile uncertain tool outcomes before automatic resume.
Stop completion and bounded provisioning/stop conflict handling still need implementation.

For handoff, state changed behavior, checks that ran, and unresolved limits.
Update this file and the design/requirements when decisions change. Do not add a separate handoff document.
