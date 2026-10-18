# Herdr plugin guideline review

## Scope and sources

This review uses the official [Herdr 0.9.5 plugin documentation](https://herdr.dev/docs/0.9.5/plugins/) and [agent-wrapper documentation](https://herdr.dev/docs/0.9.5/agents/#vms-and-sandbox-wrappers).
Version 0.9.5 is the declared minimum and the installed validation version.

Herdr requires a root manifest and executable argv entrypoints.
It does not prescribe an internal `src/` or `docs/` layout.
This repository's three-component layout follows that contract.
Each component owns its README, implementation, and tests. Infrastructure uses a private npm/CDK project; the other components use Python packages.
The review is not an official endorsement or a claim of production readiness.

## Contract review

| Official convention | Implementation |
| --- | --- |
| Required manifest metadata | [Manifest](../herdr-plugin.toml) has ID, name, version, and minimum Herdr version. Package versions agree. |
| Supported platforms | Linux and macOS match the POSIX terminal and file locks. Windows is not advertised. |
| Commands are argv arrays | Build, action, and pane commands use arrays. The connector quotes remote launch arguments explicitly. |
| Declare actions and panes | Five actions and their pane entrypoints are static. No private UI API is required. |
| Use `HERDR_BIN_PATH` | [Herdr adapter](../src/herdr_plugin/herdr_agentcore/herdr.py) uses the injected path, with a CLI fallback. |
| Respect invocation context | Pane creation uses `HERDR_PLUGIN_CONTEXT_JSON` and the invoking pane/workspace. It does not select an unrelated focused pane. |
| Keep user data outside the plugin root | [Storage](../src/herdr_plugin/herdr_agentcore/storage.py) uses plugin config/state directories, private atomic writes, and connection locks. |
| Plugin owns its schema | [Models](../src/herdr_plugin/herdr_agentcore/models.py) validate local records. [The shared contract](../src/runtime_contract/README.md) defines exported connection data. |
| Declare toolchains and dependencies | The build uses `uv sync --frozen --no-dev` and excludes runtime definitions. Docker is needed only for the separate runtime publisher. |
| Link does not build | README steps install dependencies before linking. `.venv/` is generated runtime state, not distribution source. |
| Build has no runtime context | The manifest build installs dependencies. It does not call Herdr or provision AWS resources. |
| Put long-running terminal work in panes | Connectors run as pane commands. Exit cancels local I/O and restores terminal modes. |
| Expose a host-visible agent hint | The connector re-executes with the saved `agent_kind`. It clears inherited hints for ordinary terminals. Old profiles retain OpenCode recognition. |
| Separate metadata and agent lifecycle | `pane report-metadata` carries transport status. It does not create false agent lifecycle events. |
| Startup hooks are one-shot | No startup hook is declared. A future reconciliation hook must finish and exit. |
| Updates preserve user state | Data stays outside installation. Existing connections keep profile snapshots. Full managed-update testing remains pending. |

## Trust and lifecycle boundaries

Herdr plugins run as the host user and inherit its environment. They are not sandboxed.
The connector can use the AWS permissions available to that identity.
Review the manifest and scope host and runtime roles separately.

Provisioning is an explicit operation in the runtime component, not a connector build or startup side effect.
A new-agent action starts remote compute. Stop is a separate, confirmed operation.
Detach leaves compute subject to AWS lifecycle limits.
Unlinking or uninstalling the plugin does not delete AWS resources.

Herdr's screen detection can report idle for an unfamiliar prompt.
`cloud=connected` proves only transport state, not TUI health or permission to answer a dialog.
See [design limits](DESIGN.md) for viewport and recovery findings.
AgentCore's health bridge remains separate from Herdr's screen-derived status.

## Repository layout

```text
herdr-plugin.toml       Plugin contract
pyproject.toml          Packaging and tooling
uv.lock                 Locked dependencies
README.md               Goal, setup, and usage
AGENTS.md, agent.md      Coding-agent instructions
LICENSE, NOTICE         Licensing and attribution
.github/workflows/      CI configuration
src/agentcore_runtime/  Assistant definitions, deployment, README, and tests
src/herdr_plugin/       Connector, README, and tests
src/runtime_contract/   Shared connection schema, README, and tests
docs/                   Requirements, design, proposals, and reviews
```

Git ignores `.venv/`, `build/`, `dist/`, test/lint caches, bytecode, and package metadata.
It also excludes user deployment/configuration files.
No upstream source checkout is needed to build, link, or run the plugin.

The connector and Python contract build separate wheels and source distributions.
Infrastructure uses official CDK constructs and has no custom provisioning executable.
Runtime assets do not enter the connector wheel. Named settings feed explicit connection data to the connector.
Root design documents remain in the repository. Component README links to them refer to a full checkout.

## Validation and follow-up

Manifest tests check commands, version alignment, and platforms.
With `HERDR_TEST_BINARY`, they register the plugin in a disabled, isolated registry.
They verify registration and the config directory without starting a server or changing the user's registry.

```bash
HERDR_TEST_BINARY="$(command -v herdr)" uv run --frozen pytest \
  src/herdr_plugin/tests/test_plugin.py src/herdr_plugin/tests/test_herdr_manifest.py -q --tb=short
uv run --frozen ruff check src
uv run --frozen ruff format --check src
uv run --frozen python src/herdr_plugin/tests/repository_privacy.py
uv build --all-packages
npm ci --prefix src/agentcore_runtime
npm test --prefix src/agentcore_runtime
```

The current layout has Python, CDK assertion, image, and named-profile checks.
Independent connector/contract distributions and descriptor import have validation coverage. The CDK project has separate assertion tests.
A connector-only production installation excludes the runtime-definition package.
The updated connector imported a CDK-deployed runtime and passed fresh cloud model/activity/attachment tests.
Both shared-image examples later passed cloud model/attachment tests on disposable runtimes. The evidence below describes earlier revisions.

The earlier layout review passed all nine targeted plugin/manifest tests and package checks.
The later refactor passed 170 offline Python tests, including the isolated manifest test.
All nine runtime-image tests passed against the full image built and pushed by the provisioner.
That build succeeded after earlier direct builds timed out at public-base metadata resolution.
The updated runtime passed fresh cloud activity, role-based inference, default selection, attachment, and follow-up probes.
Both disposable sessions and the isolated test server were stopped. These tests do not establish persistent recovery or hosting readiness.

Before publication, validate GitHub-managed installation/updates and the full platform matrix.
Community discovery uses a public repository with a valid manifest and the `herdr-plugin` topic.
Publication, topic registration, and marketplace indexing have not occurred.
EC2/SSM hosting and persistent-state recovery remain separate milestones.
Follow the [documentation style guide](../agent.md#documentation-style-asd-ste100-style-english) when updating this review.
