# EC2 host for Herdr and OpenCode

## Goal

This component creates one EC2 host for interactive work.
You open a terminal on the host. In the terminal you run the Herdr TUI and OpenCode.
OpenCode uses a Claude model in Amazon Bedrock.

This component is separate from [`../agentcore_runtime/`](../agentcore_runtime/README.md).
That component runs coding agents in AgentCore Runtime. This component gives a person a host to work on.

## How it works

- You reach the host through AWS Systems Manager Session Manager. The host has no SSH keys and no inbound ports.
- The host gets its AWS credentials from its instance role. The role can call only the Claude model. No AWS keys are stored.
- On the first boot, `bootstrap.sh` installs OpenCode and Herdr and writes their configuration.
  It marks the host ready only after it checks the tools and Bedrock access.
- The stack uses a VPC and subnet that already exist. It never creates a network.

## What you provide

Copy `.sample.env` to `.env` in this folder. Git ignores `.env`. Enter two IDs:

| Variable | Value |
| --- | --- |
| `EC2_HOST_VPC_ID` | An existing VPC. |
| `EC2_HOST_SUBNET_ID` | A subnet in that VPC. |

Use a private subnet with a NAT gateway. The host then has no public IP address.
The subnet must have a route to the internet.

You also need an AWS sign-in, a bootstrapped CDK environment, and Bedrock access to the Claude model.

## Use it

Deploy only with explicit authorization. AWS charges for the resources.

```bash
npm ci --prefix src/ec2_herdr_host
npm --prefix src/ec2_herdr_host run cdk -- deploy
```

The stack output `SessionCommand` is the command that opens a terminal.
It starts Bash on purpose. A plain `aws ssm start-session` starts `sh`, and `sh` does not find the tools.

## Know before you change it

- AWS deletes the disk when it replaces or ends the instance. Push your work to a Git remote.
- A new AMI or a new disk size replaces the instance. CDK keeps the AMI choice in `cdk.context.json`. Keep a copy of this file.
- A changed `bootstrap.sh` does not run on a host that exists.

## Where to find details

| File | Content |
| --- | --- |
| `app.ts` | Region, optional disk size, and notes on the CDK lookups. |
| `host-stack.ts` | Instance, security group, IAM policy, and model settings. |
| `bootstrap.sh` | First-boot steps, log file, and completion marker. |
| `host-config.ts` | How `.env` is read. |
| `tests/` | Tests that make no AWS calls. Run them with `npm test --prefix src/ec2_herdr_host`. |
