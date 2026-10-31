# Pinned connection contract

The `herdr-to-agentcore` plugin repository owns this format.
This repository contains a checksum-pinned copy of its schema and conformance cases.
No plugin source or shared implementation package is required to build or deploy a runtime.

[upstream.json](upstream.json) records the source and exact file hashes.
`source_release` is `null` when no release tag is assigned. The SHA-256 values identify the exact source files.
Normal builds do not fetch or update these files.

## Exported descriptor

```json
{
  "version": "1.0.0",
  "transport": "agentcore-shell-v1",
  "connection": {
    "runtime_arn": "arn:aws:bedrock-agentcore:eu-west-1:123456789012:runtime/example-Abc123",
    "command": ["/app/run.sh"]
  }
}
```

The identifiers are fictional. The runtime supplies its actual launch command.
Only the ARN and command are required connection values. An optional `endpoint` defaults to `DEFAULT`.
The consumer derives the region. Agent recognition, host AWS credentials, and local profile labels belong to the consumer.
Do not export `region`, `agent_kind`, `runtime_profile`, credentials, or session IDs.

[connection.schema.json](connection.schema.json) specifies field and text limits.
Commands contain 1–64 arguments. Each argument contains at most 4096 Unicode characters and no control characters.
The first argument must not start with `-`.
Also enforce the 8192-byte aggregate limit: sum each argument's UTF-8 byte length plus one.
The schema cannot express that aggregate rule. The runtime producer checks it in code.

## Update procedure

1. Obtain the schema and fixtures from an explicit plugin release.
2. Replace the two JSON files together and update the source release and SHA-256 values in `upstream.json`.
3. Run the CDK checks and tests, including the pinned conformance cases.
4. Review the contract changes before changing the exported descriptor version.

Keep published descriptor versions stable.
The consumer rejects unknown fields; adding fields can require a new version.
The `export-connection` command validates a CDK output and writes a standalone descriptor without modifying the source file.

## SemVer compatibility

The producer emits contract `1.0.0`. The exporter accepts stable `1.x.y` versions and preserves the input descriptor's version.
Build metadata is accepted. Prereleases, numeric versions, incomplete versions, and other major versions are rejected.
The `v1/` directory groups contract major version 1. The transport name identifies the Shell protocol independently.
Incompatible wire fields or validation behavior require a major version. Minor versions preserve the accepted payload shape; patches contain compatible fixes or documentation changes.
Plugin releases, runtime images, and contract versions are independent.
