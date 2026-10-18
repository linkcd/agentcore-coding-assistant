import { App } from "aws-cdk-lib";
import { RuntimeStack } from "./runtime-stack";
import { loadProfile } from "./profile";

const app = new App();
const commandContext = app.node.tryGetContext("command");
const retainedContext = app.node.tryGetContext("retainedModelIds");
const profileName = app.node.tryGetContext("runtimeProfile");
if (!profileName) throw new Error("Select a named configuration with -c runtimeProfile=<name>");
const profile = loadProfile(profileName);

new RuntimeStack(app, app.node.tryGetContext("stackName") ?? profile.stackName, {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: app.node.tryGetContext("region") ?? process.env.CDK_DEFAULT_REGION,
  },
  profileName,
  profile,
  runtimeName: app.node.tryGetContext("runtimeName") ?? profile.runtimeName,
  modelId: app.node.tryGetContext("modelId") ?? profile.inference.modelId,
  inferenceRegion: app.node.tryGetContext("inferenceRegion") ?? profile.inference.region,
  command: commandContext === undefined ? undefined : JSON.parse(commandContext),
  retainedModelIds: retainedContext === undefined ? [] : JSON.parse(retainedContext),
});
