import { ArnFormat, CfnOutput, Stack, StackProps, Tags, aws_bedrockagentcore as agentcore,
  aws_ecr_assets as assets, aws_iam as iam, aws_s3files as s3files } from "aws-cdk-lib";
import { Construct } from "constructs";
import * as path from "node:path";
import { connectionDescriptor, validateCommand } from "./connection";
import { REPOSITORY_ROOT, RuntimeProfile } from "./profile";
import { AgentImage, IMAGE_DIRECTORY } from "./image";
import { RuntimeInfrastructure } from "./infrastructure-stack";
import { directoryPath } from "./infrastructure-config";

// Fixed contract with the non-root agent user in the supplied runtime images.
const WORKSPACE_POSIX = { uid: "1000", gid: "1000", permissions: "755" } as const;

export interface RuntimeProps extends Omit<StackProps, "env" | "stackName"> {
  account: string;
  profileName: string;
  profile: RuntimeProfile;
  imageDefinition: AgentImage;
  infrastructure?: RuntimeInfrastructure;
}

export class RuntimeStack extends Stack {
  constructor(scope: Construct, id: string, props: RuntimeProps) {
    super(scope, id, { ...props, stackName: props.profile.stackName,
      env: { account: props.account, region: props.profile.region } });
    const definition = props.imageDefinition;
    const command = validateCommand(props.profile.command === undefined ? definition.command : props.profile.command);
    const { runtimeName } = props.profile;
    const { modelId } = props.profile.inference;

    const generated = ["**/node_modules", "**/cdk.out", "**/tests", "**/__pycache__", "**/*.pyc",
      "**/.env*", "**/*.connection.json", "**/cdk.context.json", "**/cdk-outputs*.json"];
    const directory = props.profile.image;
    const imagePath = path.relative(REPOSITORY_ROOT, IMAGE_DIRECTORY);
    // The image reference is the only source for its adapter directory.
    const exclude = ["**", "!.dockerignore", "!LICENSE", "!NOTICE", "!src", "src/*",
      "!src/agentcore_runtime", "src/agentcore_runtime/*", `!${imagePath}`, `${imagePath}/*`,
      `!${imagePath}/common`, `!${imagePath}/common/**`,
      `!${imagePath}/${directory}`, `!${imagePath}/${directory}/**`, ...generated];
    const image = new assets.DockerImageAsset(this, "AssistantImage", {
      directory: REPOSITORY_ROOT,
      file: path.join(imagePath, definition.file),
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
    let profileDirectory: string | undefined;
    if (props.profile.s3Files) {
      const infrastructure = props.infrastructure;
      if (!infrastructure) throw new Error("S3 Files requires managed infrastructure bindings");
      if (infrastructure.region !== this.region || infrastructure.account !== this.account) {
        throw new Error("Infrastructure must match the effective deployment account and region");
      }
      if (props.profile.vpc) throw new Error("S3 Files network settings come from the external network bindings");
      if (!directoryPath(`/${props.profileName}`, 1)) throw new Error("Invalid profile access-point root directory");
      const rootDirectory = `/agent-filesystem/profiles/${props.profileName}`;
      profileDirectory = props.profile.s3Files.mountPath;
      const accessPoint = new s3files.CfnAccessPoint(this, "WorkspaceAccessPoint", {
        fileSystemId: infrastructure.fileSystemId,
        posixUser: { uid: WORKSPACE_POSIX.uid, gid: WORKSPACE_POSIX.gid },
        rootDirectory: { path: rootDirectory, creationPermissions: {
          ownerUid: WORKSPACE_POSIX.uid, ownerGid: WORKSPACE_POSIX.gid,
          permissions: WORKSPACE_POSIX.permissions,
        } },
      });
      const accessPointArn = accessPoint.attrAccessPointArn;
      new CfnOutput(this, "WorkspaceRootDirectory", { value: rootDirectory });
      const fileSystemArn = infrastructure.fileSystemArn;
      network = { networkMode: "VPC", networkModeConfig: {
        subnets: infrastructure.subnetIds, securityGroups: infrastructure.securityGroupIds,
      } };
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
      new CfnOutput(this, "WorkspaceAccessPointArn", { value: accessPointArn });
      new CfnOutput(this, "ProfileWorkingDirectory", { value: profileDirectory });
    }
    const workingDirectory = props.profile.workingDirectory ?? profileDirectory;
    if (profileDirectory && workingDirectory) {
      const relative = path.posix.relative(profileDirectory, workingDirectory);
      if (relative === ".." || relative.startsWith("../") || path.posix.isAbsolute(relative)) {
        throw new Error("S3 workingDirectory must be inside this profile's access-point mount");
      }
    }
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
        ...(profileDirectory ? { AGENTCORE_PROFILE_DIRECTORY: profileDirectory } : {}),
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
        runtime_arn: runtime.attrAgentRuntimeArn, command,
      })),
    });
  }
}
