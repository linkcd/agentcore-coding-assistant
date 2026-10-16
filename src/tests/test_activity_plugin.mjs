import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import test from "node:test";
import { ActivityTracker, createReporter } from "../herdr_agentcore/runtime_image/activity.mjs";

const status = (sessionID, type) => ({ type: "session.status", properties: { sessionID, status: { type } } });
const event = (type, sessionID, extra = {}) => ({ type, properties: { sessionID, ...extra } });

test("an open process is idle; generation and retries are work; completion is idle", () => {
  const tracker = new ActivityTracker();
  assert.equal(tracker.busy, false);
  tracker.handle(status("chat", "busy"));
  assert.equal(tracker.busy, true);
  tracker.handle(status("chat", "retry"));
  assert.equal(tracker.busy, true);
  tracker.handle(status("chat", "idle"));
  assert.equal(tracker.busy, false);
});

for (const kind of ["question", "permission"]) {
  test(`${kind} wait is idle until all outstanding requests are answered`, () => {
    const tracker = new ActivityTracker();
    tracker.handle(status("chat", "busy"));
    tracker.handle(event(`${kind}.asked`, "chat", { id: "one" }));
    assert.equal(tracker.busy, false);
    tracker.handle(status("chat", "busy")); // A repeated busy event is not a reply.
    tracker.handle(event(`${kind}.asked`, "chat", { id: "two" }));
    tracker.handle(event(`${kind}.replied`, "chat", { requestID: "one" }));
    assert.equal(tracker.busy, false);
    tracker.handle(event(`${kind}.replied`, "chat", { requestID: "two" }));
    assert.equal(tracker.busy, true);
    tracker.handle(status("chat", "idle"));
    assert.equal(tracker.busy, false);
    tracker.handle(event(`${kind}.replied`, "chat", { requestID: "two" }));
    assert.equal(tracker.busy, false); // Late replies cannot revive a finished turn.
  });
}

test("independent active sessions keep the runtime busy while another awaits input", () => {
  const tracker = new ActivityTracker();
  tracker.handle(status("first", "busy"));
  tracker.handle(status("second", "busy"));
  tracker.handle(event("question.asked", "first", { id: "answer-me" }));
  assert.equal(tracker.busy, true);
  tracker.handle(event("session.error", "second"));
  assert.equal(tracker.busy, false);
  tracker.handle(event("question.rejected", "first", { requestID: "answer-me" }));
  assert.equal(tracker.busy, true);
  tracker.handle(event("session.idle", "first"));
  assert.equal(tracker.busy, false);
});

test("malformed, unrelated, and unscoped error events do not change work state", () => {
  const tracker = new ActivityTracker();
  tracker.handle(status("chat", "busy"));
  for (const input of [null, {}, event(undefined, "chat"), event("other.event", "chat"),
    status("chat", "unknown"), { type: "session.error", properties: {} }]) {
    assert.equal(tracker.handle(input), false);
    assert.equal(tracker.busy, true);
  }
});

function reporter(t, options = {}) {
  const directory = mkdtempSync(join(tmpdir(), "herdr-activity-test-"));
  const value = createReporter({ directory, identity: { pid: 42, process_start: "123" }, ...options });
  t.after(() => { value.dispose(); rmSync(directory, { recursive: true, force: true }); });
  return {
    ...value,
    records: () => readdirSync(directory).filter((name) => name.endsWith(".json"))
      .map((name) => JSON.parse(readFileSync(join(directory, name), "utf8"))),
  };
}

test("16 minutes of work then a user-input wait starts idle at minute 16, not at startup", (t) => {
  let now = 0;
  const value = reporter(t, { now: () => now });
  assert.deepEqual(value.records(), []);
  value.event(status("chat", "busy"));
  assert.equal(value.records()[0].busy, true);
  now = 16 * 60 * 1000;
  value.event(event("question.asked", "chat", { id: "waiting" }));
  assert.deepEqual(value.records(), []);
  now = 31 * 60 * 1000;
  assert.deepEqual(value.records(), []); // No heartbeat manufactures activity while waiting.
});

test("work-only heartbeats contain process metadata, not session or prompt contents", async (t) => {
  let now = 1000;
  const value = reporter(t, { now: () => now, interval: 10 });
  value.event(status("private-chat-id", "busy"));
  now = 2000;
  await sleep(35);
  assert.deepEqual(value.records(), [{
    version: 1, pid: 42, process_start: "123", busy: true, updated_at: 2,
  }]);
  value.event(status("private-chat-id", "idle"));
  await sleep(35);
  assert.deepEqual(value.records(), []);
});

test("dispose removes busy state and late events cannot renew it", (t) => {
  const value = reporter(t);
  value.event(status("chat", "busy"));
  assert.equal(value.records().length, 1);
  value.dispose();
  value.event(status("chat", "busy"));
  assert.deepEqual(value.records(), []);
});
