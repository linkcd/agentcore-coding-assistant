# EC2 host for Herdr and OpenCode

## Goal

This component creates one EC2 host for interactive work.
You open a terminal on the host. In the terminal you run the Herdr TUI and OpenCode.
OpenCode uses the Kimi K3 model from Moonshot AI in Amazon Bedrock. The AgentCore runtime profiles use the same model.

This component is separate from [`../agentcore_runtime/`](../agentcore_runtime/README.md).
That component runs coding agents in AgentCore Runtime. This component gives a person a host to work on.

## How it works

- You reach the host through AWS Systems Manager Session Manager. The host has no SSH keys and no inbound ports.
- The host gets its AWS credentials from its instance role. The role can call only Kimi K3 through its global inference profile, plus AgentCore runtimes (terminal and stop actions only). That is every runtime in the account and Region, or only those listed in `AGENTCORE_RUNTIME_ARN`. No AWS keys are stored.
- On the first boot, `bootstrap.sh` installs OpenCode, Herdr, the Herdr agent skill for OpenCode, uv, and the Herdr AgentCore plugin (`linkcd/herdr-agentcore`) and writes their configuration.
  It marks the host ready only after it checks the tools and Bedrock access.
- The stack uses a VPC and subnet that already exist. It never creates a network.

## What you provide

Copy `.sample.env` to `.env` in this folder. Git ignores `.env`. Enter two IDs, and optionally the runtime ARN:

| Variable | Value |
| --- | --- |
| `EC2_HOST_VPC_ID` | An existing VPC. |
| `EC2_HOST_SUBNET_ID` | A subnet in that VPC. |
| `AGENTCORE_RUNTIME_ARN` | Optional. The `RuntimeArn` of the AgentCore runtime(s) the host may open terminals in, separated by commas. The role then gets `InvokeAgentRuntimeCommandShell` and `StopRuntimeSession` on only those runtimes and their `DEFAULT` endpoint. Without it, the role may use every runtime of the account and Region. Set it to follow least privilege. |

Use a private subnet with a NAT gateway. The host then has no public IP address.
The subnet must have a route to the internet.

You also need an AWS sign-in, a bootstrapped CDK environment, and Bedrock access to Kimi K3 (see below).

## The model

OpenCode uses `amazon-bedrock/global.moonshotai.kimi-k3` in `eu-west-1`. This is the model ID of the AgentCore runtime profiles in `../agentcore_runtime/`.

- The host uses the **global** cross-Region inference profile. Bedrock can process requests in any commercial Region.
  There is no EU-only profile. Do not use this host for data that must stay in the EU.
- If an SCP denies Regions, it must allow `aws:RequestedRegion` = `unspecified`, because global profiles use that value.
- The role gets three grants, all tied to this one profile: the profile in `eu-west-1`, the model in `eu-west-1`, and the Region-less global model.
- To change the model, edit `MODEL_ID` and `FOUNDATION_MODEL` in `host-stack.ts`. Check the new ID with `opencode models amazon-bedrock` first.
  The policy is written for a `global.` profile. A geographic or in-Region profile needs different model grants, so change the policy too.

## Use it

Deploy only with explicit authorization. AWS charges for the resources.

```bash
npm ci --prefix src/ec2_herdr_host
npm --prefix src/ec2_herdr_host run cdk -- deploy
```

The stack output `SessionCommand` is the command that opens a terminal.
It starts Bash on purpose. A plain `aws ssm start-session` starts `sh`, and `sh` does not find the tools.

## Connect to AgentCore from the host

After the host is up, connect it to a runtime that you deployed with [`../agentcore_runtime/`](../agentcore_runtime/README.md).
The first boot installs Herdr, uv, and the [Herdr AgentCore plugin](https://github.com/linkcd/herdr-agentcore). You only connect the plugin to your runtime.

### 1. Collect two values from the runtime

| Value | Where to find it |
| --- | --- |
| Runtime ARN | The `RuntimeArn` output of the runtime deployment. The same ARN is in the `ConnectionDescriptor` output. |
| Launch command | The `command` in the same `ConnectionDescriptor`. The sample OpenCode and Codex images use `["/app/run.sh"]`. |

### 2. Allow the host to open a terminal in the runtime

The plugin signs its requests with the host's AWS identity (the EC2 instance role).
That role needs these permissions on your runtime ARN:

- `bedrock-agentcore:InvokeAgentRuntimeCommandShell` to open a terminal.
- `bedrock-agentcore:StopRuntimeSession` to stop a session. It is optional if you never stop sessions from Herdr.

Grant them on the runtime ARN and on `RUNTIME_ARN/runtime-endpoint/DEFAULT` (use your endpoint name if it is not `DEFAULT`).
AgentCore checks both resources.

This stack already grants them on every runtime in its account and Region.
To narrow that to one runtime, set `AGENTCORE_RUNTIME_ARN` in `.env` to the `RuntimeArn` and redeploy.
If the host was created before this default, redeploy the stack to add the policy. Until then the connection fails with an HTTP 403 (`AccessDenied`).

### 3. Open the host and start Herdr

1. Run the `SessionCommand` output of this stack on your laptop. It opens a Bash terminal on the host.
2. Check that the plugin is there: `herdr plugin list` must show `agentcore`.
   If it does not, run `herdr plugin install linkcd/herdr-agentcore --yes`.
3. Run `herdr`. Press Enter to close the welcome message. You now have a workspace with a terminal pane.

### 4. Save the connection (one time)

In that Herdr terminal pane, run:

```bash
herdr plugin action invoke agentcore.setup
```

An **AgentCore setup** pane opens and asks these questions:

| Question | What to enter |
| --- | --- |
| Profile name | Any short name, for example `my-agent`. Press Enter to use `default`. |
| Runtime ARN | The `RuntimeArn` from step 1. |
| AWS profile | Leave blank. The host uses its instance role. |
| Runtime endpoint | Leave blank to use `DEFAULT`. |
| Herdr agent kind | Press Enter to accept the default `opencode`. Enter `codex` to match a Codex image, or `terminal` for a plain terminal. The prompt shows these choices. |
| Launch argv as JSON | Press Enter to accept the default `["/app/run.sh"]`, which the sample OpenCode and Codex images use. For another image, enter the `command` from its `ConnectionDescriptor`. |

The answers are saved as a profile in `config.json` in the folder printed by `herdr plugin config-dir agentcore`.
The region comes from the ARN. The first profile you save becomes the default.
The file holds no credentials. It survives plugin updates and uninstall, so you set up once per host.

### 5. Start the cloud agent

```bash
herdr plugin action invoke agentcore.new
```

A new pane opens a terminal inside your runtime and starts the assistant.
The first start can take a short while because AgentCore creates the session.
The saved default profile is used.

### 6. Detach, come back, and stop

| Goal | How |
| --- | --- |
| Leave the agent running | Press Ctrl+] then `d`, or close the pane. |
| Return to it | `herdr plugin action invoke agentcore.attach`, then pick the session. |
| See saved sessions | `herdr plugin action invoke agentcore.sessions` |
| End it and free the compute | Detach, then `herdr plugin action invoke agentcore.stop`, then type the session name to confirm. |

Closing your Session Manager terminal does not stop Herdr or the agent. Run `herdr` on the host again to return.
Reattaching works only while the original AgentCore session is alive. After it expires, start a new one with `agentcore.new`.

### If something goes wrong

| Message or symptom | Likely cause and fix |
| --- | --- |
| `server_not_running` | Herdr is not running. Run `herdr` first, then invoke the action from a Herdr pane. |
| HTTP 403 or `AccessDeniedException` | The host role lacks the permission from step 2, or it is scoped to a different runtime ARN or endpoint name. |
| `NoCredentialsError` | The host has no AWS credentials. Check that the instance has its role. If you typed an AWS profile in setup, make sure it exists on the host, or run setup again and leave it blank. |
| `ResourceNotFoundException` | The runtime ARN is wrong or belongs to another region or account. |
| Shell closes at once | The launch command does not exist in the image. Check it against the runtime's `ConnectionDescriptor`. |
| A plain terminal opens, not the agent | The agent kind is `terminal` or one that Herdr does not recognize. The terminal still works. |
| Wrong profile saved | Run `agentcore.setup` again with the same name and answer `y` to replace it. |

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
