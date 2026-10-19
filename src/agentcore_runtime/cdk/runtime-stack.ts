import { ArnFormat, CfnOutput, Stack, StackProps, Tags, aws_bedrockagentcore as agentcore,
  aws_ecr_assets as assets, aws_iam as iam } from "aws-cdk-lib";
import { Construct } from "constructs";
import { connectionDescriptor, validateCommand } from "../../runtime_contract/connection";
import { RuntimeProfile } from "./profile";
import { AgentImage, IMAGE_DIRECTORY } from "./image";

export interface RuntimeProps extends Omit<StackProps, "env" | "stackName"> {
  account: string;
  profileName: string;
  profile: RuntimeProfile;
  imageDefinition: AgentImage;
}

export class RuntimeStack extends Stack {
  constructor(scope: Construct, id: string, props: RuntimeProps) {
    super(scope, id, { ...props, stackName: props.profile.stackName,
      env: { account: props.account, region: props.profile.region } });
    const definition = props.imageDefinition;
    const command = validateCommand(props.profile.command === undefined ? definition.command : props.profile.command);
    const agentKind = props.profile.agentKind === undefined ? definition.agentKind : props.profile.agentKind;
    const { runtimeName } = props.profile;
    const { modelId } = props.profile.inference;

    const generated = ["node_modules", "cdk.out", "tests", "**/__pycache__", "**/*.pyc"];
    const directory = props.profile.image;
    // The image reference is the only source for its adapter directory.
    const exclude = ["**", "!common", "!common/**", `!${directory}`, `!${directory}/**`, ...generated];
    const image = new assets.DockerImageAsset(this, "AssistantImage", {
      directory: IMAGE_DIRECTORY,
      file: definition.file,
      platform: assets.Platform.LINUX_ARM64, // AgentCore microVM container architecture.
      buildArgs: { ...definition.buildArgs, ASSISTANT_DIR: directory },
      exclude,
    });
    const role = new iam.Role(this, "ExecutionRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
          ArnLike: { "aws:SourceArn": this.formatArn({ service: "bedrock-agentcore",
            resource: "runtime", resourceName: `${runtimeName}-*`, arnFormat: ArnFormat.SLASH_RESOURCE_NAME }) },
        },
      }),
    });
    image.repository.grantPull(role);
    const inferenceRegion = props.profile.inference.region ?? this.region;
    const endpointType = props.profile.inference["bedrock-endpoint-type"];
    if (endpointType !== undefined && endpointType !== "runtime" && endpointType !== "mantle") {
      throw new Error("Invalid inference.bedrock-endpoint-type");
    }
    // Startup routing does not restrict later native model selections.
    // Both endpoints remain subject to account access and retention controls.
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], resources: ["*"],
    }));
    role.addToPolicy(new iam.PolicyStatement({ actions: ["bedrock:ListInferenceProfiles"], resources: ["*"] }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-mantle:CreateInference"],
      resources: [this.formatArn({ service: "bedrock-mantle", region: inferenceRegion,
        resource: "project", resourceName: "*", arnFormat: ArnFormat.SLASH_RESOURCE_NAME })],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "logs:PutResourcePolicy"],
      resources: [this.formatArn({ service: "logs", resource: "log-group",
        resourceName: `/aws/bedrock-agentcore/runtimes/${runtimeName}-*`, arnFormat: ArnFormat.COLON_RESOURCE_NAME })],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:DescribeLogGroups"],
      resources: [this.formatArn({ service: "logs", resource: "log-group", resourceName: "*",
        arnFormat: ArnFormat.COLON_RESOURCE_NAME })],
    }));

    let network: agentcore.CfnRuntime.NetworkConfigurationProperty = { networkMode: "PUBLIC" };
    if (props.profile.vpc) {
      network = { networkMode: "VPC", networkModeConfig: {
        subnets: props.profile.vpc.subnetIds, securityGroups: props.profile.vpc.securityGroupIds,
      } };
    }
    const filesystems: agentcore.CfnRuntime.FilesystemConfigurationProperty[] = [];
    if (props.profile.s3Files) {
      if (!props.profile.vpc) throw new Error("S3 Files requires VPC configuration");
      const { accessPointArn } = props.profile.s3Files;
      if (accessPointArn.split(":")[3] !== this.region || accessPointArn.split(":")[4] !== this.account) {
        throw new Error("S3 Files access point must match the effective deployment account and region");
      }
      const fileSystemArn = accessPointArn.split("/access-point/")[0];
      role.addToPolicy(new iam.PolicyStatement({
        actions: ["s3files:ClientMount",
          ...(props.profile.s3Files.readOnly ? [] : ["s3files:ClientWrite"])],
        resources: [fileSystemArn],
        conditions: { ArnEquals: { "s3files:AccessPointArn": accessPointArn } },
      }));
      // Runtime creation and mount setup read filesystem/access-point/target metadata.
      // These lookups do not provide the NFS-only AccessPointArn condition context.
      role.addToPolicy(new iam.PolicyStatement({
        actions: ["s3files:GetAccessPoint", "s3files:GetFileSystem", "s3files:GetMountTarget", "s3files:ListMountTargets"],
        resources: [fileSystemArn, accessPointArn],
      }));
      filesystems.push({ s3FilesAccessPoint: {
        accessPointArn, mountPath: props.profile.s3Files.mountPath,
      } });
    }
    const workingDirectory = props.profile.workingDirectory ?? props.profile.s3Files?.mountPath;
    const runtime = new agentcore.CfnRuntime(this, "Runtime", {
      agentRuntimeName: runtimeName,
      agentRuntimeArtifact: { containerConfiguration: { containerUri: image.imageUri } },
      roleArn: role.roleArn,
      networkConfiguration: network,
      filesystemConfigurations: filesystems.length ? filesystems : undefined,
      protocolConfiguration: "HTTP", // Supplied images implement the HTTP health/invocation contract.
      environmentVariables: {
        ...Object.fromEntries(Object.entries(props.profile.environment ?? {}).map(([key, value]) =>
          [key, value.replaceAll("$RUNTIME_REGION", this.region).replaceAll("$INFERENCE_REGION", inferenceRegion).replaceAll("$MODEL_ID", modelId)])),
        AWS_REGION: this.region,
        BEDROCK_MODEL_ID: modelId,
        BEDROCK_INFERENCE_REGION: inferenceRegion,
        ...(endpointType !== undefined ? { BEDROCK_ENDPOINT_TYPE: endpointType } : {}),
        ...(workingDirectory ? { AGENTCORE_WORKDIR: workingDirectory } : {}),
        ...(props.profile.s3Files ? { AGENTCORE_REQUIRED_MOUNT: props.profile.s3Files.mountPath } : {}),
      },
      lifecycleConfiguration: props.profile.lifecycle,
    });
    runtime.node.addDependency(role);
    for (const [key, value] of Object.entries(props.profile.tags ?? {})) Tags.of(this).add(key, value);

    new CfnOutput(this, "RuntimeArn", { value: runtime.attrAgentRuntimeArn });
    new CfnOutput(this, "RuntimeId", { value: runtime.attrAgentRuntimeId });
    new CfnOutput(this, "ConnectionDescriptor", {
      value: this.toJsonString(connectionDescriptor({
        runtime_arn: runtime.attrAgentRuntimeArn, region: this.region, endpoint: "DEFAULT",
        command, agent_kind: agentKind, runtime_profile: props.profileName,
      })),
    });
  }
}
