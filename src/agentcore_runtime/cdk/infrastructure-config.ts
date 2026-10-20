/** Storage and existing-network bindings resolved only from the component .env. */
export interface NetworkConfig {
  subnetIds: string[];
  securityGroupIds: string[];
}

export interface InfrastructureConfig extends NetworkConfig {
  bucketName: string;
}

type Environment = Record<string, string | undefined>;

export function directoryPath(value: string, maximumDepth = 4): boolean {
  const parts = value.split("/").slice(1);
  return value.startsWith("/") && parts.length > 0 && parts.length <= maximumDepth &&
    parts.every((part) => /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(part) && part !== "." && part !== "..");
}

function required(environment: Environment, key: string): string {
  const value = environment[key]?.trim();
  if (!value || value.startsWith("REPLACE_WITH_")) {
    throw new Error(`Missing deployment variable ${key}; fill src/agentcore_runtime/.env`);
  }
  return value;
}

export function loadNetworkConfig(environment: Environment): NetworkConfig {
  const csv = (key: string) => required(environment, key).split(",").map((value) => value.trim());
  const config = { subnetIds: csv("VPC_SUBNET_IDS"), securityGroupIds: csv("VPC_SECURITY_GROUP_IDS") };
  for (const [ids, prefix] of [[config.subnetIds, "subnet"], [config.securityGroupIds, "sg"]] as const) {
    if (ids.length === 0 || new Set(ids).size !== ids.length ||
        ids.some((id) => !new RegExp(`^${prefix}-(?:[0-9a-f]{8}|[0-9a-f]{17})$`).test(id))) {
      throw new Error("Supply distinct existing subnet and security-group IDs");
    }
  }
  return config;
}

export function loadInfrastructureConfig(environment: Environment): InfrastructureConfig {
  for (const key of ["S3_FILES_PREFIX", "S3_FILES_PROFILE_ROOT_DIRECTORY"]) {
    if (environment[key]?.trim()) throw new Error(`Remove ${key}; access-point and profile roots are derived from the profile name`);
  }
  const config: InfrastructureConfig = {
    bucketName: required(environment, "S3_BUCKET_NAME"),
    ...loadNetworkConfig(environment),
  };
  if (!/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(config.bucketName) ||
      config.bucketName.includes("..") || /^\d+\.\d+\.\d+\.\d+$/.test(config.bucketName)) {
    throw new Error("Invalid S3 bucket name");
  }
  return config;
}
