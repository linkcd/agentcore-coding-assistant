import { App } from "aws-cdk-lib";
import { HerdrHostStack } from "./host-stack";
import { loadAgentCoreRuntimeArns, loadEnvironment, loadHostNetworkConfig } from "./host-config";

const app = new App();
// The Bedrock policy and OpenCode configuration target the eu.* inference profile in eu-west-1.
const region = "eu-west-1";
// Account identity is supplied by the authenticated CDK Toolkit, never copied into the repository.
const account = process.env.CDK_DEFAULT_ACCOUNT;
if (!account || !/^\d{12}$/.test(account)) {
  throw new Error("CDK_DEFAULT_ACCOUNT must be resolved. Run through the CDK CLI with AWS credentials.");
}
// CDK saves the VPC and AMI lookups in cdk.context.json. To change the network, run
// "cdk context", then "cdk context --reset <number>" for the vpc-provider entry only.
// Do not reset the ssm: entry on a host to keep: a new AMI replaces the instance and deletes its disk.
// The lookups need bootstrap version 8 or later of the CDK lookup role.
const environment = loadEnvironment();
const network = loadHostNetworkConfig(environment);
const agentCoreRuntimeArns = loadAgentCoreRuntimeArns(environment);
// Optional: -c volumeSizeGiB=<size>. A change on a host that exists replaces the instance and deletes its disk.
const volumeSizeGiB = app.node.tryGetContext("volumeSizeGiB");
new HerdrHostStack(app, "HerdrOpenCodeHost", {
  env: { account, region },
  description: "EC2 host for Herdr and OpenCode with Amazon Bedrock, reached through Session Manager",
  ...network,
  agentCoreRuntimeArns,
  volumeSizeGiB: volumeSizeGiB === undefined ? undefined : Number(volumeSizeGiB),
});
