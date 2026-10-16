"""Provision the packaged OpenCode image, runtime role, and AgentCore deployment.

Two CloudFormation stacks own infrastructure and runtime separately, allowing
the image to be pushed before the runtime is created. No populated deployment
files or credentials are written into the checkout.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, WaiterError

from .storage import Profile, Store, UserError, profile_name

IMAGE_CONTEXT = Path(__file__).parent / "runtime_image"
OWNER_TAG = "herdr-agentcore-deployment"


def validate_options(args):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", args.name):
        raise UserError(
            "Runtime name must use 1–48 letters, digits, or underscores; start with a letter."
        )
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", args.region):
        raise UserError("Supply an AWS region such as us-west-2.")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.:-]{0,199}", args.model_id):
        raise UserError(
            "Supply a Bedrock foundation-model or system inference-profile ID, not an ARN."
        )
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.opencode_version):
        raise UserError("OpenCode version must be a pinned release, such as 1.18.30.")
    profile_name(args.profile)


def sub(value: str) -> dict:
    return {"Fn::Sub": value}


def allow(actions, resources) -> dict:
    return {"Effect": "Allow", "Action": actions, "Resource": resources}


def infrastructure_template(name: str, model_id: str) -> dict:
    base_model = re.sub(r"^(us|eu|apac|global)\.", "", model_id)
    model_resources = [sub(f"arn:${{AWS::Partition}}:bedrock:*::foundation-model/{base_model}")]
    # OpenCode can choose a geographic system inference profile automatically.
    # Grant only this model family, including the selected profile and its targets.
    for prefix in ("", "us.", "eu.", "apac.", "global."):
        model_resources.append(
            sub(
                "arn:${AWS::Partition}:bedrock:*:${AWS::AccountId}:inference-profile/"
                + prefix
                + base_model
            )
        )
    logs = sub(
        "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:"
        f"log-group:/aws/bedrock-agentcore/runtimes/{name}-*"
    )
    trust = {
        "Effect": "Allow",
        "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}},
            "ArnLike": {
                "aws:SourceArn": sub(
                    "arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:"
                    f"${{AWS::AccountId}}:runtime/{name}-*"
                )
            },
        },
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            allow(
                ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], model_resources
            ),
            allow("bedrock:ListInferenceProfiles", "*"),
            allow(
                ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                {"Fn::GetAtt": ["Repository", "Arn"]},
            ),
            allow("ecr:GetAuthorizationToken", "*"),
            allow(
                [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:PutResourcePolicy",
                ],
                logs,
            ),
            allow(
                "logs:DescribeLogGroups",
                sub("arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:*"),
            ),
        ],
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Herdr OpenCode image repository and AgentCore execution role",
        "Resources": {
            "Repository": {
                "Type": "AWS::ECR::Repository",
                "DeletionPolicy": "Retain",
                "UpdateReplacePolicy": "Retain",
                "Properties": {
                    "ImageTagMutability": "IMMUTABLE",
                    "ImageScanningConfiguration": {"ScanOnPush": True},
                    "EncryptionConfiguration": {"EncryptionType": "AES256"},
                },
            },
            "ExecutionRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "AssumeRolePolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [trust],
                    },
                    "Policies": [{"PolicyName": "RuntimeAccess", "PolicyDocument": policy}],
                },
            },
        },
        "Outputs": {
            "RepositoryUri": {"Value": {"Fn::GetAtt": ["Repository", "RepositoryUri"]}},
            "RepositoryName": {"Value": {"Ref": "Repository"}},
            "ExecutionRoleArn": {"Value": {"Fn::GetAtt": ["ExecutionRole", "Arn"]}},
        },
    }


def runtime_template(name: str, model_id: str) -> dict:
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Herdr-managed OpenCode on AgentCore Runtime",
        "Parameters": {"ImageUri": {"Type": "String"}, "ExecutionRoleArn": {"Type": "String"}},
        "Resources": {
            "Runtime": {
                "Type": "AWS::BedrockAgentCore::Runtime",
                "Properties": {
                    "AgentRuntimeName": name,
                    "AgentRuntimeArtifact": {
                        "ContainerConfiguration": {"ContainerUri": {"Ref": "ImageUri"}}
                    },
                    "RoleArn": {"Ref": "ExecutionRoleArn"},
                    "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
                    "ProtocolConfiguration": "HTTP",
                    "EnvironmentVariables": {
                        "AWS_REGION": {"Ref": "AWS::Region"},
                        "AWS_PROFILE": "default",
                        "BEDROCK_MODEL_ID": model_id,
                    },
                    "LifecycleConfiguration": {
                        "IdleRuntimeSessionTimeout": 900,
                        "MaxLifetime": 28800,
                    },
                },
            },
        },
        "Outputs": {"RuntimeArn": {"Value": {"Fn::GetAtt": ["Runtime", "AgentRuntimeArn"]}}},
    }


def inspect_stack(client, name: str, deployment: str, update: bool):
    try:
        stack = client.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as exc:
        error = exc.response["Error"]
        if error["Code"] == "ValidationError" and "does not exist" in error.get("Message", ""):
            return None
        raise
    tags = {tag["Key"]: tag["Value"] for tag in stack.get("Tags", [])}
    if tags.get(OWNER_TAG) != deployment:
        raise UserError(f"Stack {name} is not owned by this deployment.")
    if not update:
        raise UserError(f"Stack {name} already exists. Use --update to update this deployment.")
    if stack["StackStatus"] not in {
        "CREATE_COMPLETE",
        "UPDATE_COMPLETE",
        "UPDATE_ROLLBACK_COMPLETE",
    }:
        raise UserError(
            f"Stack {name} is {stack['StackStatus']}; resolve it in CloudFormation first."
        )
    return stack


def apply_stack(client, name, deployment, template, existing, parameters=None):
    request = {
        "StackName": existing["StackId"] if existing else name,
        "TemplateBody": json.dumps(template),
        "Parameters": [
            {"ParameterKey": k, "ParameterValue": v} for k, v in (parameters or {}).items()
        ],
        "Capabilities": ["CAPABILITY_IAM"],
        "Tags": [{"Key": OWNER_TAG, "Value": deployment}],
    }
    operation = "update" if existing else "create"
    print(f"CloudFormation {operation}: {name}", flush=True)
    try:
        if existing:
            client.update_stack(**request)
        else:
            client.create_stack(**request, OnFailure="ROLLBACK", TimeoutInMinutes=20)
    except ClientError as exc:
        error = exc.response["Error"]
        if not (
            existing
            and error["Code"] == "ValidationError"
            and "No updates are to be performed" in error.get("Message", "")
        ):
            raise
    else:
        try:
            client.get_waiter(f"stack_{operation}_complete").wait(
                StackName=request["StackName"], WaiterConfig={"Delay": 5, "MaxAttempts": 240}
            )
        except WaiterError as exc:
            raise UserError(
                f"Stack {name} did not complete; inspect its CloudFormation events."
            ) from exc
    stack = client.describe_stacks(StackName=request["StackName"])["Stacks"][0]
    return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}


def docker(*args, env=None, input=None, capture=False):
    result = subprocess.run(
        ["docker", *args],
        env=env,
        input=input,
        text=True,
        check=False,
        capture_output=capture,
        timeout=1800 if "build" in args else 60,
    )
    if result.returncode:
        raise UserError(f"Docker {args[0]} failed (exit {result.returncode}).")
    return result.stdout.strip() if capture else None


@contextmanager
def docker_environment(docker_host: str, plugin_dirs: list[str]):
    # Keep the ECR push token out of the user's Docker configuration and build
    # context. This is deployment authentication, never runtime model credentials.
    with tempfile.TemporaryDirectory(prefix="herdr-ecr-") as directory:
        # Docker Desktop often installs buildx in a user-configured plugin
        # directory. Preserve discovery paths, not the user's stored logins.
        (Path(directory) / "config.json").write_text(
            json.dumps({"cliPluginsExtraDirs": plugin_dirs})
        )
        env = dict(os.environ, DOCKER_CONFIG=directory, DOCKER_HOST=docker_host)
        env.pop("DOCKER_CONTEXT", None)
        yield env


def push_image(ecr, infrastructure, version: str, docker_host: str, plugin_dirs: list[str]) -> str:
    tag = "build-" + uuid.uuid4().hex
    repository = infrastructure["RepositoryUri"]
    registry = repository.split("/", 1)[0]
    authorization = ecr.get_authorization_token()["authorizationData"][0]
    if authorization["proxyEndpoint"] != f"https://{registry}":
        raise UserError("ECR authorization endpoint did not match the deployment repository.")
    username, password = (
        base64.b64decode(authorization["authorizationToken"]).decode().split(":", 1)
    )
    with docker_environment(docker_host, plugin_dirs) as env:
        docker("buildx", "version", capture=True, env=env)
        docker(
            "login",
            "--username",
            username,
            "--password-stdin",
            registry,
            input=password,
            capture=True,
            env=env,
        )
        docker(
            "buildx",
            "build",
            "--platform",
            "linux/arm64",
            "--provenance=false",
            "--sbom=false",
            "--build-arg",
            f"OPENCODE_VERSION={version}",
            "--tag",
            f"{repository}:{tag}",
            "--push",
            str(IMAGE_CONTEXT),
            env=env,
        )
    image = ecr.describe_images(
        repositoryName=infrastructure["RepositoryName"], imageIds=[{"imageTag": tag}]
    )["imageDetails"][0]
    return f"{repository}@{image['imageDigest']}"


def provision(args, store: Store):
    validate_options(args)
    infrastructure = infrastructure_template(args.name, args.model_id)
    runtime = runtime_template(args.name, args.model_id)
    if args.plan:
        print(json.dumps({"infrastructure": infrastructure, "runtime": runtime}, indent=2))
        return
    if args.profile in store.profiles() and not args.replace:
        raise UserError(f"Profile '{args.profile}' already exists. Use --replace to update it.")
    stack_prefix = "herdr-" + args.name.replace("_", "-")
    infrastructure_name, runtime_name = stack_prefix + "-image", stack_prefix + "-runtime"
    plugins = json.loads(docker("info", "--format", "{{json .ClientInfo.Plugins}}", capture=True))
    plugin_dirs = sorted({str(Path(plugin["Path"]).parent) for plugin in plugins})
    docker("buildx", "version", capture=True)
    docker_host = (
        os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    ) or docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", capture=True)
    if not docker_host.startswith("unix://"):
        raise UserError("Provisioning requires a local Docker engine with a Unix socket.")
    try:
        session = boto3.Session(profile_name=args.aws_profile, region_name=args.region)
        client = session.client("cloudformation")
        # Check both stacks before making changes, including after a partial deployment.
        old_infrastructure = inspect_stack(client, infrastructure_name, args.name, args.update)
        old_runtime = inspect_stack(client, runtime_name, args.name, args.update)
        outputs = apply_stack(
            client, infrastructure_name, args.name, infrastructure, old_infrastructure
        )
        image_uri = push_image(
            session.client("ecr"), outputs, args.opencode_version, docker_host, plugin_dirs
        )
        deployed = apply_stack(
            client,
            runtime_name,
            args.name,
            runtime,
            old_runtime,
            {"ImageUri": image_uri, "ExecutionRoleArn": outputs["ExecutionRoleArn"]},
        )
    except (ClientError, BotoCoreError) as exc:
        code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
        raise UserError(
            f"Provisioning failed ({code}). Inspect stacks {infrastructure_name} and "
            f"{runtime_name}; use --update after resolving any failed stack."
        ) from exc
    profile = Profile.from_dict(
        {"runtime_arn": deployed["RuntimeArn"], "aws_profile": args.aws_profile}
    )
    print(f"Runtime ready: {profile.runtime_arn}", flush=True)
    store.save_profile(args.profile, profile, replace=args.replace)
    print(f"Saved connector profile {args.profile} to {store.paths.config / 'config.json'}")
    print("Connect using the AgentCore new-agent action in Herdr.")
