"""Validate runtime documentation and pinned contract data without another checkout."""

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def anchors(document):
    result, counts, fenced = set(), {}, False
    for line in document.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if fenced or not line.startswith("#"):
            continue
        slug = re.sub(r"[^\w\- ]", "", re.sub(r"^#+\s+", "", line).lower()).replace(" ", "-")
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(slug if number == 0 else f"{slug}-{number}")
    return result


def check_documents():
    documents = [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md"), *ROOT.glob("contracts/**/*.md")]
    documents.append(ROOT / "src/agentcore_runtime/README.md")
    for document in documents:
        content = document.read_text()
        assert content.count("```") % 2 == 0, document
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            assert target.exists(), f"Missing documentation target: {document.name}: {link}"
            if parsed.fragment and target.suffix == ".md":
                assert unquote(parsed.fragment) in anchors(target), link
    print(f"Verified {len(documents)} runtime documents and their local links.")


def check_contract():
    directory = ROOT / "contracts/v1"
    pin = json.loads((directory / "upstream.json").read_text())
    for name, expected in pin["sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected, name
    schema = json.loads((directory / "connection.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    cases = json.loads((directory / "fixtures.json").read_text())
    for case in cases["valid"]:
        validator.validate(case["descriptor"])
    for case in cases["invalid"]:
        assert not validator.is_valid(case["descriptor"]), case["name"]
    print("Verified the independently pinned contract schema and fixtures.")


def check_boundaries():
    sources = [
        source
        for source in (ROOT / "src/agentcore_runtime").rglob("*.py")
        if not {"node_modules", "cdk.out", "__pycache__"}.intersection(source.parts)
    ]
    local_modules = {source.stem for source in [*sources, *ROOT.glob("scripts/*.py")]}
    allowed = (
        sys.stdlib_module_names
        | local_modules
        | {"agentcore_runtime", "boto3", "botocore", "bedrock_agentcore", "pytest", "jsonschema"}
    )
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                modules = [node.module]
            assert {module.split(".")[0] for module in modules} <= allowed, source
    for name in ("LICENSE", "NOTICE"):
        assert (ROOT / name).is_file()
    print("Verified runtime implementation boundaries and root legal files.")


if __name__ == "__main__":
    check_documents()
    check_contract()
    check_boundaries()
