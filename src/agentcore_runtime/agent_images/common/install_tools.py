"""Install checksum-pinned ARM64 tool archives during the image build only."""

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def download(url: str, digest: str, destination: Path) -> Path:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("A pinned SHA-256 digest is required for each archive")
    run("curl", "--fail", "--location", "--retry", "3", "--output", str(destination), url)
    with destination.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != digest:
        raise ValueError(f"Checksum mismatch for {destination.name}")
    return destination


def main():
    if platform.machine() != "aarch64":
        raise ValueError("The runtime toolchain requires Linux ARM64")
    versions = {
        name: os.environ[f"{name}_VERSION"]
        for name in (
            "PYTHON",
            "MCP_PYTHON",
            "NODE",
            "UV",
            "PNPM",
            "GO",
            "RUST",
            "GH",
            "AWSCLI",
            "RIPGREP",
        )
    }
    if not all(versions.values()):
        raise ValueError("Declare tool versions in the selected image definition")
    with tempfile.TemporaryDirectory(prefix="image-tools-") as temporary:
        root = Path(temporary)

        def archive(name, url, *, target=root, strip=0):
            payload = download(url, os.environ[f"{name}_SHA256"], root / f"{name}.archive")
            run("tar", "xf", str(payload), "-C", str(target), f"--strip-components={strip}")

        archive(
            "UV",
            f"https://github.com/astral-sh/uv/releases/download/{versions['UV']}/uv-aarch64-unknown-linux-gnu.tar.gz",
        )
        for name in ("uv", "uvx"):
            shutil.copy2(root / "uv-aarch64-unknown-linux-gnu" / name, f"/usr/local/bin/{name}")
        # uv carries the Python archive checksums in its versioned download catalog.
        python_env = {
            **os.environ,
            "UV_PYTHON_INSTALL_DIR": "/usr/local/share/python",
            "UV_PYTHON_BIN_DIR": "/usr/local/bin",
            "UV_CACHE_DIR": str(root / "uv-cache"),
        }
        run("uv", "python", "install", versions["PYTHON"], versions["MCP_PYTHON"], env=python_env)
        for key in ("PYTHON", "MCP_PYTHON"):
            executable = subprocess.check_output(
                ["uv", "python", "find", "--managed-python", versions[key]],
                env=python_env,
                text=True,
            ).strip()
            minor = ".".join(versions[key].split(".")[:2])
            binary = Path(executable)
            for name in (f"python{minor}", f"python{minor}-config"):
                link = Path("/usr/local/bin") / name
                if not link.exists():
                    link.symlink_to(binary.parent / name)
            if key == "PYTHON":
                for name in ("python", "python3"):
                    (Path("/usr/local/bin") / name).symlink_to(binary)
                # Seed only this image-owned interpreter from its bundled pip wheel.
                # Keep uv's managed marker; project installs still use virtual environments.
                wheel = next(
                    (binary.parent.parent / f"lib/python{minor}/ensurepip/_bundled").glob(
                        "pip-*.whl"
                    )
                )
                run(
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    executable,
                    "--break-system-packages",
                    "--no-index",
                    str(wheel),
                    env=python_env,
                )
                for name in ("pip", "pip3"):
                    (Path("/usr/local/bin") / name).symlink_to(binary.parent / name)

        archive(
            "NODE",
            f"https://nodejs.org/dist/v{versions['NODE']}/node-v{versions['NODE']}-linux-arm64.tar.xz",
            target=Path("/usr/local"),
            strip=1,
        )
        Path("/usr/local/bin/nodejs").symlink_to("node")
        run("npm", "install", "--global", f"pnpm@{versions['PNPM']}")
        run("npm", "cache", "clean", "--force")

        archive(
            "GO",
            f"https://go.dev/dl/go{versions['GO']}.linux-arm64.tar.gz",
            target=Path("/usr/local"),
        )
        for name in ("go", "gofmt"):
            (Path("/usr/local/bin") / name).symlink_to(f"/usr/local/go/bin/{name}")

        rust = f"rust-{versions['RUST']}-aarch64-unknown-linux-gnu"
        archive("RUST", f"https://static.rust-lang.org/dist/{rust}.tar.xz")
        run(
            "sh",
            str(root / rust / "install.sh"),
            "--prefix=/usr/local",
            "--disable-ldconfig",
            "--components=rustc,rust-std-aarch64-unknown-linux-gnu,cargo,rustfmt-preview,clippy-preview",
        )
        run("ldconfig")

        gh = f"gh_{versions['GH']}_linux_arm64"
        archive("GH", f"https://github.com/cli/cli/releases/download/v{versions['GH']}/{gh}.tar.gz")
        shutil.copytree(root / gh, "/usr/local", dirs_exist_ok=True)

        rg = f"ripgrep-{versions['RIPGREP']}-aarch64-unknown-linux-gnu"
        archive(
            "RIPGREP",
            f"https://github.com/BurntSushi/ripgrep/releases/download/{versions['RIPGREP']}/{rg}.tar.gz",
        )
        shutil.copy2(root / rg / "rg", "/usr/local/bin/rg")
        shutil.copytree(root / rg, "/usr/local/share/ripgrep", dirs_exist_ok=True)

        aws = download(
            f"https://awscli.amazonaws.com/awscli-exe-linux-aarch64-{versions['AWSCLI']}.zip",
            os.environ["AWSCLI_SHA256"],
            root / "aws.zip",
        )
        run("unzip", "-q", str(aws), "-d", str(root))
        run(
            str(root / "aws/install"),
            "--install-dir",
            "/usr/local/aws-cli",
            "--bin-dir",
            "/usr/local/bin",
        )

    # Fail the build if an unexpected executable shadows any pinned runtime.
    checks = {
        "python3": versions["PYTHON"],
        "python3.13": versions["MCP_PYTHON"],
        "node": versions["NODE"],
        "uv": versions["UV"],
        "uvx": versions["UV"],
        "pnpm": versions["PNPM"],
        "rustc": versions["RUST"],
        "gh": versions["GH"],
        "aws": versions["AWSCLI"],
        "rg": versions["RIPGREP"],
    }
    for command, version in checks.items():
        output = subprocess.check_output([command, "--version"], text=True)
        if version not in output:
            raise ValueError(f"Unexpected {command} version")
    run("go", "version")


if __name__ == "__main__":
    main()
