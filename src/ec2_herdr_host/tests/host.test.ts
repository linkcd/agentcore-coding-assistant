import assert from "node:assert/strict";
import test from "node:test";
import { App, Stack, aws_ec2 as ec2 } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { HerdrHostStack, MODEL_ID, PROFILE_REGIONS } from "../host-stack";
import { loadHostNetworkConfig } from "../host-config";

const ACCOUNT = "123456789012";
const VPC_ID = "vpc-" + "0".repeat(8);
const PUBLIC_SUBNET = "subnet-" + "1".repeat(8);
const PRIVATE_SUBNET = "subnet-" + "2".repeat(8);
const ISOLATED_SUBNET = "subnet-" + "3".repeat(8);

// A VPC lookup needs AWS credentials, so tests import a synthetic VPC with the same shape.
function build(props: { volumeSizeGiB?: number; subnetId?: string } = {}, context: Record<string, string> = {}) {
  const app = new App({ context });
  const env = { account: ACCOUNT, region: "eu-west-1" };
  const vpc = ec2.Vpc.fromVpcAttributes(new Stack(app, "Network", { env }), "Vpc", {
    vpcId: VPC_ID, availabilityZones: ["eu-west-1a"],
    publicSubnetIds: [PUBLIC_SUBNET], privateSubnetIds: [PRIVATE_SUBNET], isolatedSubnetIds: [ISOLATED_SUBNET],
  });
  return new HerdrHostStack(app, "TestHost", { env, vpcId: VPC_ID, subnetId: PUBLIC_SUBNET, vpc, ...props });
}
const synth = (props: Parameters<typeof build>[0] = {}, context: Record<string, string> = {}) =>
  Template.fromStack(build(props, context));

test("the host is a t3.large with IMDSv2 required and an encrypted gp3 root volume", () => {
  synth().hasResourceProperties("AWS::EC2::Instance", {
    InstanceType: "t3.large",
    MetadataOptions: Match.objectLike({ HttpTokens: "required" }),
    BlockDeviceMappings: [Match.objectLike({
      DeviceName: "/dev/xvda", Ebs: Match.objectLike({ VolumeSize: 30, VolumeType: "gp3", Encrypted: true }),
    })],
  });
});

test("volume size can be overridden", () => {
  synth({ volumeSizeGiB: 100 }).hasResourceProperties("AWS::EC2::Instance", {
    BlockDeviceMappings: [Match.objectLike({ Ebs: Match.objectLike({ VolumeSize: 100 }) })],
  });
});

test("the security group has no inbound rules and the stack creates no network", () => {
  const template = synth();
  const groups = template.findResources("AWS::EC2::SecurityGroup");
  assert.equal(Object.keys(groups).length, 1);
  for (const group of Object.values(groups)) assert.equal((group.Properties as any).SecurityGroupIngress, undefined);
  template.resourceCountIs("AWS::EC2::SecurityGroupIngress", 0);
  for (const type of ["VPC", "Subnet", "NatGateway", "InternetGateway", "RouteTable", "Route"]) {
    template.resourceCountIs(`AWS::EC2::${type}`, 0);
  }
  template.hasResourceProperties("AWS::EC2::SecurityGroup", { VpcId: VPC_ID });
});

test("the instance uses the supplied public subnet and gets a public IP", () => {
  synth().hasResourceProperties("AWS::EC2::Instance", {
    NetworkInterfaces: [Match.objectLike({ AssociatePublicIpAddress: true, SubnetId: PUBLIC_SUBNET })],
  });
});

test("a private subnet gets no public IP", () => {
  synth({ subnetId: PRIVATE_SUBNET }).hasResourceProperties("AWS::EC2::Instance", {
    NetworkInterfaces: [Match.objectLike({ AssociatePublicIpAddress: false, SubnetId: PRIVATE_SUBNET })],
  });
});

test("a subnet without internet egress or outside the VPC is rejected", () => {
  assert.throws(() => build({ subnetId: ISOLATED_SUBNET }), /route to an internet gateway or NAT gateway/);
  assert.throws(() => build({ subnetId: "subnet-" + "9".repeat(8) }), /must be a subnet of EC2_HOST_VPC_ID/);
});

test("network bindings come from the environment and must be existing IDs", () => {
  assert.deepEqual(loadHostNetworkConfig({ EC2_HOST_VPC_ID: VPC_ID, EC2_HOST_SUBNET_ID: PUBLIC_SUBNET }),
    { vpcId: VPC_ID, subnetId: PUBLIC_SUBNET });
  assert.throws(() => loadHostNetworkConfig({ EC2_HOST_SUBNET_ID: PUBLIC_SUBNET }), /Missing deployment variable EC2_HOST_VPC_ID/);
  assert.throws(() => loadHostNetworkConfig({ EC2_HOST_VPC_ID: "REPLACE_WITH_VPC_ID", EC2_HOST_SUBNET_ID: PUBLIC_SUBNET }),
    /Missing deployment variable EC2_HOST_VPC_ID/);
  assert.throws(() => loadHostNetworkConfig({ EC2_HOST_VPC_ID: PUBLIC_SUBNET, EC2_HOST_SUBNET_ID: PUBLIC_SUBNET }),
    /EC2_HOST_VPC_ID must be one existing vpc ID/);
});

test("the instance role is trusted by EC2 and has Session Manager access", () => {
  const template = synth();
  template.hasResourceProperties("AWS::IAM::Role", {
    AssumeRolePolicyDocument: { Statement: [Match.objectLike({ Principal: { Service: "ec2.amazonaws.com" } })] },
    ManagedPolicyArns: [Match.objectLike({
      "Fn::Join": ["", Match.arrayWith([Match.stringLikeRegexp("AmazonSSMManagedInstanceCore")])],
    })],
  });
  template.resourceCountIs("AWS::IAM::AccessKey", 0);
});

test("Bedrock access is limited to the inference profile and its destination models", () => {
  const template = synth();
  const policies = Object.values(template.findResources("AWS::IAM::Policy"));
  const policy = policies.find((resource) => (resource.Properties as any).PolicyName === "HerdrOpenCodeClaudeSonnet55EU");
  assert.ok(policy);
  const [invoke, describe] = (policy.Properties as any).PolicyDocument.Statement;
  assert.deepEqual(invoke.Action, ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]);
  assert.equal(describe.Action, "bedrock:GetInferenceProfile");
  // Expected values are written out, not taken from the stack constants.
  const arn = (rest: string) => ({ "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, `:bedrock:${rest}`]] });
  const profile = arn(`eu-west-1:${ACCOUNT}:inference-profile/eu.anthropic.claude-sonnet-5-5`);
  const models = ["eu-north-1", "eu-west-3", "eu-south-1", "eu-south-2", "eu-west-1", "eu-central-1"]
    .map((region) => arn(`${region}::foundation-model/anthropic.claude-sonnet-5-5`));
  assert.deepEqual(invoke.Resource, [profile, ...models]);
  assert.deepEqual(describe.Resource, profile);
  assert.deepEqual(PROFILE_REGIONS, ["eu-north-1", "eu-west-3", "eu-south-1", "eu-south-2", "eu-west-1", "eu-central-1"]);
  assert.equal(MODEL_ID, "eu.anthropic.claude-sonnet-5-5");
});

test("the instance waits for the Bedrock policy", () => {
  const template = synth();
  const [policyId] = Object.keys(template.findResources("AWS::IAM::Policy"));
  const instance = Object.values(template.findResources("AWS::EC2::Instance"))[0];
  assert.ok((instance.DependsOn as string[]).includes(policyId));
});

test("the AMI is a literal ID from the CDK context, not a parameter resolved at each deployment", () => {
  const key = "ssm:account=" + ACCOUNT + ":parameterName=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64:region=eu-west-1";
  const template = synth({}, { [key]: "ami-0123456789abcdef0" });
  template.hasResourceProperties("AWS::EC2::Instance", { ImageId: "ami-0123456789abcdef0" });
  const parameters = Object.values(template.toJSON().Parameters ?? {}) as Array<{ Type: string }>;
  assert.ok(!parameters.some((parameter) => parameter.Type.includes("AWS::EC2::Image::Id")));
});

test("user data installs Herdr and OpenCode and writes the Bedrock configuration", () => {
  const instance = Object.values(synth().findResources("AWS::EC2::Instance"))[0];
  const userData = JSON.stringify((instance.Properties as any).UserData);
  for (const expected of [
    "HOST_REGION='eu-west-1'", `HOST_MODEL_ID='${MODEL_ID}'`, "OPENCODE_VERSION='2.2.5'",
    "https://herdr.dev/install.sh", "https://opencode.ai/v2/install", "amazon-ssm-agent", "awscli-2",
    ".config/opencode/opencode.json", "profile ${HOST_PROFILE}",
  ]) assert.ok(userData.includes(expected), expected);
  assert.ok(!/AKIA|aws_secret_access_key|aws_access_key_id/i.test(userData));
});

test("outputs include a session command that starts Bash", () => {
  const outputs = synth().findOutputs("SessionCommand");
  const value = JSON.stringify(outputs.SessionCommand.Value);
  assert.match(value, /--document-name AWS-StartInteractiveCommand/);
  assert.match(value, /\/bin\/bash -l/);
  assert.match(value, /eu-west-1/);
});
