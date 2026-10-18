import * as fs from "node:fs";
import * as path from "node:path";
import { validateCommand } from "../runtime_contract/connection";

export interface RuntimeProfile {
  stackName: string;
  runtimeName: string;
  image: { directory: string; file?: string; buildArgs?: Record<string, string> };
  command: string[];
  agentKind: string | null;
  inference: { api: "bedrock" | "mantle"; modelId: string; region?: string };
  environment: Record<string, string>;
}

export function loadProfile(name: string, directory = path.join(__dirname, "profiles")): RuntimeProfile {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(name)) throw new Error("Invalid assistant profile name");
  const data = JSON.parse(fs.readFileSync(path.join(directory, `${name}.json`), "utf8"));
  validateCommand(data.command);
  if (typeof data.stackName !== "string" || typeof data.runtimeName !== "string" ||
      typeof data.image?.directory !== "string" || typeof data.inference?.modelId !== "string" ||
      !["bedrock", "mantle"].includes(data.inference.api) ||
      (data.agentKind !== null && (typeof data.agentKind !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(data.agentKind)))) {
    throw new Error("Invalid runtime profile settings");
  }
  if (!data.environment || typeof data.environment !== "object" ||
      Object.values(data.environment).some((value) => typeof value !== "string")) {
    throw new Error("Profile environment must contain string settings");
  }
  return data as RuntimeProfile;
}
