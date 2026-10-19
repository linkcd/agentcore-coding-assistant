"""Check repository links and three independent distributions without AWS calls."""

import argparse
import re
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = {
    "agentcore_contract": ("runtime_contract", "agentcore_contract", "agentcore_contract"),
    "herdr_agentcore": ("herdr_plugin", "herdr_agentcore", "herdr_agentcore"),
}


def anchors(path):
    result, counts = set(), {}
    fenced = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if fenced or not line.startswith("#"):
            continue
        heading = re.sub(r"^#+\s+", "", line).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug if not count else f"{slug}-{count}")
    return result


def check_documents(root):
    documents = sorted(
        path
        for path in [*root.glob("*.md"), *root.glob("docs/*.md"), *root.glob("src/**/*.md")]
        if not {"node_modules", "cdk.out"}.intersection(path.parts)
    )
    links = 0
    for document in documents:
        text = document.read_text()
        assert "src/herdr_agentcore/" not in text and "src/tests/" not in text, document
        assert "agentcore_runtime/agentcore_runtime/" not in text, document
        assert text.count("```") % 2 == 0, document
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            assert target.exists(), f"Missing target: {document.name}: {link}"
            if parsed.fragment and target.suffix == ".md":
                assert unquote(parsed.fragment) in anchors(target), f"Missing anchor: {link}"
            links += 1
    requirements = (root / "docs/REQUIREMENTS.md").read_text()
    for prefix, count in {"F": 18, "L": 12, "P": 7, "H": 10, "C": 9}.items():
        for number in range(1, count + 1):
            assert requirements.count(f"| {prefix}{number:02} |") == 1
    for name in ("LICENSE", "NOTICE"):
        assert (root / name).is_file()
        nested = [
            path
            for path in (root / "src").rglob(name)
            if not {"node_modules", "cdk.out"}.intersection(path.parts)
        ]
        assert not nested, f"Project legal files must be kept at the repository root: {nested}"
    print(f"Verified {len(documents)} documents, {links} local links, and 56 requirement IDs.")


def check_packages(root, directory):
    packages = {package for _, package, _ in COMPONENTS.values()}
    for distribution, (component, package, source_directory) in COMPONENTS.items():
        wheel_path = next(directory.glob(f"{distribution}-*.whl"))
        with zipfile.ZipFile(wheel_path) as wheel:
            names = wheel.namelist()
            metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
            metadata_directory = metadata_path.removesuffix("METADATA")
            for legal in ("LICENSE", "NOTICE"):
                assert (
                    wheel.read(metadata_directory + "extra_metadata/" + legal)
                    == (root / legal).read_bytes()
                )
            assert not any(
                "__pycache__" in name or "/tests/" in name or name.startswith("tests/")
                for name in names
            )
            for other in packages - {package}:
                assert not any(name.startswith(other + "/") for name in names)
            source_root = root / "src" / component / source_directory
            for source in source_root.rglob("*"):
                if not source.is_file() or "__pycache__" in source.parts:
                    continue
                relative = source.relative_to(source_root)
                if source_directory == "." and relative.parts[0] not in {
                    "__init__.py",
                    "__main__.py",
                    "cli.py",
                    "opencode",
                }:
                    continue
                name = (Path(package) / relative).as_posix()
                assert wheel.read(name) == source.read_bytes(), f"Wheel mismatch: {name}"
            metadata = Parser().parsestr(wheel.read(metadata_path).decode())
            requirements = metadata.get_all("Requires-Dist", [])
            if package == "agentcore_contract":
                assert requirements == []
            else:
                assert any(item.startswith("agentcore-contract==") for item in requirements)
                assert not any(
                    item.startswith(("herdr-agentcore", "agentcore-runtimes"))
                    for item in requirements
                )
        with tarfile.open(next(directory.glob(f"{distribution}-*.tar.gz"))) as archive:
            files = {"/".join(item.name.split("/")[1:]): item for item in archive if item.isfile()}
            for name in ("README.md", "pyproject.toml"):
                assert (
                    archive.extractfile(files[name]).read()
                    == (root / "src" / component / name).read_bytes()
                )
            for legal in ("LICENSE", "NOTICE"):
                assert archive.extractfile(files[legal]).read() == (root / legal).read_bytes()
            assert not any("__pycache__" in name or "/.venv/" in name for name in files)
    print("Verified two isolated Python wheels/source distributions and their dependency metadata.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    check_documents(ROOT)
    check_packages(ROOT, args.dist)
