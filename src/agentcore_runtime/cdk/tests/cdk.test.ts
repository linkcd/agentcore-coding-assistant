import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as path from "node:path";
import { spawnSync } from "node:child_process";
import { App } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { RuntimeStack } from "../runtime-stack";
import { IMAGE_DIRECTORY, loadImage } from "../image";
import { loadProfile, loadRuntimeEnvironment, parseProfile, REPOSITORY_ROOT, RUNTIME_ROOT, RuntimeProfile } from "../profile";

const CODEX = "codex-agentcore-profile-1";
const OPENCODE = "opencode-agentcore-profile-2";
const STORAGE = "opencode-s3filesystem-agentcore-profile-3";
const PROFILE_NAMES = [CODEX, OPENCODE, STORAGE];
// Tests use synthetic bindings, never the developer's .env or AWS credentials.
const TEST_ENV = {
  SHARED_VPC_SUBNET_IDS: "subnet-" + "0".repeat(8) + ",subnet-" + "1".repeat(8),
  SHARED_VPC_SECURITY_GROUP_IDS: "sg-" + "0".repeat(8),
  SHARED_S3_FILES_ACCESS_POINT_ARN: `arn:aws:s3files:eu-west-1:123456789012:file-system/fs-${"0".repeat(17)}/access-point/fsap-${"0".repeat(17)}`,
};
const profileFor = (name: string) => loadProfile(name, TEST_ENV);

function template(name = OPENCODE, profile: RuntimeProfile = profileFor(name)) {
  const stack = new RuntimeStack(new App(), profile.stackName, {
    account: "123456789012", profileName: name, profile,
    imageDefinition: loadImage(profile.image),
  });
  return Template.fromStack(stack);
}

test("the repository has exactly the three requested sample profiles", () => {
  const names = fs.readdirSync(path.resolve(__dirname, "../../provision_profiles"))
    .filter((name) => name.endsWith(".json")).map((name) => name.slice(0, -5));
  assert.deepEqual(new Set(names), new Set(PROFILE_NAMES));
  const codex = loadProfile(CODEX, {});
  const opencode = loadProfile(OPENCODE, {});
  const storage = profileFor(STORAGE);
  assert.equal(codex.inference.modelId, "global.openai.gpt-5.6-sol");
  assert.equal(opencode.inference.modelId, "global.moonshotai.kimi-k3");
  assert.deepEqual(opencode.inference, storage.inference);
  assert.equal(opencode.inference["bedrock-endpoint-type"], "runtime");
  assert.equal(opencode.environment, undefined);
  assert.equal(storage.environment, undefined);
  assert.equal(codex.vpc, undefined);
  assert.equal(opencode.vpc, undefined);
  assert.ok(storage.vpc && storage.s3Files);
  for (const profile of [codex, opencode, storage]) {
    assert.equal(profile.inference["bedrock-endpoint-type"], "runtime");
    assert.equal(profile.inference.region, undefined);
    assert.equal(profile.command, undefined);
    assert.equal(profile.agentKind, undefined);
    assert.equal(profile.environment, undefined);
    assert.equal(profile.tags, undefined);
  }
});

test("public samples have no VPC, storage lookup, or mount requirement", () => {
  for (const name of [CODEX, OPENCODE]) {
    const profile = profileFor(name);
    const t = template(name);
    t.resourceCountIs("AWS::BedrockAgentCore::Runtime", 1);
    t.resourceCountIs("AWS::IAM::Role", 1);
    t.resourceCountIs("Custom::AWS", 0);
    t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
      AgentRuntimeName: profile.runtimeName, ProtocolConfiguration: "HTTP",
      NetworkConfiguration: { NetworkMode: "PUBLIC" },
      FilesystemConfigurations: Match.absent(),
      LifecycleConfiguration: { IdleRuntimeSessionTimeout: 900, MaxLifetime: 28800 },
      EnvironmentVariables: {
        AWS_REGION: profile.region,
        BEDROCK_INFERENCE_REGION: profile.inference.region ?? profile.region,
        BEDROCK_MODEL_ID: profile.inference.modelId,
        BEDROCK_ENDPOINT_TYPE: profile.inference["bedrock-endpoint-type"],
        CODEX_BEDROCK_BASE_URL: Match.absent(),
        CODEX_AGENTS_ENABLED: Match.absent(), CODEX_WEB_SEARCH: Match.absent(),
        AGENTCORE_REQUIRED_MOUNT: Match.absent(), AGENTCORE_WORKDIR: Match.absent(),
        AWS_PROFILE: Match.absent(),
      },
    });
    t.hasResourceProperties("AWS::IAM::Role", {
      AssumeRolePolicyDocument: { Statement: Match.arrayWith([Match.objectLike({
        Principal: { Service: "bedrock-agentcore.amazonaws.com" },
        Condition: { StringEquals: { "aws:SourceAccount": "123456789012" }, ArnLike: Match.anyValue() },
      })]) },
    });
  }
});

test("sample deployments have no custom tags or serialized OpenCode configuration", () => {
  for (const name of PROFILE_NAMES) {
    const t = template(name);
    t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
      Tags: Match.absent(), EnvironmentVariables: {
        OPENCODE_CONFIG: Match.absent(), OPENCODE_CONFIG_CONTENT: Match.absent(),
      },
    });
    t.hasResourceProperties("AWS::IAM::Role", { Tags: Match.absent() });
  }
});

test("image definitions declare explicit commands and hints with validated overrides", () => {
  assert.deepEqual(loadImage("opencode").command, ["/app/run.sh"]);
  assert.equal(loadImage("codex").agentKind, "codex");
  assert.throws(() => loadImage("../outside"), /image reference/);
  const command = ["/opt/assistant/start", "--project", "a b"];
  const profile = { ...profileFor(OPENCODE), command, agentKind: null };
  const output = JSON.stringify(template(OPENCODE, profile).toJSON().Outputs.ConnectionDescriptor);
  assert.ok(output.includes("/opt/assistant/start") && output.includes("agentcore-shell-v1"));
  assert.ok(output.includes('"agent_kind":null') || output.includes('\\"agent_kind\\":null'));
  for (const command of [[], null, ["bad\ncommand"]]) {
    assert.throws(() => parseProfile({ ...profile, command }), /command/);
  }
});

test("profile names remain generic settings references", () => {
  const profile = parseProfile({ ...profileFor(OPENCODE), command: ["/opt/reviewer/start"] });
  assert.deepEqual(profile.command, ["/opt/reviewer/start"]);
  assert.throws(() => loadProfile("../outside", {}), /profile name/);
  assert.throws(() => loadProfile("reviewer", {}), { code: "ENOENT" });
});

test("sample inference IAM allows live model selection but not Bedrock administration", () => {
  for (const name of PROFILE_NAMES) {
    const policy = template(name).findResources("AWS::IAM::Policy");
    const statements = Object.values(policy).flatMap((p: any) => p.Properties.PolicyDocument.Statement);
    const bedrock = statements.filter((statement: any) =>
      [statement.Action].flat().some((action: string) => action.startsWith("bedrock:")));
    assert.deepEqual(new Set(bedrock.flatMap((statement: any) => [statement.Action].flat())),
      new Set(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:ListInferenceProfiles"]));
    assert.ok(bedrock.every((statement: any) => statement.Resource === "*"));
    assert.ok(!JSON.stringify(statements).includes("bedrock-mantle:"));
  }
});

test("Mantle selection changes both launch configuration and inference IAM", () => {
  for (const name of [CODEX, OPENCODE]) {
    const profile = parseProfile({ ...profileFor(name), inference: {
      "bedrock-endpoint-type": "mantle", modelId: "openai.gpt-5.6-sol", region: "us-east-2",
    } });
    const t = template(name, profile);
    t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", { EnvironmentVariables: {
      AWS_REGION: "eu-west-1", BEDROCK_INFERENCE_REGION: "us-east-2",
      BEDROCK_ENDPOINT_TYPE: "mantle", BEDROCK_MODEL_ID: "openai.gpt-5.6-sol",
    } });
    const statements = Object.values(t.findResources("AWS::IAM::Policy"))
      .flatMap((p: any) => p.Properties.PolicyDocument.Statement);
    const mantle = statements.filter((statement: any) =>
      [statement.Action].flat().some((action: string) => action.startsWith("bedrock-mantle:")));
    assert.equal(mantle.length, 1);
    assert.equal(mantle[0].Action, "bedrock-mantle:CreateInference");
    assert.ok(JSON.stringify(mantle[0].Resource).includes(":bedrock-mantle:us-east-2:123456789012:project/*"));
    assert.ok(!JSON.stringify(statements).includes("bedrock:"));
  }
});

test("the endpoint field accepts only the two exact values and rejects earlier names", () => {
  const base = profileFor(CODEX);
  for (const value of [undefined, null, "Bedrock Runtime", "Bedrock Mantle", "bedrock", "Runtime", "runtime ", [], {}]) {
    assert.throws(() => parseProfile({ ...base, inference: { ...base.inference, "bedrock-endpoint-type": value } }),
      /inference.bedrock-endpoint-type must be "runtime" or "mantle"/);
  }
  for (const field of ["api", "endpoint-type"]) {
    assert.throws(() => parseProfile({ ...base, inference: { ...base.inference, [field]: "bedrock" } }));
    assert.throws(() => parseProfile({ ...base, inference: { modelId: base.inference.modelId, [field]: "bedrock" } }));
  }
});

test("both OpenCode profiles share one image and exclude deployment data from assets", () => {
  const imageSources: string[] = [];
  for (const name of PROFILE_NAMES) {
    const profile = profileFor(name);
    const definition = loadImage(profile.image);
    assert.equal(definition.file, "common/Dockerfile");
    assert.ok(!("ASSISTANT_DIR" in definition.buildArgs));
    assert.ok(fs.existsSync(path.join(IMAGE_DIRECTORY, profile.image, "assistant.py")));
    const app = new App();
    new RuntimeStack(app, profile.stackName, {
      account: "123456789012", profileName: name, profile, imageDefinition: definition,
    });
    const assembly = app.synth();
    const staged = fs.readdirSync(assembly.directory).map((entry) => path.join(assembly.directory, entry))
      .find((entry) => fs.existsSync(path.join(entry, "common", "Dockerfile")));
    assert.ok(staged);
    assert.ok(fs.existsSync(path.join(staged, profile.image, "image.json")));
    assert.ok(!fs.existsSync(path.join(staged, profile.image === "opencode" ? "codex" : "opencode")));
    for (const excluded of ["node_modules", "provision_profiles", "cdk", ".env", ".sample.env"]) {
      assert.ok(!fs.existsSync(path.join(staged, excluded)));
    }
    if (profile.image === "opencode") imageSources.push(path.basename(staged));
  }
  assert.equal(imageSources[0], imageSources[1]);
});

test("S3 configuration uses only the access point, without direct bucket access or a lookup", () => {
  const profile = profileFor(STORAGE);
  const t = template(STORAGE);
  t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
    NetworkConfiguration: { NetworkMode: "VPC", NetworkModeConfig: {
      Subnets: profile.vpc!.subnetIds, SecurityGroups: profile.vpc!.securityGroupIds,
    } },
    FilesystemConfigurations: [{ S3FilesAccessPoint: {
      AccessPointArn: profile.s3Files!.accessPointArn, MountPath: "/mnt/workspace",
    } }],
    EnvironmentVariables: {
      AGENTCORE_WORKDIR: "/mnt/workspace", AGENTCORE_REQUIRED_MOUNT: "/mnt/workspace",
      BEDROCK_ENDPOINT_TYPE: "runtime",
    },
  });
  t.resourceCountIs("Custom::AWS", 0);
  t.resourceCountIs("AWS::Lambda::Function", 0);
  t.resourceCountIs("AWS::IAM::Role", 1);
  const fileSystemArn = profile.s3Files!.accessPointArn.split("/access-point/")[0];
  t.hasResourceProperties("AWS::IAM::Policy", { PolicyDocument: { Statement: Match.arrayWith([
    Match.objectLike({ Action: ["s3files:ClientMount", "s3files:ClientWrite"], Resource: fileSystemArn,
      Condition: { ArnEquals: { "s3files:AccessPointArn": profile.s3Files!.accessPointArn } } }),
    Match.objectLike({ Action: ["s3files:GetAccessPoint", "s3files:GetFileSystem", "s3files:GetMountTarget", "s3files:ListMountTargets"],
      Condition: Match.absent(), Resource: Match.arrayWith([profile.s3Files!.accessPointArn]) }),
  ]) } });
  const serialized = JSON.stringify(t.toJSON());
  assert.ok(!serialized.includes("s3:"), "The execution role must not bypass the access point with direct S3 grants");
  assert.ok(!serialized.includes("s3files:ClientRootAccess"));
  assert.ok(!serialized.includes('"AWS::S3::Bucket"') && !serialized.includes('"AWS::EC2::VPC"'));
  for (const key of ["S3BucketName", "S3FilesAccessPointArn", "VpcSubnetIds", "VpcSecurityGroupIds"]) {
    assert.ok(!(key in (t.toJSON().Parameters ?? {})));
  }
});

test("read-only storage omits filesystem write authorization", () => {
  const profile = profileFor(STORAGE);
  profile.s3Files!.readOnly = true;
  assert.ok(!JSON.stringify(template(STORAGE, profile).toJSON()).includes("s3files:ClientWrite"));
});

test("optional deployment overrides each affect generated resources", () => {
  const profile = parseProfile({
    ...profileFor(STORAGE), workingDirectory: "/mnt/workspace/project",
    environment: { PROJECT_MODEL: "$MODEL_ID" }, tags: { UserLabel: "custom-project" },
    lifecycle: { idleRuntimeSessionTimeout: 300, maxLifetime: 3600 },
  });
  const t = template(STORAGE, profile);
  t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
    LifecycleConfiguration: { IdleRuntimeSessionTimeout: 300, MaxLifetime: 3600 },
    EnvironmentVariables: { AGENTCORE_WORKDIR: "/mnt/workspace/project", PROJECT_MODEL: profile.inference.modelId },
  });
  assert.ok(JSON.stringify(t.toJSON()).includes("custom-project"));
});

test("duplicate, unused, and invalid profile fields are rejected", () => {
  const base = profileFor(STORAGE);
  for (const changes of [
    { account: "123456789012" }, { networkMode: "PUBLIC" }, { image: { directory: "agent_images" } },
    { inference: { ...base.inference, retainedModelIds: [] } },
    { inference: { ...base.inference, project: "default" } },
    { environment: { BEDROCK_MODEL_ID: "duplicate" } }, { environment: { AWS_REGION: "eu-west-1" } },
    { environment: { BEDROCK_ENDPOINT_TYPE: "mantle" } },
    { environment: { OPENCODE_WORKDIR: "/somewhere" } },
    { s3Files: { ...base.s3Files, bucketName: "duplicate-bucket" } },
    { s3Files: { ...base.s3Files, prefix: "agents/" } },
    { s3Files: { ...base.s3Files, mountPath: "/mnt/nested/path" } },
    { s3Files: { ...base.s3Files, readOnly: "false" } },
    { vpc: undefined }, { vpc: { subnetIds: [], securityGroupIds: null } },
    { region: ["eu-west-1"] }, { workingDirectory: "relative" }, { tags: { InvalidValue: 1 } },
    { stackName: "invalid stack" }, { stackName: "1Invalid" }, { stackName: "A".repeat(129) },
    { runtimeName: "invalid-runtime" }, { runtimeName: "A".repeat(49) },
    { lifecycle: { idleRuntimeSessionTimeout: 59, maxLifetime: 3600 } },
    { lifecycle: { idleRuntimeSessionTimeout: 3600, maxLifetime: 300 } },
  ]) assert.throws(() => parseProfile({ ...base, ...changes }));
});

test("env resolution handles CSV and fails on missing S3 bindings", () => {
  const profile = loadProfile(STORAGE, {
    ...TEST_ENV, SHARED_VPC_SUBNET_IDS: TEST_ENV.SHARED_VPC_SUBNET_IDS.replace(",", ", "),
  });
  assert.deepEqual(profile.vpc!.subnetIds, TEST_ENV.SHARED_VPC_SUBNET_IDS.split(","));
  for (const key of Object.keys(TEST_ENV)) {
    const env: Record<string, string> = { ...TEST_ENV };
    delete env[key];
    assert.throws(() => loadProfile(STORAGE, env), new RegExp(`Missing deployment variable ${key}`));
  }
  assert.doesNotThrow(() => loadProfile(OPENCODE, {}));
  assert.doesNotThrow(() => loadProfile(CODEX, {}));
});

test("S3 access points must match the deployment account and region", () => {
  const profile = profileFor(STORAGE);
  for (const target of [{ account: "111122223333", region: profile.region }, { account: "123456789012", region: "us-east-1" }]) {
    assert.throws(() => new RuntimeStack(new App(), "Mismatch", {
      account: target.account, profileName: STORAGE, profile: { ...profile, region: target.region },
      imageDefinition: loadImage(profile.image),
    }), /effective deployment account and region/);
  }
});

test("the CDK entrypoint rejects context overrides of file configuration", () => {
  for (const key of ["stackName", "runtimeName", "region", "modelId", "inferenceRegion", "command", "profileDirectory", "retainedModelIds"]) {
    const result = spawnSync(process.execPath, ["--import", require.resolve("tsx"), path.resolve(__dirname, "../app.ts")], {
      cwd: REPOSITORY_ROOT,
      env: { ...process.env, CDK_CONTEXT_JSON: JSON.stringify({ runtimeProfile: OPENCODE, [key]: "override" }) },
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, new RegExp(`Context ${key} is not supported`));
  }
});

test("the component env file is the only source of deployment bindings", (t) => {
  const envFile = path.join(RUNTIME_ROOT, ".env");
  const originalRead = fs.readFileSync;
  let exists = true;
  t.mock.method(require("node:fs"), "existsSync", (file: string) => {
    assert.equal(file, envFile);
    return exists;
  });
  t.mock.method(require("node:fs"), "readFileSync", (file: string, options: any) => {
    assert.notEqual(file, path.join(REPOSITORY_ROOT, ".env"));
    return file === envFile ? Object.entries(TEST_ENV).map(([key, value]) => `${key}=${value}`).join("\n") : originalRead(file, options);
  });
  const previous = process.env.SHARED_VPC_SUBNET_IDS;
  process.env.SHARED_VPC_SUBNET_IDS = "ambient-value-must-not-override-the-file";
  t.after(() => {
    if (previous === undefined) delete process.env.SHARED_VPC_SUBNET_IDS;
    else process.env.SHARED_VPC_SUBNET_IDS = previous;
  });
  assert.deepEqual(loadRuntimeEnvironment(), TEST_ENV);
  assert.deepEqual(loadProfile(STORAGE, loadRuntimeEnvironment()), profileFor(STORAGE));
  assert.throws(() => loadProfile(STORAGE), /Missing deployment variable SHARED_VPC_SUBNET_IDS/);
  exists = false;
  assert.deepEqual(loadRuntimeEnvironment(), {});
});

test("profile values control names, deployment region, inference region, model, and command", () => {
  const profile = parseProfile({ ...profileFor(OPENCODE),
    stackName: "ConfiguredStack", runtimeName: "configured_runtime", region: "us-west-2",
    command: ["/opt/custom/start", "--project", "a b"],
    inference: { "bedrock-endpoint-type": "runtime", modelId: "example.model", region: "us-east-2" },
    environment: { RESOLVED_SETTINGS: "$RUNTIME_REGION/$INFERENCE_REGION/$MODEL_ID" },
  });
  const stack = new RuntimeStack(new App(), profile.stackName, {
    account: "123456789012", profileName: OPENCODE, profile, imageDefinition: loadImage(profile.image),
  });
  assert.equal(stack.stackName, "ConfiguredStack");
  assert.equal(stack.region, "us-west-2");
  assert.equal(stack.account, "123456789012");
  const t = Template.fromStack(stack);
  t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
    AgentRuntimeName: "configured_runtime", EnvironmentVariables: {
      AWS_REGION: "us-west-2", BEDROCK_INFERENCE_REGION: "us-east-2", BEDROCK_MODEL_ID: "example.model",
      RESOLVED_SETTINGS: "us-west-2/us-east-2/example.model",
    },
  });
  const serialized = JSON.stringify(t.toJSON());
  assert.ok(serialized.includes("bedrock-agentcore:us-west-2:123456789012:runtime/configured_runtime-*"));
  assert.ok(JSON.stringify(t.toJSON().Outputs.ConnectionDescriptor).includes("/opt/custom/start"));
});

test("the CDK entrypoint requires a resolved authenticated account", () => {
  for (const account of ["", "invalid-account"]) {
    const result = spawnSync(process.execPath, ["--import", require.resolve("tsx"), path.resolve(__dirname, "../app.ts")], {
      cwd: REPOSITORY_ROOT,
      env: { ...process.env, CDK_DEFAULT_ACCOUNT: account,
        CDK_CONTEXT_JSON: JSON.stringify({ runtimeProfile: OPENCODE }) },
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /CDK_DEFAULT_ACCOUNT must be resolved/);
  }
});

test("logical IDs stay stable and Runtime creation waits for execution permissions", () => {
  for (const name of PROFILE_NAMES) {
    const resources = template(name).toJSON().Resources;
    assert.equal(resources.ExecutionRole605A040B.Type, "AWS::IAM::Role");
    assert.equal(resources.ExecutionRoleDefaultPolicyA5B92313.Type, "AWS::IAM::Policy");
    assert.equal(resources.Runtime.Type, "AWS::BedrockAgentCore::Runtime");
    assert.ok(resources.Runtime.DependsOn.includes("ExecutionRoleDefaultPolicyA5B92313"));
  }
});

test("Git ignores local env values but includes the env template", () => {
  const env = path.relative(REPOSITORY_ROOT, path.join(RUNTIME_ROOT, ".env"));
  const sample = path.relative(REPOSITORY_ROOT, path.join(RUNTIME_ROOT, ".sample.env"));
  assert.ok(fs.existsSync(path.join(RUNTIME_ROOT, "README.md")));
  assert.ok(fs.existsSync(path.join(RUNTIME_ROOT, ".sample.env")));
  assert.equal(spawnSync("git", ["check-ignore", "--no-index", "--quiet", env], { cwd: REPOSITORY_ROOT }).status, 0);
  assert.equal(spawnSync("git", ["check-ignore", "--no-index", "--quiet", sample], { cwd: REPOSITORY_ROOT }).status, 1);
});
