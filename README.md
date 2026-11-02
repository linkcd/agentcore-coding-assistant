# Coding assistants on AWS

This repository helps people work with coding assistants on AWS. It has two separate components.

| Component | Goal | Guide |
| --- | --- | --- |
| [`src/agentcore_runtime/`](src/agentcore_runtime/README.md) | Run interactive coding assistants in Amazon Bedrock AgentCore Runtime. | Images, CDK, storage, checks |
| [`src/ec2_herdr_host/`](src/ec2_herdr_host/README.md) | Give a person an EC2 host to run the Herdr TUI and OpenCode. | CDK, first-boot setup |

The two components share no code, no `.env` file, and no CDK app. Each has its own CDK project and README.
Choose the component that fits your goal. You do not need the other one.

The connector that attaches Herdr to AgentCore runtimes is a separate project: [linkcd/herdr-agentcore](https://github.com/linkcd/herdr-agentcore).
This repository and the connector share only a versioned JSON data format, never code.

## Layout

```text
src/agentcore_runtime/    Coding assistants that run in AgentCore Runtime
src/ec2_herdr_host/       EC2 host for the Herdr TUI and OpenCode
contracts/                Pinned copy of the connection contract
docs/                     Design, requirements, and storage documentation
scripts/                  Repository checks
```

## Get started

1. Read the guide of the component that you need.
2. Install the tools that the component needs. The versions are in `pyproject.toml` and in each `package.json`.
3. Configure the component with its `.sample.env`. Never put credentials or real IDs in Git.
4. Deploy only with explicit authorization, because AWS charges for the resources.

[Contributor instructions](agent.md) list the checks to run before you change anything.
Default checks make no AWS calls.

## Documentation

- [AgentCore runtime guide](src/agentcore_runtime/README.md)
- [EC2 host guide](src/ec2_herdr_host/README.md)
- [Design](docs/DESIGN.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Storage mapping](docs/STORAGE_MAPPING.md)
- [Connection contract](contracts/1.0.0/README.md)
- [Contributor instructions](agent.md)

[LICENSE](LICENSE) and [NOTICE](NOTICE) stay at the repository root and go into every image.
