"""Build a local ARM64 test image with the same declared arguments as CDK.

Usage, from the repository root:
    uv run --frozen python src/agentcore_runtime/tests/build_runtime_image.py \\
        opencode --tag agentcore-tools:opencode

To run the opt-in container checks, set HERDR_RUNTIME_TEST_IMAGE (OpenCode image)
or CODEX_RUNTIME_TEST_IMAGE (Codex image) to the tag. The Docker context is the
repository root, so the image includes LICENSE and NOTICE.
"""

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
