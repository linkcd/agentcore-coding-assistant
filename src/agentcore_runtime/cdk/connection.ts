/** Runtime-owned JSON producer. Its data format is pinned under contracts/<CONTRACT_VERSION>. */
export const CONTRACT_VERSION = "1.0.0";

export interface ConnectionFields {
  runtime_arn: string;
  command: readonly string[];
  endpoint?: string;
}

export function validateCommand(value: unknown): string[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 64) {
    throw new Error("command is required and must contain 1–64 arguments");
  }
  for (const argument of value) {
    if (typeof argument !== "string" || !argument || Array.from(argument).length > 4096 ||
        /[\u0000-\u001f\u007f-\u009f]/.test(argument)) {
      throw new Error("command arguments must be nonempty text without control characters");
    }
  }
  if (value[0].startsWith("-") || value.reduce((size, argument) => size + Buffer.byteLength(argument) + 1, 0) > 8192) {
    throw new Error("Invalid command executable or command exceeds 8 KiB");
  }
  return [...value];
}

export function connectionDescriptor(connection: ConnectionFields) {
  // ARN tokens resolve during deployment. The consumer derives the region.
  const fields: ConnectionFields = {
    runtime_arn: connection.runtime_arn,
    command: validateCommand(connection.command),
  };
  if (connection.endpoint !== undefined && connection.endpoint !== "DEFAULT") {
    if (typeof connection.endpoint !== "string" || !connection.endpoint ||
        Array.from(connection.endpoint).length > 4096 || /[\u0000-\u001f\u007f-\u009f]/.test(connection.endpoint)) {
      throw new Error("Invalid connection endpoint");
    }
    fields.endpoint = connection.endpoint;
  }
  return { version: CONTRACT_VERSION, transport: "agentcore-shell-v1", connection: fields };
}
