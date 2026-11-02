"""Verify runtime source boundaries, dependencies, and contract data."""

import tomllib
from pathlib import Path

import pytest
from check_repository import check_boundaries, check_contract
from runtime_connection import UserError, runtime_target


def test_runtime_tooling_has_no_application_package_dependencies():
    root = Path(__file__).resolve().parents[3]
    components = {path.name for path in (root / "src").iterdir() if path.is_dir()}
    assert components == {"agentcore_runtime", "ec2_herdr_host"}
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    assert metadata["project"]["dependencies"] == []
    assert metadata["tool"]["uv"]["package"] is False
    check_boundaries()


def test_contract_pin_and_shared_fixtures():
    check_contract()


def test_probe_target_uses_runtime_arn_and_derives_region():
    target = runtime_target(
        "arn:aws:bedrock-agentcore:eu-west-1:123456789012:runtime/example-Abc123"
    )
    assert target.region == "eu-west-1" and target.endpoint == "DEFAULT"
    with pytest.raises(UserError):
        runtime_target("https://example.invalid/runtime")
