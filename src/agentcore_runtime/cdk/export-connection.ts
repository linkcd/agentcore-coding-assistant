/** Export a validated connection descriptor from a selected CDK output. */
import * as fs from "node:fs";
import * as path from "node:path";
import { parseArgs } from "node:util";
import Ajv2020 from "ajv/dist/2020";
import { CONTRACT_VERSION, connectionDescriptor } from "./connection";

const schema = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../contracts", CONTRACT_VERSION, "connection.schema.json"), "utf8"));
const validate = new Ajv2020({ strict: false }).compile<ReturnType<typeof connectionDescriptor>>(schema);

export function descriptorFromOutputs(outputs: unknown, stack?: string) {
  if (!outputs || typeof outputs !== "object" || Array.isArray(outputs)) throw new Error("Invalid CDK outputs");
  const stacks = Object.keys(outputs);
  if (!stack && stacks.length !== 1) throw new Error("Select one stack explicitly");
  const selected = (outputs as Record<string, any>)[stack ?? stacks[0]];
  if (typeof selected?.ConnectionDescriptor !== "string") throw new Error("Missing ConnectionDescriptor output");
  const document = JSON.parse(selected.ConnectionDescriptor);
  if (!validate(document)) throw new Error("Invalid resolved connection descriptor");
  return { ...connectionDescriptor(document.connection), version: document.version };
}

if (require.main === module) {
  try {
    const { values } = parseArgs({ options: {
      "cdk-outputs": { type: "string" }, stack: { type: "string" }, output: { type: "string" },
    } });
    if (!values["cdk-outputs"] || !values.output) throw new Error("Required arguments are missing");
    const descriptor = descriptorFromOutputs(JSON.parse(fs.readFileSync(values["cdk-outputs"], "utf8")), values.stack);
    fs.mkdirSync(path.dirname(path.resolve(values.output)), { recursive: true });
    fs.writeFileSync(values.output, JSON.stringify(descriptor, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    console.log(`Wrote minimal connection descriptor: ${values.output}`);
  } catch {
    console.error("Connection export failed. Check the input, stack selection, and unused output path.");
    process.exitCode = 1;
  }
}
