/** Pure deployment-side connection data. No AWS or filesystem dependencies. */
export interface ConnectionFields {
  runtime_arn: string;
  region: string;
  endpoint: string;
  command: readonly string[];
  agent_kind: string | null;
  runtime_profile: string;
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
  // CDK ARN/region tokens resolve during deployment. The consumer validates the
  // resolved ARN and region before it registers the connection.
  return {
    version: 1,
    transport: "agentcore-shell-v1",
    connection: { ...connection, command: validateCommand(connection.command) },
  };
}
