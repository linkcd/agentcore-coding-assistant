# Profile storage mapping

## Decision and status

Use one dedicated S3 Files access point for each S3-backed provision profile.
Do not share an access point between different profiles.
Sessions of the same profile share its access point and persistent files.

This mapping is implemented in the CDK definitions and runtime launcher.
Externally supplied access-point ARNs are rejected, so separate profiles cannot select the same access point through the provision-profile schema.
See the runtime README for dated deployment and verification results.

The OpenCode S3 profile was migrated to this layout on 2026-10-20.
Two replacement user sessions confirmed `/mnt/workspace` as their working directory, with no nested profile directory.
The old duplicated prefix contained only three empty directory markers. Those approved markers were removed; unrelated S3 data was preserved.

## Mapping

Use one existing S3 bucket and a managed S3 Files filesystem rooted at that bucket.
Each access point selects this directory:

```text
/agent-filesystem/profiles/<profile-name>
```

Mount the selected access point at `/mnt/workspace` inside the runtime.
Start the assistant in `/mnt/workspace`.
Do not add another `profiles/<profile-name>` directory inside the runtime mount.

| Profile | S3 object prefix | Access-point root | Runtime mount and working directory |
| --- | --- | --- | --- |
| `profile1` | `agent-filesystem/profiles/profile1/` | `/agent-filesystem/profiles/profile1` | `/mnt/workspace` |
| `profile2` | `agent-filesystem/profiles/profile2/` | `/agent-filesystem/profiles/profile2` | `/mnt/workspace` |
| `profile3` | `agent-filesystem/profiles/profile3/` | `/agent-filesystem/profiles/profile3` | `/mnt/workspace` |

This example assumes that all three profiles use S3.
Profiles without S3 continue to use their runtime-local working directories.

## S3 layout

```text
s3://<bucket>/
└── agent-filesystem/
    └── profiles/
        ├── profile1/              <- Access point 1 root
        │   ├── AGENTS.md
        │   ├── opencode.json
        │   ├── .opencode/
        │   ├── tools/
        │   └── projects/
        ├── profile2/              <- Access point 2 root
        │   ├── AGENTS.md
        │   ├── opencode.json
        │   ├── .opencode/
        │   ├── tools/
        │   └── projects/
        └── profile3/              <- Access point 3 root
            ├── AGENTS.md
            ├── opencode.json
            ├── .opencode/
            ├── tools/
            └── projects/
```

The access-point roots are distinct and do not contain each other.
Do not root an access point at `/agent-filesystem` or `/agent-filesystem/profiles`; that would expose multiple profile directories.

## Runtime layout

Every S3-backed OpenCode runtime sees the same local paths:

```text
/mnt/workspace/
├── AGENTS.md                      # Workspace instructions
├── opencode.json                  # OpenCode settings and MCP registrations
├── .opencode/
│   ├── skills/
│   │   └── <skill>/SKILL.md        # Discoverable skills
│   ├── agents/                    # Custom agent definitions
│   └── commands/                  # Custom commands
├── tools/                         # Persistent MCP source, manifests, and lockfiles
└── projects/                      # Working repositories
```

The mount hides the S3 directory prefix from the assistant.
For example, `/mnt/workspace/opencode.json` in a profile1 session maps to `s3://<bucket>/agent-filesystem/profiles/profile1/opencode.json`.
The same local path in a profile2 session maps to profile2's file.

Use the assistant's native configuration conventions.
Register MCP servers in `opencode.json`; files under `tools/` alone do not register a server.
Keep disposable dependency caches, sockets, processes, and live runtime state on session-local storage.
Use the appropriate native configuration files for other assistants, such as Codex.

## Access boundaries

Each runtime execution role must permit mounting only its profile's access point.
Do not grant worker roles direct S3 bucket access or access to another profile's access point.
Under those permissions, access through the profile mounts is:

| Runtime profile | Profile 1 files | Profile 2 files | Profile 3 files |
| --- | --- | --- | --- |
| Profile 1 | Yes | No | No |
| Profile 2 | No | Yes | No |
| Profile 3 | No | No | Yes |

The access-point root and IAM policy enforce the boundary.
The common UID/GID `1000:1000` and directory mode `755` do not provide cross-profile isolation by themselves.
Two sessions of profile1 deliberately share profile1's files, but retain separate runtime processes and local caches.

## Configuration ownership

The component `.env` supplies the existing bucket name, subnet IDs, and security-group IDs.
No filesystem prefix or profile-workspace-base setting is required.
The provision profile selects its storage stack; CDK creates the dedicated access point and derives its root from the profile name.
UID/GID `1000:1000` and directory mode `755` remain fixed CDK values.
The repository's `provision_profiles/` directory stores deployment definitions. It is separate from the S3 directory layout.

## Migration checks

1. Inspect the old and destination S3 prefixes before changing the access point.
2. Preserve existing files. Delete only explicitly approved objects or empty directory markers.
3. Coordinate replacement of affected runtime sessions. An existing session does not switch mounts automatically.
4. Verify the new access-point root and its runtime role policy.
5. Verify `/mnt/workspace` startup and native configuration discovery in a fresh session.
6. Verify shared persistence between sessions of the same profile and separate roots for different profiles.

See [the runtime setup guide](../src/agentcore_runtime/README.md) and [the architecture design](DESIGN.md#persistent-coding-files-through-s3-files).
