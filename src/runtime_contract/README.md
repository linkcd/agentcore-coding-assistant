# Runtime connection contract

## Purpose

Define the data exchanged between a runtime publisher and a terminal connector.
The Python consumer package is `agentcore-contract`. Its module is `agentcore_contract`.
`connection.ts` supplies the deployment-side shape used by CDK.
Both implementations use standard libraries only. They make no AWS, Docker, Herdr, or filesystem calls.

The contract targets interactive AgentCore Shell connections.
It does not convert an HTTP-only agent into a terminal application.

## Descriptor version 1

```json
{
  "version": 1,
  "transport": "agentcore-shell-v1",
  "connection": {
    "runtime_arn": "arn:aws:bedrock-agentcore:eu-west-1:123456789012:runtime/example-Abc123",
    "region": "eu-west-1",
    "endpoint": "DEFAULT",
    "command": ["/app/run.sh"],
    "agent_kind": "opencode",
    "runtime_profile": "opencode-agentcore-profile-2"
  }
}
```

The example account and runtime are fictional.

| Field | Meaning |
| --- | --- |
| `version` | Descriptor version. Only integer `1` is accepted. |
| `transport` | Protocol identifier. Only `agentcore-shell-v1` is accepted. |
| `runtime_arn` | Deployed runtime Amazon Resource Name (ARN). Required. |
| `region` | AWS region. Omit it to derive the region from the ARN. An explicit value must match. |
| `endpoint` | Runtime endpoint qualifier. Default: `DEFAULT`. |
| `command` | Required remote launch argument array. There is no default. It must start an installed interactive program. |
| `agent_kind` | Herdr recognition hint. Use a supported lowercase identifier, or `null` for an ordinary terminal. Default: `null`. |
| `runtime_profile` | Optional provision profile reference, such as `opencode-agentcore-profile-2`. It is not a connector enum or a command lookup. |

The consumer validates version, transport, ARN, region, argument limits, and recognition-hint syntax.
Unknown fields are rejected. Commands allow 1–64 arguments and at most 8 KiB in total.
Control characters are rejected.

The descriptor contains no credentials, host AWS profile, model settings, or session IDs.
The connector selects host credentials locally and creates execution IDs.
Model configuration, skills, permissions, and health reporting belong to the runtime definition.
Profile names and recognition hints are distinct. A profile called `reviewer` can use the same Herdr hint as another profile.
Adding a provision profile does not require a new branch in the connector or contract.
The current examples export `codex-agentcore-profile-1`, `opencode-agentcore-profile-2`, and `opencode-s3filesystem-agentcore-profile-3` as their references.
The two OpenCode descriptors have the same command and recognition hint, but different deployed runtime ARNs and profile references.

## Python API

```python
from agentcore_contract import ConnectionSpec, decode_descriptor, encode_descriptor

connection = ConnectionSpec.from_dict(connection_fields)
document = encode_descriptor(connection)
validated = decode_descriptor(document)
```

`ConnectionSpec` holds validated connection data. Encoding validates the data again.
The connector and runtime publisher own their respective file reads and writes.
Treat descriptors as trusted configuration: their command will run remotely when a new session starts.
Import does not execute the command.

`decode_cdk_outputs(data, stack)` accepts a standard CDK `--outputs-file` document.
It reads the selected stack's JSON-valued `ConnectionDescriptor` output and applies the same validation.
Multiple stacks require explicit selection. Unrelated outputs are not copied into connection profiles.

## Format status and ownership

Descriptor version and plugin storage version are separate contracts.
AWS runtime versions and assistant package versions are separate from both formats.
Updating an AWS runtime can increase its runtime version without changing descriptor version 1. Recreating a deployment produces a new ARN and restarts its runtime version sequence.
These formats are not publicly released. Internal version `1` is a validation marker, not a backward-compatibility promise.
Runtime definitions supply explicit commands. The contract does not assume `/app/run.sh`, OpenCode, or any other launcher.
Descriptors and profiles without `agent_kind` select an ordinary terminal, including when their command contains `opencode`.
The plugin may add its local `aws_profile` after descriptor validation. Exporters must not include that field.

Reconfigure experimental profiles when the required format changes. Do not add inference rules to preserve unpublished formats.
Never silently replace a missing runtime target or launch command.

## Checks and related documents

Run from the repository root:

```bash
uv run --frozen pytest src/runtime_contract/tests -q --tb=short
uv build --package agentcore-contract
```

Unit tests check validation and round trips. Repository tests enforce the three component boundaries.
The package can build independently. It does not require either application package.
All three replacement CDK output descriptors were imported successfully during the 2026-10-19 [model-only rebuild verification](../agentcore_runtime/README.md#model-only-profile-rebuild--2026-10-19).

Repository links: [runtime publisher](../agentcore_runtime/README.md), [connector](../herdr_plugin/README.md), and [writing rules](../../agent.md#documentation-style-asd-ste100-style-english).
These relative links refer to a full repository checkout.
