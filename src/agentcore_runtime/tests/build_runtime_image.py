"""Build a local ARM64 test image with the same declared arguments as CDK."""

import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", choices=("opencode", "codex"))
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    images = root / "src/agentcore_runtime/agent_images"
    definition = json.loads((images / args.image / "image.json").read_text())
    command = [
        "docker",
        "buildx",
        "build",
        "--platform",
        "linux/arm64",
        "--load",
        "--file",
        str(images / definition["file"]),
        "--tag",
        args.tag,
    ]
    for key, value in {**definition["buildArgs"], "ASSISTANT_DIR": args.image}.items():
        command.extend(["--build-arg", f"{key}={value}"])
    subprocess.run([*command, str(root)], check=True)


if __name__ == "__main__":
    main()
