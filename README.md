# Herdr → AgentCore

## Goal

Build a community Herdr plugin that lets developers **manage, visualize, and interact with OpenCode agents running inside Amazon Bedrock AgentCore Runtime** using the same terminal-based workflow they use for local coding agents.

Herdr owns workspaces, tabs, panes, agent interaction, and orchestration. The plugin adds AgentCore execution, session recovery, and persistent coding files through S3 Files. AWS access uses the management host's credential chain or IAM role; the plugin has no Cognito login or separate end-user platform.

For unattended cloud operation, run the Herdr background server, plugin connectors, and coordination workflows on an always-on management host, starting with EC2. The developer's laptop runs the Herdr client. OpenCode, its tools, and its coding workspace run in AgentCore.

```text
Laptop Herdr client → SSH → EC2 Herdr server + plugin → AgentCore sessions → OpenCode
```

Laptop-hosted Herdr remains an option for development. The cloud-hosted design keeps management and connections running while the laptop sleeps or reboots.

## Intended experience

- Start multiple cloud coding agents in separate Herdr panes.
- View their terminal output and agent status, send prompts, and respond to interactive dialogs.
- Detach and reconnect to an existing remote terminal.
- Keep cloud-hosted agent connections and coordination running independently of the laptop.
- Preserve repositories, working changes, configuration, skills, and OpenCode state on a mounted S3 Files filesystem.
- Start fresh compute or resume existing execution using persisted files and conversation state. Persistent-home integration and full recovery after compute termination are planned.
- Install and update the integration through Herdr's standard community plugin system.

## Repository structure

```text
README.md                 Repository goal
REQUIREMENTS.md           Scope, requirements, and acceptance criteria
DESIGN.md                 Architecture, diagrams, and design decisions
agent.md                  Context and instructions for follow-up coding agents
AGENTS.md                 Automatic discovery entrypoint for agent.md
herdr-plugin.toml         Herdr plugin manifest
pyproject.toml / uv.lock  Package configuration and dependency lock
src/
  herdr_agentcore/         Plugin implementation
  tests/                  Automated tests
```

The current implementation is an experimental prototype with live-PTY reattachment. Local tests and manifest validation have passed. S3 Files-backed coding state, the EC2 management deployment, live AgentCore/OpenCode workflow, and recovery after host or runtime compute termination remain to be validated or implemented.

Start with [requirements](REQUIREMENTS.md) and [design](DESIGN.md). Coding agents should read [agent.md](agent.md).
