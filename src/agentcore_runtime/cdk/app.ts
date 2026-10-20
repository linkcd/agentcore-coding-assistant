import { App } from "aws-cdk-lib";
import { RuntimeStack } from "./runtime-stack";
import { loadProfile, loadRuntimeEnvironment } from "./profile";
import { loadImage } from "./image";
import { loadInfrastructureConfig } from "./infrastructure-config";
import { InfrastructureStack } from "./infrastructure-stack";

const app = new App();
const profileName = app.node.tryGetContext("runtimeProfile");
if (!profileName) throw new Error("Select a named configuration with -c runtimeProfile=<name>");
for (const key of ["stackName", "runtimeName", "region", "modelId", "inferenceRegion", "command", "profileDirectory", "retainedModelIds"]) {
  if (app.node.tryGetContext(key) !== undefined) {
    throw new Error(`Context ${key} is not supported. Edit the repo provision profile or agentcore_runtime/.env.`);
  }
}
const environment = loadRuntimeEnvironment();
const profile = loadProfile(profileName, environment);
const imageDefinition = loadImage(profile.image);
// Account identity is supplied by the authenticated CDK Toolkit, not copied into profiles.
const account = process.env.CDK_DEFAULT_ACCOUNT;
if (!account || !/^\d{12}$/.test(account)) {
  throw new Error("CDK_DEFAULT_ACCOUNT must be resolved. Run through the CDK CLI with AWS credentials.");
}

const infrastructure = profile.s3Files?.storageStackName
  ? new InfrastructureStack(app, "CodingAgentsInfrastructure", {
    account, region: profile.region, stackName: profile.s3Files.storageStackName,
    config: loadInfrastructureConfig(environment),
  }) : undefined;
const runtime = new RuntimeStack(app, profile.stackName, {
  account,
  profileName,
  profile,
  imageDefinition,
  infrastructure: infrastructure?.runtimeInfrastructure,
});
if (infrastructure) runtime.addStackDependency(infrastructure);
