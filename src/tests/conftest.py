"""Shared configuration and state fixtures for offline tests."""

import pytest

from herdr_agentcore.storage import Paths, Profile, Store

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test_runtime-Abc123"


@pytest.fixture
def store(tmp_path):
    store = Store(Paths(tmp_path / "config", tmp_path / "state"))
    store.save_profile("default", Profile.from_dict({"runtime_arn": ARN}))
    return store


@pytest.fixture
def record(store):
    return store.create("default", "test-agent")
