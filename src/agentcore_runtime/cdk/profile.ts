import * as fs from "node:fs";
import * as path from "node:path";
import { parseEnv } from "node:util";
import { validateCommand } from "./connection";

/**
 * One named deployment definition, read from provision_profiles/<name>.json.
 * The entrypoint selects it with -c runtimeProfile=<name>. It rejects other per-field context.
 * It is a settings reference. A connector does not use it as an assistant type.
 */
export interface RuntimeProfile {
  /** Deployment names. The CDK Toolkit supplies the authenticated account. */
  stackName: string;
  runtimeName: string;
  /** AWS region of the deployment. */
  region: string;
  /** Idle timeout and maximum compute lifetime, in seconds. The platform enforces both. */
  lifecycle: { idleRuntimeSessionTimeout: number; maxLifetime: number };
  /** Explicit tags only. The stack adds no application tags. */
  tags?: Record<string, string>;
  /** External VPC bindings for a profile that has no managed S3 Files storage. */
  vpc?: { subnetIds: string[]; securityGroupIds: string[] };
  /** Directory name under agent_images/. The image definition holds the Dockerfile, build arguments, and command. */
  image: string;
  /** Explicit override of the image's launch argv. */
  command?: string[];
  inference: {
    /** Startup model identifier. */
    modelId: string;
    /** Inference region. The default is the deployment region. */
    region?: string;
    /** "runtime" or "mantle". When omitted, the model's native routing is used. */
    "bedrock-endpoint-type"?: "runtime" | "mantle";
  };
  /** Storage stack name, mount path, and read-only choice. See docs/STORAGE_MAPPING.md. */
  s3Files?: {
    storageStackName: string;
    mountPath: string;
    readOnly: boolean;
  };
  /** Absolute path. With S3 Files, it must stay inside the dedicated mount. */
  workingDirectory?: string;
  /** Extra string settings. A setting that the stack derives cannot be overridden here. */
  environment?: Record<string, string>;
}

export const RUNTIME_ROOT = path.resolve(__dirname, "..");
export const REPOSITORY_ROOT = path.resolve(RUNTIME_ROOT, "../..");
const PROFILE_DIRECTORY = path.join(RUNTIME_ROOT, "provision_profiles");
type Environment = Record<string, string | undefined>;

export function loadRuntimeEnvironment(): Environment {
  const file = path.join(RUNTIME_ROOT, ".env");
  return fs.existsSync(file) ? parseEnv(fs.readFileSync(file, "utf8")) : {};
}

function resolveValues(value: unknown, environment: Environment): any {
  if (typeof value === "string") {
    return value.replace(/\$\{([A-Z][A-Z0-9_]*)\}/g, (_, key: string) => {
      if (environment[key] === undefined) throw new Error(`Missing deployment variable ${key}; fill src/agentcore_runtime/.env`);
      return environment[key];
    });
  }
  if (Array.isArray(value)) return value.map((item) => resolveValues(item, environment));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, resolveValues(item, environment)]));
  }
  return value;
}

export function loadProfile(name: string, environment: Environment = {}): RuntimeProfile {
  if (typeof name !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(name)) throw new Error("Invalid provision profile name");
  return parseProfile(JSON.parse(fs.readFileSync(path.join(PROFILE_DIRECTORY, `${name}.json`), "utf8")), environment);
}

export function parseProfile(input: unknown, environment: Environment = {}): RuntimeProfile {
  const data = resolveValues(input, environment);
  const fields = new Set(["stackName", "runtimeName", "region", "vpc", "image",
    "command", "inference", "s3Files", "environment", "workingDirectory", "lifecycle", "tags"]);
  if (!data || typeof data !== "object" || Array.isArray(data) ||
      Object.keys(data).some((key) => !fields.has(key))) {
    throw new Error("Unknown or invalid provision profile fields");
  }
  if (data.command !== undefined) validateCommand(data.command);
  const seconds = (value: unknown) => typeof value === "number" && Number.isInteger(value) &&
    value >= 60 && value <= 1209600;
  if (!data.lifecycle || !seconds(data.lifecycle.idleRuntimeSessionTimeout) ||
      !seconds(data.lifecycle.maxLifetime) ||
      data.lifecycle.idleRuntimeSessionTimeout > data.lifecycle.maxLifetime ||
      Object.keys(data.lifecycle).some((key) => !["idleRuntimeSessionTimeout", "maxLifetime"].includes(key))) {
    throw new Error("Invalid lifecycle seconds; use 60-1209600 and idle timeout no greater than max lifetime");
  }
  if (data.tags !== undefined && (!data.tags || typeof data.tags !== "object" || Array.isArray(data.tags) ||
       Object.values(data.tags).some((value) => typeof value !== "string"))) {
    throw new Error("Profile tags must contain string settings");
  }
  if (typeof data.stackName !== "string" || !/^[A-Za-z][A-Za-z0-9-]{0,127}$/.test(data.stackName) ||
      typeof data.runtimeName !== "string" || !/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(data.runtimeName) ||
      typeof data.region !== "string" || !/^[a-z]{2}(?:-[a-z]+)+-\d+$/.test(data.region) ||
      typeof data.image !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(data.image) ||
      typeof data.inference?.modelId !== "string" ||
      Object.keys(data.inference).some((key) => !["bedrock-endpoint-type", "modelId", "region"].includes(key)) ||
      !/^[A-Za-z0-9][A-Za-z0-9.:-]{0,199}$/.test(data.inference.modelId) || data.inference.modelId.startsWith("arn:")) {
    throw new Error("Invalid runtime profile settings");
  }
  if (data.inference["bedrock-endpoint-type"] !== undefined &&
      !["runtime", "mantle"].includes(data.inference["bedrock-endpoint-type"])) {
    throw new Error('inference.bedrock-endpoint-type must be "runtime" or "mantle"');
  }
  if (data.inference.region !== undefined &&
      (typeof data.inference.region !== "string" || !/^[a-z]{2}(?:-[a-z]+)+-\d+$/.test(data.inference.region))) {
    throw new Error("Invalid inference region");
  }
  if (data.vpc !== undefined) {
    if (data.vpc && typeof data.vpc === "object") {
      for (const key of ["subnetIds", "securityGroupIds"]) {
        if (typeof data.vpc[key] === "string") data.vpc[key] = data.vpc[key].split(",").map((id: string) => id.trim());
      }
    }
    const validIds = (value: unknown, prefix: string) =>
      Array.isArray(value) && value.length > 0 && value.every((id) => typeof id === "string" &&
        new RegExp(`^${prefix}-(?:[0-9a-f]{8}|[0-9a-f]{17})$`).test(id));
    if (!data.vpc ||
        Object.keys(data.vpc).some((key) => !["subnetIds", "securityGroupIds"].includes(key)) ||
        !validIds(data.vpc.subnetIds, "subnet") || !validIds(data.vpc.securityGroupIds, "sg")) {
      throw new Error("vpc must contain resolved subnetIds and securityGroupIds lists");
    }
  }
  if (data.s3Files !== undefined &&
      (!data.s3Files || data.vpc !== undefined || typeof data.s3Files.mountPath !== "string" ||
       !/^\/mnt\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(data.s3Files.mountPath ?? "") ||
       data.s3Files.mountPath.length > 200 || typeof data.s3Files.readOnly !== "boolean" ||
        Object.keys(data.s3Files).some((key) => !["storageStackName", "mountPath", "readOnly"].includes(key)))) {
    throw new Error("S3 Files requires valid mount settings and external network bindings from .env");
  }
  if (data.s3Files) {
    const storage = data.s3Files;
    if (typeof storage.storageStackName !== "string" ||
        !/^[A-Za-z][A-Za-z0-9-]{0,127}$/.test(storage.storageStackName) || storage.storageStackName === data.stackName) {
      throw new Error("Invalid s3Files.storageStackName");
    }
  }
  const derivedEnvironment = new Set(["AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE", "BEDROCK_MODEL_ID", "BEDROCK_INFERENCE_REGION", "BEDROCK_ENDPOINT_TYPE",
    "AGENTCORE_WORKDIR", "AGENTCORE_PROFILE_DIRECTORY", "AGENTCORE_REQUIRED_MOUNT", "OPENCODE_WORKDIR", "CODEX_WORKDIR"]);
  if (data.environment !== undefined && (!data.environment || typeof data.environment !== "object" || Array.isArray(data.environment) ||
      Object.entries(data.environment).some(([key, value]) => typeof value !== "string" || derivedEnvironment.has(key)))) {
    throw new Error("Environment overrides must be strings and must not duplicate derived runtime settings");
  }
  if (data.workingDirectory !== undefined && (typeof data.workingDirectory !== "string" ||
      !path.posix.isAbsolute(data.workingDirectory) || /[\x00-\x1f\x7f]/.test(data.workingDirectory))) {
    throw new Error("workingDirectory must be an absolute container path without control characters");
  }
  return data as RuntimeProfile;
}
