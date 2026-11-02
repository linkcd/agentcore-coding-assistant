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

export function loadHostNetworkConfig(environment: Environment): HostNetworkConfig {
  return {
    vpcId: required(environment, "EC2_HOST_VPC_ID", "vpc"),
    subnetId: required(environment, "EC2_HOST_SUBNET_ID", "subnet"),
  };
}
