import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { App } from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { RuntimeStack } from "../runtime-stack";
import { loadProfile } from "../profile";

function template(command?: unknown, retainedModelIds: string[] = []) {
  const app = new App();
  const stack = new RuntimeStack(app, "TestRuntime", {
    env: { account: "123456789012", region: "us-west-2" },
    profileName: "opencode", profile: loadProfile("opencode"),
    runtimeName: "example", modelId: "example.model", command, retainedModelIds,
  });
  return Template.fromStack(stack);
}

test("official runtime resource, role access, and health settings", () => {
  const t = template();
  t.resourceCountIs("AWS::BedrockAgentCore::Runtime", 1);
  t.resourceCountIs("AWS::IAM::Role", 1);
  t.resourceCountIs("AWS::CloudFormation::CustomResource", 0);
  t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
    AgentRuntimeName: "example", ProtocolConfiguration: "HTTP",
    NetworkConfiguration: { NetworkMode: "PUBLIC" },
    LifecycleConfiguration: { IdleRuntimeSessionTimeout: 900, MaxLifetime: 28800 },
    EnvironmentVariables: { AWS_REGION: "us-west-2", AWS_PROFILE: "default", BEDROCK_MODEL_ID: "example.model" },
  });
  t.hasResourceProperties("AWS::IAM::Role", {
    AssumeRolePolicyDocument: { Statement: Match.arrayWith([Match.objectLike({
      Principal: { Service: "bedrock-agentcore.amazonaws.com" },
      Condition: { StringEquals: { "aws:SourceAccount": "123456789012" }, ArnLike: Match.anyValue() },
    })]) },
  });
  const serialized = JSON.stringify(t.toJSON());
  assert.ok(serialized.includes("foundation-model/example.model"));
  assert.ok(!serialized.includes("AWS_SECRET_ACCESS_KEY"));
  assert.ok(!serialized.includes("aws_profile"));
  assert.ok(serialized.includes("runtime_profile"));
});

test("definition default and custom commands are explicit output data", () => {
  assert.deepEqual(loadProfile("opencode").command, ["/app/run.sh"]);
  const command = ["/opt/assistant/start", "--project", "a b"];
  const output = JSON.stringify(template(command).toJSON().Outputs.ConnectionDescriptor);
  assert.ok(output.includes("/opt/assistant/start"));
  assert.ok(output.includes("agentcore-shell-v1"));
  assert.throws(() => template([]), /command/);
  assert.throws(() => template(["bad\ncommand"]), /command/);
});

test("profile names select settings rather than a predefined assistant enum", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "runtime-profiles-"));
  try {
    const settings = { ...loadProfile("opencode"), command: ["/opt/reviewer/start"] };
    fs.writeFileSync(path.join(directory, "reviewer.json"), JSON.stringify(settings));
    assert.deepEqual(loadProfile("reviewer", directory).command, ["/opt/reviewer/start"]);
    assert.throws(() => loadProfile("../outside", directory), /profile name/);
    assert.throws(() => loadProfile("not-defined", directory));
  } finally {
    fs.rmSync(directory, { recursive: true });
  }
});

test("Codex settings use the same CDK stack and a scoped Mantle policy", () => {
  const profile = loadProfile("codex");
  const stack = new RuntimeStack(new App(), "CodexExample", {
    env: { account: "123456789012", region: "us-east-2" },
    profileName: "codex", profile, runtimeName: profile.runtimeName,
    modelId: profile.inference.modelId, inferenceRegion: profile.inference.region,
  });
  const serialized = JSON.stringify(Template.fromStack(stack).toJSON());
  assert.ok(serialized.includes("bedrock-mantle:CreateInference"));
  assert.ok(!serialized.includes("bedrock-mantle:*"));
  assert.ok(serialized.includes("runtime_profile"));
});

test("retained model permissions are explicit CDK input", () => {
  const policy = JSON.stringify(template(undefined, ["example.previous-model"]).toJSON());
  assert.ok(policy.includes("foundation-model/example.previous-model"));
  assert.ok(policy.includes("foundation-model/example.model"));
});

test("both example profiles use the shared image and stage only their adapter", () => {
  const root = path.resolve(__dirname, "..");
  for (const name of ["opencode", "codex"]) {
    const profile = loadProfile(name);
    assert.equal(profile.image.file, "common/Dockerfile");
    assert.equal(profile.image.buildArgs?.ASSISTANT_DIR, `${name}/image`);
    assert.ok(fs.existsSync(path.join(root, name, "image", "assistant.py")));
    assert.ok(fs.existsSync(path.join(root, name, "image", "NOTICE")));
    assert.ok(!fs.existsSync(path.join(root, name, "README.md")));
    const app = new App();
    new RuntimeStack(app, `Image${name}`, {
      env: { account: "123456789012", region: "us-west-2" },
      profileName: name, profile, runtimeName: profile.runtimeName, modelId: profile.inference.modelId,
    });
    const assembly = app.synth();
    const staged = fs.readdirSync(assembly.directory)
      .map((entry) => path.join(assembly.directory, entry))
      .find((entry) => fs.existsSync(path.join(entry, "common", "Dockerfile")));
    assert.ok(staged, "CDK must stage the shared Docker context");
    assert.ok(fs.existsSync(path.join(staged, name, "image", "assistant.py")));
    assert.ok(!fs.existsSync(path.join(staged, name === "opencode" ? "codex" : "opencode")));
    assert.ok(!fs.existsSync(path.join(staged, "node_modules")));
  }
});
