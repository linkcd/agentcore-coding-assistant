"""Offline guard for private deployment data in worktree, index, and Git history.

Only paths, line numbers, and rule names are printed; matched values are redacted.
Run from a Git checkout: uv run python scripts/repository_privacy.py
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import json
import re
import subprocess
from pathlib import Path

EXAMPLE_ACCOUNTS = {"000000000000", "123456789012", "111122223333"}
RULES = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "literal AWS secret": re.compile(
        r"""(?i)(?:aws_secret_access_key|aws_session_token|secretAccessKey|sessionToken)"""
        r"""["']?\s*[:=]\s*["'][A-Za-z0-9/+=]{20,}["']"""
    ),
    "signed AWS URL": re.compile(r"(?i)X-Amz-(?:Signature|Credential)=[A-Za-z0-9%/]{8,}"),
    "deployment gateway URL": re.compile(
        r"https://[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com"
    ),
    "AWS resource ID": re.compile(r"\b(?:fsap|fs|vpc|subnet|sg|i)-[a-f0-9]{8,17}\b"),
    "personal machine path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
}
ACCOUNT = re.compile(r"(?<![\w])\d{12}(?![\w])")
RUNTIME_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-([A-Za-z0-9]{10})\b")
PRIVATE_NAMES = (
    ".env",
    ".env.*",
    "runtime_config*.json",
    "*.connection.json",
    "agent.config",
    "infra.config",
    ".deployed-state.json",
    "credentials",
    "credentials.json",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def findings(path: str, content: bytes) -> list[tuple[int, str]]:
    issues = []
    basename = Path(path).name
    if any(fnmatch.fnmatch(basename, pattern) for pattern in PRIVATE_NAMES):
        issues.append((0, "private configuration/credential filename"))
    if ".aws" in Path(path).parts or path == "config.json":
        issues.append((0, "private configuration path"))
    for line_number, line in enumerate(content.decode(errors="replace").splitlines(), 1):
        for name, pattern in RULES.items():
            if pattern.search(line):
                issues.append((line_number, name))
        if any(match[0] not in EXAMPLE_ACCOUNTS for match in ACCOUNT.finditer(line)):
            issues.append((line_number, "non-example AWS account ID"))
        # npm integrity digests can coincidentally match the short runtime-ID
        # heuristic. Only exempt structurally valid SHA integrity fields from
        # that one heuristic; credentials, account IDs, and other rules still run.
        runtime_line = "" if basename == "package-lock.json" and npm_integrity(line) else line
        for match in RUNTIME_ID.finditer(runtime_line):
            suffix = match[1]
            if any(c.isupper() for c in suffix) and any(c.islower() for c in suffix):
                issues.append((line_number, "deployment-style runtime ID"))
                break
    return issues


def npm_integrity(line: str) -> bool:
    try:
        data = json.loads("{" + line.strip().rstrip(",") + "}")
        if set(data) != {"integrity"} or not isinstance(data["integrity"], str):
            return False
        algorithm, encoded = data["integrity"].split("-", 1)
        length = {"sha256": 32, "sha384": 48, "sha512": 64}.get(algorithm)
        return length is not None and len(base64.b64decode(encoded, validate=True)) == length
    except (ValueError, TypeError, binascii.Error):
        return False


def audit(root: Path) -> tuple[list[tuple[str, str, int, str]], int, int]:
    results = []
    blobs = {}

    def inspect(scope, path, content):
        results.extend((scope, path, line, rule) for line, rule in findings(path, content))

    def blob(oid):
        if oid not in blobs:
            blobs[oid] = git(root, "cat-file", "blob", oid)
        return blobs[oid]

    candidates = set(
        git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        .decode()
        .split("\0")
    ) - {""}
    for name in sorted(candidates):
        path = root / name
        if path.is_symlink():
            results.append(("worktree", name, 0, "symlink requires explicit review"))
        elif path.is_file():
            inspect("worktree", name, path.read_bytes())

    for entry in git(root, "ls-files", "--stage", "-z").decode().split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, oid, _ = metadata.split()
        if mode in {"100644", "100755"}:
            inspect("index", name, blob(oid))

    commits = git(root, "rev-list", "--all", "--reflog").decode().splitlines()
    inspected = set()
    for commit in commits:
        scope = f"history:{commit[:12]}"
        inspect(scope, "<commit message>", git(root, "show", "-s", "--format=%B", commit))
        for entry in git(root, "ls-tree", "-r", "-z", commit).decode().split("\0"):
            if not entry:
                continue
            metadata, name = entry.split("\t", 1)
            mode, kind, oid = metadata.split()
            if kind != "blob" or (name, oid) in inspected:
                continue
            inspected.add((name, oid))
            if mode == "120000":
                results.append((scope, name, 0, "symlink requires explicit review"))
            else:
                inspect(scope, name, blob(oid))
    return results, len(candidates), len(commits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = Path(git(args.root, "rev-parse", "--show-toplevel").decode().strip())
    issues, files, commits = audit(root)
    for scope, path, line, rule in issues:
        print(f"{scope} {path}:{line}: {rule} [value redacted]")
    print(
        f"Audited {files} working files and the index; "
        f"{commits} history commits; {len(issues)} findings"
    )
    raise SystemExit(bool(issues))


if __name__ == "__main__":
    main()
