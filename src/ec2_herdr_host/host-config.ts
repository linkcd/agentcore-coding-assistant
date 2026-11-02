import * as fs from "node:fs";
import * as path from "node:path";
import { parseEnv } from "node:util";

/** Existing-network bindings, read only from the component .env. */
export interface HostNetworkConfig {
  vpcId: string;
  subnetId: string;
}

type Environment = Record<string, string | undefined>;

const ENV_FILE = path.join(__dirname, ".env");

export function loadEnvironment(): Environment {
  return fs.existsSync(ENV_FILE) ? parseEnv(fs.readFileSync(ENV_FILE, "utf8")) : {};
}

function required(environment: Environment, key: string, prefix: string): string {
  const value = environment[key]?.trim();
  if (!value || value.startsWith("REPLACE_WITH_")) {
    throw new Error(`Missing deployment variable ${key}; fill src/ec2_herdr_host/.env`);
  }
  if (!new RegExp(`^${prefix}-(?:[0-9a-f]{8}|[0-9a-f]{17})$`).test(value)) {
    throw new Error(`${key} must be one existing ${prefix} ID`);
  }
  return value;
}

const RUNTIME_ARN = /^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime\/[A-Za-z0-9_]+-[A-Za-z0-9]{10}$/;

/**
 * Optional AGENTCORE_RUNTIME_ARN: one or more AgentCore runtime ARNs, separated by commas.
 * The host role may open terminals only in these runtimes. Without it, the role may use every runtime in the account and Region.
 */
export function loadAgentCoreRuntimeArns(environment: Environment): string[] {
  const value = environment.AGENTCORE_RUNTIME_ARN?.trim();
  if (!value || value.startsWith("REPLACE_WITH_")) return [];
  const arns = value.split(",").map((arn) => arn.trim());
  for (const arn of arns) {
    if (!RUNTIME_ARN.test(arn)) throw new Error("AGENTCORE_RUNTIME_ARN must list AgentCore runtime ARNs, not endpoint ARNs");
  }
  return [...new Set(arns)];
}

export function loadHostNetworkConfig(environment: Environment): HostNetworkConfig {
  return {
    vpcId: required(environment, "EC2_HOST_VPC_ID", "vpc"),
    subnetId: required(environment, "EC2_HOST_SUBNET_ID", "subnet"),
  };
}
