import * as fs from "node:fs";
import * as path from "node:path";
import { ArnFormat, CfnOutput, Stack, StackProps, Tags, aws_ec2 as ec2, aws_iam as iam } from "aws-cdk-lib";
import { Construct } from "constructs";

export const MODEL_ID = "eu.anthropic.claude-sonnet-5-5";
export const FOUNDATION_MODEL = "anthropic.claude-sonnet-5-5";
// Destination regions of the eu. inference profile. Verify with:
// aws bedrock get-inference-profile --inference-profile-identifier eu.anthropic.claude-sonnet-5-5
export const PROFILE_REGIONS = ["eu-north-1", "eu-west-3", "eu-south-1", "eu-south-2", "eu-west-1", "eu-central-1"];
export const HOST_USER = "ssm-user";
export const AWS_PROFILE_NAME = "ec2";
export const OPENCODE_VERSION = "2.2.5";

export interface HerdrHostProps extends StackProps {
  /** Existing VPC, looked up by ID. The stack creates no network resources other than its security group. */
  vpcId: string;
  /** Replaces the lookup. Tests use it, because a lookup needs AWS credentials. */
  vpc?: ec2.IVpc;
  /** Existing subnet in `vpc` with a route to the internet (internet gateway or NAT gateway). */
  subnetId: string;
  instanceType?: string;
  volumeSizeGiB?: number;
}

export class HerdrHostStack extends Stack {
  readonly instance: ec2.Instance;

  constructor(scope: Construct, id: string, props: HerdrHostProps) {
    super(scope, id, props);
    const region = this.region;

    const vpc = props.vpc ?? ec2.Vpc.fromLookup(this, "ExistingVpc", { vpcId: props.vpcId });
    const subnets = [...vpc.publicSubnets, ...vpc.privateSubnets, ...vpc.isolatedSubnets];
    // On the first synthesis, CDK returns a placeholder VPC until the lookup result is cached.
    const lookupPending = vpc.vpcId !== props.vpcId;
    const subnet = subnets.find((candidate) => candidate.subnetId === props.subnetId) ?? (lookupPending ? subnets[0] : undefined);
    if (!subnet) throw new Error("EC2_HOST_SUBNET_ID must be a subnet of EC2_HOST_VPC_ID");
    // The host needs outbound HTTPS to SSM, Bedrock, the dnf repositories, GitHub, the npm registry, and herdr.dev.
    // A lookup classifies a subnet as isolated when it has no internet gateway or NAT gateway route.
    if (vpc.isolatedSubnets.includes(subnet)) {
      throw new Error("EC2_HOST_SUBNET_ID needs a route to an internet gateway or NAT gateway");
    }
    const publicSubnet = vpc.publicSubnets.includes(subnet);
    const securityGroup = new ec2.SecurityGroup(this, "SecurityGroup", {
      vpc, allowAllOutbound: true, description: "Herdr host: no inbound rules. Access is through SSM only.",
    });

    const role = new iam.Role(this, "InstanceRole", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName("AmazonSSMManagedInstanceCore")],
    });
    const inferenceProfileArn = this.formatArn({
      service: "bedrock", resource: "inference-profile", resourceName: MODEL_ID, arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    });
    const foundationModelArns = PROFILE_REGIONS.map((profileRegion) => this.formatArn({
      service: "bedrock", region: profileRegion, account: "", resource: "foundation-model",
      resourceName: FOUNDATION_MODEL, arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    }));
    const bedrockPolicy = new iam.Policy(this, "BedrockPolicy", {
      policyName: "HerdrOpenCodeClaudeSonnet55EU",
      statements: [
        new iam.PolicyStatement({
          actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
          resources: [inferenceProfileArn, ...foundationModelArns],
        }),
        new iam.PolicyStatement({ actions: ["bedrock:GetInferenceProfile"], resources: [inferenceProfileArn] }),
      ],
    });
    role.attachInlinePolicy(bedrockPolicy);

    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      `export HOST_USER='${HOST_USER}' HOST_REGION='${region}' HOST_MODEL_ID='${MODEL_ID}'`,
      `export HOST_PROFILE='${AWS_PROFILE_NAME}' OPENCODE_VERSION='${OPENCODE_VERSION}'`,
      fs.readFileSync(path.join(__dirname, "bootstrap.sh"), "utf8"),
    );

    this.instance = new ec2.Instance(this, "Host", {
      vpc, securityGroup, role, userData,
      instanceType: new ec2.InstanceType(props.instanceType ?? "t3.large"),
      // Cached in cdk.context.json. A new AMI would replace the instance and delete its disk.
      machineImage: ec2.MachineImage.latestAmazonLinux2023({ cachedInContext: true, cpuType: ec2.AmazonLinuxCpuType.X86_64 }),
      vpcSubnets: { subnets: [subnet] },
      associatePublicIpAddress: publicSubnet,
      httpTokens: ec2.HttpTokens.REQUIRED,
      blockDevices: [{
        deviceName: "/dev/xvda",
        volume: ec2.BlockDeviceVolume.ebs(props.volumeSizeGiB ?? 30, { volumeType: ec2.EbsDeviceVolumeType.GP3, encrypted: true }),
      }],
    });
    // Without this, the instance can boot before the role can call Bedrock.
    this.instance.node.addDependency(bedrockPolicy);
    Tags.of(this.instance).add("Name", "herdr-opencode-host");

    new CfnOutput(this, "InstanceId", { value: this.instance.instanceId });
    new CfnOutput(this, "SessionCommand", {
      description: "Opens a Bash login shell through Session Manager",
      value: `aws ssm start-session --region ${region} --target ${this.instance.instanceId} `
        + `--document-name AWS-StartInteractiveCommand --parameters '{"command":["/bin/bash -l"]}'`,
    });
  }
}
