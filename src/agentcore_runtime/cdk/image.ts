import * as fs from "node:fs";
import * as path from "node:path";
import { validateCommand } from "../../runtime_contract/connection";

export const IMAGE_DIRECTORY = path.resolve(__dirname, "../agent_images");

export interface AgentImage {
  file: string;
  buildArgs: Record<string, string>;
  command: string[];
  agentKind: string | null;
}

export function loadImage(name: string): AgentImage {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(name)) throw new Error("Invalid agent image reference");
  const data = JSON.parse(fs.readFileSync(path.join(IMAGE_DIRECTORY, name, "image.json"), "utf8"));
  if (!data || typeof data !== "object" || Array.isArray(data) ||
      Object.keys(data).some((key) => !["file", "buildArgs", "command", "agentKind"].includes(key)) ||
      typeof data.file !== "string" || data.file.split("/").includes("..") ||
      !(data.file.startsWith("common/") || data.file.startsWith(`${name}/`)) ||
      !data.buildArgs || typeof data.buildArgs !== "object" || Array.isArray(data.buildArgs) ||
      Object.entries(data.buildArgs).some(([key, value]) => key === "ASSISTANT_DIR" ||
        !/^[A-Z][A-Z0-9_]*$/.test(key) || typeof value !== "string" || !value) ||
      (data.agentKind !== null && (typeof data.agentKind !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(data.agentKind)))) {
    throw new Error("Invalid agent image definition");
  }
  if (data.file === "common/Dockerfile" &&
      ["NPM_PACKAGE", "NPM_VERSION", "EXECUTABLE"].some((key) => !data.buildArgs[key])) {
    throw new Error("The shared Dockerfile requires package, version, and executable build arguments");
  }
  validateCommand(data.command);
  return data as AgentImage;
}
