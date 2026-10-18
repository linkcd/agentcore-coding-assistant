import * as path from "node:path";
import { CfnOutput, Stack, StackProps, Tags, aws_bedrockagentcore as agentcore,
  aws_ecr_assets as assets, aws_iam as iam } from "aws-cdk-lib";
import { Construct } from "constructs";
import { connectionDescriptor, validateCommand } from "../runtime_contract/connection";
import { RuntimeProfile } from "./profile";

export interface RuntimeProps extends StackProps {
  profileName: string;
  profile: RuntimeProfile;
  runtimeName: string;
  modelId: string;
  inferenceRegion?: string;
  command?: unknown;
  retainedModelIds?: string[];
}

export class RuntimeStack extends Stack {
  constructor(scope: Construct, id: string, props: RuntimeProps) {
    super(scope, id, props);
    const command = validateCommand(props.command === undefined ? props.profile.command : props.command);
    if (!/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(props.runtimeName)) {
      throw new Error("runtimeName must use 1–48 letters, digits, or underscores and start with a letter");
    }
    if (!Array.isArray(props.retainedModelIds ?? [])) throw new Error("retainedModelIds must be an array");
    const modelIds = [props.modelId, ...(props.retainedModelIds ?? [])];
    if (modelIds.some((model) => typeof model !== "string" || !/^[A-Za-z0-9][A-Za-z0-9.:-]{0,199}$/.test(model) || model.startsWith("arn:"))) {
      throw new Error("Supply modelId and retainedModelIds as Bedrock model/system inference-profile IDs");
    }

    const generated = ["node_modules", "cdk.out", "tests", "**/__pycache__", "**/*.pyc"];
    let exclude = generated;
    if (props.profile.image.file === "common/Dockerfile") {
      const directory = props.profile.image.buildArgs?.ASSISTANT_DIR;
      if (!directory || !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(directory)) {
        throw new Error("The shared image requires a relative ASSISTANT_DIR");
      }
      const parts = directory.split("/");
      const parents = parts.map((_, index) => `!${parts.slice(0, index + 1).join("/")}`);
      // Stage only the shared implementation and selected adapter. Changes to
      // another assistant must not invalidate this profile's image asset.
      exclude = ["**", "!common", "!common/**", ...parents, `!${directory}/**`, ...generated];
    }
    const image = new assets.DockerImageAsset(this, "AssistantImage", {
      directory: path.resolve(__dirname, props.profile.image.directory),
      file: props.profile.image.file,
      platform: assets.Platform.LINUX_ARM64,
      buildArgs: props.profile.image.buildArgs,
      exclude,
    });
    const role = new iam.Role(this, "ExecutionRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
          ArnLike: { "aws:SourceArn": `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:runtime/${props.runtimeName}-*` },
        },
      }),
    });
    image.repository.grantPull(role);
    const inferenceRegion = props.inferenceRegion ?? this.region;
    if (props.profile.inference.api === "bedrock") {
      const resources = new Set<string>();
      for (const modelId of modelIds) {
        const base = modelId.replace(/^(us|eu|apac|global)\./, "");
        resources.add(`arn:${this.partition}:bedrock:*::foundation-model/${base}`);
        for (const prefix of ["", "us.", "eu.", "apac.", "global."]) {
          resources.add(`arn:${this.partition}:bedrock:*:${this.account}:inference-profile/${prefix}${base}`);
        }
      }
      role.addToPolicy(new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], resources: [...resources],
      }));
      role.addToPolicy(new iam.PolicyStatement({ actions: ["bedrock:ListInferenceProfiles"], resources: ["*"] }));
    } else {
      role.addToPolicy(new iam.PolicyStatement({
        actions: ["bedrock-mantle:CreateInference"],
        resources: [`arn:${this.partition}:bedrock-mantle:${inferenceRegion}:${this.account}:project/*`],
      }));
    }
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "logs:PutResourcePolicy"],
      resources: [`arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/${props.runtimeName}-*`],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:DescribeLogGroups"],
      resources: [`arn:${this.partition}:logs:${this.region}:${this.account}:log-group:*`],
    }));

    const runtime = new agentcore.CfnRuntime(this, "Runtime", {
      agentRuntimeName: props.runtimeName,
      agentRuntimeArtifact: { containerConfiguration: { containerUri: image.imageUri } },
      roleArn: role.roleArn,
      networkConfiguration: { networkMode: "PUBLIC" },
      protocolConfiguration: "HTTP",
      environmentVariables: Object.fromEntries(Object.entries(props.profile.environment).map(([key, value]) =>
        [key, value.replaceAll("$RUNTIME_REGION", this.region).replaceAll("$INFERENCE_REGION", inferenceRegion).replaceAll("$MODEL_ID", props.modelId)])),
      lifecycleConfiguration: { idleRuntimeSessionTimeout: 900, maxLifetime: 28800 },
    });
    runtime.node.addDependency(role);
    Tags.of(this).add("Project", "herdr-agentcore");
    Tags.of(this).add("AssistantProfile", props.profileName);

    new CfnOutput(this, "RuntimeArn", { value: runtime.attrAgentRuntimeArn });
    new CfnOutput(this, "RuntimeId", { value: runtime.attrAgentRuntimeId });
    new CfnOutput(this, "ConnectionDescriptor", {
      value: this.toJsonString(connectionDescriptor({
        runtime_arn: runtime.attrAgentRuntimeArn, region: this.region, endpoint: "DEFAULT",
        command, agent_kind: props.profile.agentKind, runtime_profile: props.profileName,
      })),
    });
  }
}
