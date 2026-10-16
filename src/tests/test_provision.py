"""Provisioning contracts with no cloud or Docker side effects."""

import base64
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, WaiterError
from conftest import ARN

from herdr_agentcore import provision as module
from herdr_agentcore.cli import main, parser
from herdr_agentcore.storage import Paths, Store, UserError

MODEL = "anthropic.claude-sonnet-4-5-20250929-v1:0"
ARGS = ["provision", "--name", "herdr_opencode", "--region", "us-west-2", "--model-id", MODEL]


def test_plan_is_offline_and_does_not_create_configuration(monkeypatch, tmp_path, capsys):
    session = Mock(side_effect=AssertionError("AWS must not be contacted"))
    docker = Mock(side_effect=AssertionError("Docker must not be contacted"))
    monkeypatch.setattr(module.boto3, "Session", session)
    monkeypatch.setattr(module, "docker", docker)
    assert main([*ARGS, "--plan", "--config-dir", str(tmp_path)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert set(plan) == {"infrastructure", "runtime"}
    assert not (tmp_path / "config.json").exists()
    session.assert_not_called()
    docker.assert_not_called()


def test_execution_role_only_invokes_selected_model_and_its_profiles():
    template = module.infrastructure_template("herdr_opencode", "eu." + MODEL)
    role = template["Resources"]["ExecutionRole"]["Properties"]
    trust = role["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert trust["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"}
    statements = role["Policies"][0]["PolicyDocument"]["Statement"]
    invoke = next(s for s in statements if "bedrock:InvokeModel" in s["Action"])
    resources = [item["Fn::Sub"] for item in invoke["Resource"]]
    assert any(resource.endswith("foundation-model/" + MODEL) for resource in resources)
    assert any(resource.endswith("inference-profile/eu." + MODEL) for resource in resources)
    assert all(resource.endswith(MODEL) for resource in resources)
    assert template["Resources"]["Repository"]["DeletionPolicy"] == "Retain"


def test_runtime_has_role_but_no_explicit_credentials():
    runtime = module.runtime_template("herdr_opencode", MODEL)["Resources"]["Runtime"]["Properties"]
    assert runtime["RoleArn"] == {"Ref": "ExecutionRoleArn"}
    assert runtime["EnvironmentVariables"] == {
        "AWS_REGION": {"Ref": "AWS::Region"},
        "AWS_PROFILE": "default",
        "BEDROCK_MODEL_ID": MODEL,
    }
    assert runtime["ProtocolConfiguration"] == "HTTP"
    assert "AuthorizerConfiguration" not in runtime  # IAM is the default.


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--name", "invalid-name"),
        ("--name", "1invalid"),
        ("--region", "bad region"),
        ("--model-id", "arn:aws:bedrock:region:account:model/x"),
        ("--opencode-version", "latest"),
        ("--profile", "../outside"),
    ],
)
def test_invalid_provisioning_options_are_rejected_before_side_effects(flag, value, tmp_path):
    assert main([*ARGS, flag, value, "--plan", "--config-dir", str(tmp_path)]) == 1


def test_stack_inspection_distinguishes_missing_from_denied():
    client = Mock()
    client.describe_stacks.side_effect = ClientError(
        {"Error": {"Code": "ValidationError", "Message": "Stack test does not exist"}},
        "DescribeStacks",
    )
    assert module.inspect_stack(client, "test", "deployment", False) is None
    client.describe_stacks.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DescribeStacks"
    )
    with pytest.raises(ClientError):
        module.inspect_stack(client, "test", "deployment", False)


@pytest.mark.parametrize(
    "tags,update,status",
    [
        ([], True, "CREATE_COMPLETE"),
        ([{"Key": module.OWNER_TAG, "Value": "deployment"}], False, "CREATE_COMPLETE"),
        ([{"Key": module.OWNER_TAG, "Value": "deployment"}], True, "UPDATE_IN_PROGRESS"),
    ],
)
def test_existing_stack_requires_ownership_explicit_update_and_stable_state(tags, update, status):
    client = Mock()
    client.describe_stacks.return_value = {"Stacks": [{"Tags": tags, "StackStatus": status}]}
    with pytest.raises(UserError):
        module.inspect_stack(client, "test", "deployment", update)


def test_stack_wait_failure_is_not_reported_as_ready():
    client = Mock()
    client.get_waiter.return_value.wait.side_effect = WaiterError("wait", "failed", {})
    with pytest.raises(UserError, match="did not complete"):
        module.apply_stack(client, "test", "deployment", {}, None)
    client.describe_stacks.assert_not_called()


def test_stack_noop_update_uses_existing_identity_without_creating():
    client = Mock()
    client.update_stack.side_effect = ClientError(
        {"Error": {"Code": "ValidationError", "Message": "No updates are to be performed."}},
        "UpdateStack",
    )
    client.describe_stacks.return_value = {
        "Stacks": [{"Outputs": [{"OutputKey": "RuntimeArn", "OutputValue": ARN}]}]
    }
    assert module.apply_stack(client, "test", "deployment", {}, {"StackId": "owned-stack"}) == {
        "RuntimeArn": ARN
    }
    assert client.update_stack.call_args.kwargs["StackName"] == "owned-stack"
    client.create_stack.assert_not_called()
    client.get_waiter.assert_not_called()


def test_provision_saves_direct_launcher_profile_only_after_runtime_ready(monkeypatch, tmp_path):
    args = parser().parse_args([*ARGS, "--aws-profile", "deployer"])
    store = Store(Paths(tmp_path / "config", tmp_path / "state"))
    monkeypatch.setattr(
        module,
        "docker",
        Mock(
            side_effect=lambda *args, **kwargs: (
                "[]" if args[0] == "info" else "unix:///example.sock"
            )
        ),
    )
    monkeypatch.setattr(module.boto3, "Session", Mock())
    monkeypatch.setattr(module, "inspect_stack", Mock(return_value=None))
    monkeypatch.setattr(module, "push_image", Mock(return_value="image@sha256:example"))
    stages = []

    def apply(client, name, deployment, template, existing, parameters=None):
        assert not store.profiles()
        stages.append(name)
        if name.endswith("-image"):
            return {"ExecutionRoleArn": "role-for-test"}
        assert parameters == {
            "ImageUri": "image@sha256:example",
            "ExecutionRoleArn": "role-for-test",
        }
        return {"RuntimeArn": ARN}

    monkeypatch.setattr(module, "apply_stack", apply)
    module.provision(args, store)
    assert stages == ["herdr-herdr-opencode-image", "herdr-herdr-opencode-runtime"]
    profile = store.profiles()["default"]
    assert profile.runtime_arn == ARN
    assert profile.command == ["/app/run.sh"]  # No compatibility credential shim needed.
    assert profile.aws_profile == "deployer"


def test_existing_connector_profile_is_preserved_before_any_deployment(store, monkeypatch):
    docker = Mock()
    monkeypatch.setattr(module, "docker", docker)
    with pytest.raises(UserError, match="--replace"):
        module.provision(parser().parse_args(ARGS), store)
    docker.assert_not_called()


def test_push_uses_arm64_ephemeral_login_and_returns_digest(monkeypatch):
    registry = "123456789012.dkr.ecr.us-west-2.amazonaws.com"
    ecr = Mock()
    ecr.get_authorization_token.return_value = {
        "authorizationData": [
            {
                "proxyEndpoint": f"https://{registry}",
                "authorizationToken": base64.b64encode(b"AWS:synthetic-token").decode(),
            }
        ]
    }
    ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:" + "a" * 64}]}
    calls = []

    def docker(*args, **kwargs):
        config = Path(kwargs["env"]["DOCKER_CONFIG"])
        assert config.is_dir()
        assert json.loads((config / "config.json").read_text()) == {
            "cliPluginsExtraDirs": ["/example/plugins"]
        }
        assert kwargs["env"]["DOCKER_HOST"] == "unix:///example.sock"
        assert "DOCKER_CONTEXT" not in kwargs["env"]
        assert "synthetic-token" not in " ".join(args)
        calls.append((args, kwargs, config))

    monkeypatch.setattr(module, "docker", docker)
    result = module.push_image(
        ecr,
        {"RepositoryUri": f"{registry}/example", "RepositoryName": "example"},
        "1.18.30",
        "unix:///example.sock",
        ["/example/plugins"],
    )
    assert result == f"{registry}/example@sha256:" + "a" * 64
    assert calls[1][1]["input"] == "synthetic-token"
    assert "--password-stdin" in calls[1][0]
    build = calls[2][0]
    assert build[build.index("--platform") + 1] == "linux/arm64"
    assert "--push" in build and "--provenance=false" in build
    assert not calls[0][2].exists()
