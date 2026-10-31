# Runtime requirements

| ID | Requirement |
| --- | --- |
| R01 | Build and deploy without a Herdr plugin checkout or shared implementation package. |
| R02 | Use TypeScript CDK and the official deployment CLI. |
| R03 | Select settings through a named provision profile and image definition. |
| R04 | Resolve external bindings from the component `.env`, not ambient overrides. |
| R05 | Publish only the minimal versioned connection descriptor. |
| R06 | Keep assistant-specific startup and work-health behavior in the image adapter. |
| R07 | Use native AWS role providers without credential snapshots. |
| R08 | Keep development-tool versions and download checksums explicit. |
| R09 | Keep transient caches and live process state outside persistent coding storage. |
| S01 | Use one dedicated S3 Files access point per S3-backed profile. |
| S02 | Preserve external bucket and network ownership. |
| S03 | Restrict each worker role to its profile's access point. |
| S04 | Mount and start directly at the profile root, with UID/GID 1000:1000 and mode 755. |
| T01 | Validate the pinned contract schema, fixtures, and aggregate command limits. |
| T02 | Run offline checks without AWS calls or user-session changes. |
| T03 | Run authorized live checks only in disposable sessions. |
| P01 | Keep credentials and real deployment bindings out of Git and images. |
| P02 | Preserve root legal files and upstream attribution. |

See [the design](DESIGN.md), [runtime guide](../src/agentcore_runtime/README.md), and [contract](../contracts/1.0.0/README.md).
