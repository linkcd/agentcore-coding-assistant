import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as path from "node:path";
import { createHash } from "node:crypto";
import Ajv2020 from "ajv/dist/2020";
import { CONTRACT_VERSION, connectionDescriptor, validateCommand } from "../connection";
import { descriptorFromOutputs } from "../export-connection";

const directory = path.resolve(__dirname, "../../../../contracts", CONTRACT_VERSION);
const read = (name: string) => JSON.parse(fs.readFileSync(path.join(directory, name), "utf8"));
const cases = read("fixtures.json");
const validate = new Ajv2020({ strict: false }).compile(read("connection.schema.json"));

test("TypeScript compilation includes only project-local source paths", () => {
  const project = path.resolve(__dirname, "..");
  const config = JSON.parse(fs.readFileSync(path.join(project, "tsconfig.json"), "utf8"));
  for (const pattern of config.include) {
    const relative = path.relative(project, path.resolve(project, pattern));
    assert.ok(!relative.startsWith("..") && !path.isAbsolute(relative));
  }
});

test("contract files match their pinned upstream checksums", () => {
  assert.equal(read("upstream.json").descriptor_version, CONTRACT_VERSION);
  assert.equal(read("upstream.json").source_path, `contracts/${CONTRACT_VERSION}`);
  assert.equal(read("connection.schema.json").properties.version.default, CONTRACT_VERSION);
  assert.equal(read("connection.schema.json").$id, `urn:herdr-agentcore:connection:${CONTRACT_VERSION}`);
  assert.deepEqual(Object.keys(read("upstream.json").sha256).sort(), ["connection.schema.json", "fixtures.json"]);
  for (const [name, expected] of Object.entries(read("upstream.json").sha256)) {
    assert.equal(createHash("sha256").update(fs.readFileSync(path.join(directory, name))).digest("hex"), expected);
  }
});

for (const item of cases.valid) {
  test(`producer conforms to contract case: ${item.name}`, () => {
    assert.ok(validate(item.descriptor), JSON.stringify(validate.errors));
    const produced = connectionDescriptor(item.descriptor.connection);
    assert.ok(validate(produced), JSON.stringify(validate.errors));
    const expected = structuredClone(item.descriptor);
    if (expected.connection.endpoint === "DEFAULT") delete expected.connection.endpoint;
    assert.deepEqual(produced, { ...expected, version: CONTRACT_VERSION });
    assert.deepEqual(descriptorFromOutputs({ Stack: {
      ConnectionDescriptor: JSON.stringify(item.descriptor),
    } }), expected);
  });
}

for (const item of cases.invalid) {
  test(`schema rejects contract case: ${item.name}`, () => {
    assert.equal(validate(item.descriptor), false);
    assert.throws(() => descriptorFromOutputs({ Stack: {
      ConnectionDescriptor: JSON.stringify(item.descriptor),
    } }));
  });
}

test("command validation enforces UTF-8 size, argument count, and executable limits", () => {
  assert.doesNotThrow(() => validateCommand(["a", "é".repeat(4094)]));
  assert.throws(() => validateCommand(["a", "é".repeat(4095)]), /8 KiB/);
  assert.doesNotThrow(() => validateCommand(["a".repeat(4095), "b".repeat(4095)]));
  for (const argv of [["--flag"], ["a", ""], Array(65).fill("a"), ["a".repeat(4097)]]) {
    assert.throws(() => validateCommand(argv));
  }
});

test("export selects one stack and leaves the source document unchanged", () => {
  const original = structuredClone(cases.valid[0].descriptor);
  const outputs = { Selected: { ConnectionDescriptor: JSON.stringify(original) } };
  const before = structuredClone(outputs);
  assert.deepEqual(descriptorFromOutputs(outputs), cases.valid[0].descriptor);
  assert.deepEqual(outputs, before);
  const multiple = { ...outputs, Other: { RuntimeArn: "unrelated" } };
  assert.throws(() => descriptorFromOutputs(multiple), /Select one stack/);
  assert.deepEqual(descriptorFromOutputs(multiple, "Selected"), cases.valid[0].descriptor);
  assert.throws(() => descriptorFromOutputs(outputs, "Missing"));
  assert.throws(() => descriptorFromOutputs({ Stack: { ConnectionDescriptor: "{}" } }));
});

test("export enforces the aggregate command limit", () => {
  const document = structuredClone(cases.valid[0].descriptor);
  document.connection.command = ["a", "é".repeat(4095)];
  assert.ok(validate(document));
  assert.throws(() => descriptorFromOutputs({ Stack: {
    ConnectionDescriptor: JSON.stringify(document),
  } }), /8 KiB/);
});
