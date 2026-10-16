"""Regressions for current/index/history privacy checks, using synthetic values."""

import subprocess

import pytest
from repository_privacy import audit, findings


def test_example_account_is_allowed_but_nonexample_account_is_flagged():
    assert not findings("fixture.py", b"account = '123456789012'")
    synthetic = ("account = '" + "9" * 12 + "'").encode()
    assert (1, "non-example AWS account ID") in findings("fixture.py", synthetic)


@pytest.mark.parametrize(
    "content, rule",
    [
        (("AKIA" + "A" * 16).encode(), "AWS access key"),
        (("-----BEGIN " + "PRIVATE KEY-----").encode(), "private key"),
        (("aws_secret_access_key = '" + "A" * 40 + "'").encode(), "literal AWS secret"),
        (("open_code-" + "AbCdEf1234").encode(), "deployment-style runtime ID"),
    ],
)
def test_sensitive_patterns_are_flagged_without_returning_values(content, rule):
    assert (1, rule) in findings("fixture.py", content)
    assert content.decode() not in repr(findings("fixture.py", content))


def test_generated_config_is_private_even_without_a_credential():
    assert findings("nested/runtime_config.json", b"{}")
    assert findings(".aws/config", b"{}")


def test_deleted_historical_config_is_still_detected(tmp_path):
    def run(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Privacy Test", "-c", "user.email=test@example.invalid", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    run("init", "-q")
    config = tmp_path / "runtime_config.json"
    config.write_text("{}")
    run("add", "runtime_config.json")
    run("commit", "-qm", "add synthetic private config")
    run("rm", "runtime_config.json")
    run("commit", "-qm", "remove synthetic private config")
    issues, _, commits = audit(tmp_path)
    assert commits == 2
    assert any(
        scope.startswith("history:") and path == "runtime_config.json"
        for scope, path, _, _ in issues
    )
    assert not any(scope in {"worktree", "index"} for scope, _, _, _ in issues)
