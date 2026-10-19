"""Enforce component dependency direction without importing either application."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module.split(".")[0]


def test_source_has_exactly_three_components_with_readmes():
    expected = {"agentcore_runtime", "herdr_plugin", "runtime_contract"}
    assert {path.name for path in (ROOT / "src").iterdir() if path.is_dir()} == expected
    for name in expected:
        assert (ROOT / "src" / name / "README.md").is_file()
        metadata = "cdk/package.json" if name == "agentcore_runtime" else "pyproject.toml"
        assert (ROOT / "src" / name / metadata).is_file()
    runtime = ROOT / "src/agentcore_runtime"
    assert (runtime / "cdk/cdk.json").is_file()
    assert not (runtime / "cli.py").exists()
    assert not (runtime / "pyproject.toml").exists()
    assert (runtime / "agent_images/opencode").is_dir()
    assert (runtime / "provision_profiles").is_dir()
    assert not (runtime / "agentcore_runtime").exists()


def test_implementation_dependencies_do_not_cross_runtime_and_plugin():
    for component, package, forbidden in (
        ("herdr_plugin", "herdr_agentcore", {"agentcore_runtime"}),
        ("agentcore_runtime", ".", {"herdr_agentcore"}),
    ):
        for path in (ROOT / "src" / component / package).rglob("*.py"):
            if {"tests", "node_modules", "cdk.out"}.intersection(
                path.relative_to(ROOT / "src" / component / package).parts
            ):
                continue
            assert not set(imports(path)) & forbidden, path


def test_contract_has_only_standard_library_dependencies():
    for path in (ROOT / "src/runtime_contract/agentcore_contract").glob("*.py"):
        assert set(imports(path)) <= sys.stdlib_module_names, path
