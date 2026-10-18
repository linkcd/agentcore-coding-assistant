// Local, metadata-only OpenCode activity leases. No prompts, tool arguments,
// credentials, or conversation contents are written to disk.
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const HEARTBEAT_MS = 10_000;
export const ACTIVITY_DIRECTORY = "/tmp/herdr-agentcore-activity";

export class ActivityTracker {
  sessions = new Map();

  state(sessionID) {
    if (!this.sessions.has(sessionID)) {
      this.sessions.set(sessionID, { active: false, waiting: new Map(), tools: new Map() });
    }
    return this.sessions.get(sessionID);
  }

  toolStarted({ sessionID, callID, tool }) {
    if (typeof sessionID !== "string" || !sessionID || typeof callID !== "string" || !callID) return false;
    const session = this.state(sessionID);
    const previous = session.tools.get(callID);
    session.tools.set(callID, { kind: tool ?? previous?.kind, child: previous?.child });
    return true;
  }

  toolFinished({ sessionID, callID }) {
    return this.sessions.get(sessionID)?.tools.delete(callID) ?? false;
  }

  handle(event) {
    const properties = event?.properties;
    const type = event?.type;
    if (typeof type !== "string") return false;
    if (type === "message.part.updated") {
      const part = properties?.part;
      if (part?.type !== "tool") return false;
      const input = { sessionID: part.sessionID, callID: part.callID, tool: part.tool };
      if (["completed", "error"].includes(part.state?.status)) return this.toolFinished(input);
      if (!["pending", "running"].includes(part.state?.status) || !this.toolStarted(input)) return false;
      const child = part.state?.metadata?.sessionId;
      if (part.tool === "task" && typeof child === "string" && child) {
        this.sessions.get(part.sessionID).tools.get(part.callID).child = child;
      }
      return true;
    }
    const sessionID = properties?.sessionID;
    if (typeof sessionID !== "string" || !sessionID) return false;
    if (type === "session.idle") return this.sessions.delete(sessionID);
    if (type === "session.error") {
      const session = this.sessions.get(sessionID);
      if (!session) return false;
      session.active = false;
      // A model error does not prove that concurrent tools have stopped.
      return true;
    }
    if (type === "session.status") {
      const status = properties.status?.type;
      if (status === "idle") return this.sessions.delete(sessionID);
      if (status !== "busy" && status !== "retry") return false;
      this.state(sessionID).active = true;
      return true;
    }
    const [kind, action] = type.split(".");
    if (kind !== "permission" && kind !== "question") return false;
    if (action === "asked" && typeof properties.id === "string") {
      const callID = properties.tool?.callID;
      this.state(sessionID).waiting.set(`${kind}:${properties.id}`,
        typeof callID === "string" && callID ? callID : null);
      return true;
    }
    if (action === "replied" || action === "rejected") {
      return this.sessions.get(sessionID)?.waiting.delete(`${kind}:${properties.requestID}`) ?? false;
    }
    return false;
  }

  get busy() {
    return [...this.sessions.keys()].some((id) => this.sessionBusy(id));
  }

  sessionBusy(id, ancestors = new Set()) {
    // Unknown child activity is conservative: a delegated task has started, but
    // this plugin instance cannot yet prove that it is idle. Cycles cannot recurse.
    if (ancestors.has(id)) return true;
    const session = this.sessions.get(id);
    if (!session) return true;
    const path = new Set([...ancestors, id]);
    const blocked = new Set(session.waiting.values());
    const unscopedQuestion = [...session.waiting.entries()].some(
      ([key, callID]) => key.startsWith("question:") && callID === null,
    );
    for (const [callID, tool] of session.tools) {
      if (blocked.has(callID)) continue;
      if (blocked.has(null) && session.tools.size === 1) continue;
      if (unscopedQuestion && tool.kind === "question") continue;
      if (tool.kind === "task" && tool.child) {
        if (this.sessionBusy(tool.child, path)) return true;
      } else {
        return true;
      }
    }
    if (session.tools.size) return false; // All known tools are waiting or delegated to idle children.
    return session.active && session.waiting.size === 0;
  }
}

function processIdentity() {
  // /proc stat field 22 is the process start tick. It distinguishes PID reuse.
  const stat = readFileSync(`/proc/${process.pid}/stat`, "utf8");
  const start = stat.slice(stat.lastIndexOf(")") + 2).split(/\s+/)[19];
  if (!/^\d+$/.test(start)) throw new Error("Missing process start identity");
  return { pid: process.pid, process_start: start };
}

export function createReporter({
  directory = process.env.HERDR_ACTIVITY_DIR || ACTIVITY_DIRECTORY,
  identity = processIdentity(),
  now = Date.now,
  interval = HEARTBEAT_MS,
} = {}) {
  const tracker = new ActivityTracker();
  const path = join(directory, `${identity.pid}-${randomUUID()}.json`);
  const temporary = `${path}.tmp`;
  let timer;
  let disposed = false;
  let reportedError = false;

  function write() {
    try {
      if (disposed || !tracker.busy) {
        rmSync(path, { force: true });
        rmSync(temporary, { force: true });
      } else {
        mkdirSync(directory, { recursive: true, mode: 0o700 });
        writeFileSync(temporary, JSON.stringify({
          version: 1,
          ...identity,
          busy: true,
          updated_at: now() / 1000,
        }), { mode: 0o600 });
        renameSync(temporary, path);
      }
      reportedError = false;
    } catch (error) {
      if (!reportedError) console.error(`Herdr activity reporting failed (${error.code ?? "unknown"})`);
      reportedError = true;
      // A failed write must not fail a user's model/tool request. The reader
      // rejects leases after 45 seconds without a successful heartbeat.
    }
  }

  function update(changed) {
    if (disposed || !changed) return;
    write();
    if (tracker.busy && !timer) {
      timer = setInterval(write, interval);
      timer.unref();
    } else if (!tracker.busy && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  }

  return {
    event(event) { if (!disposed) update(tracker.handle(event)); },
    toolStarted(input) { if (!disposed) update(tracker.toolStarted(input)); },
    toolFinished(input) { if (!disposed) update(tracker.toolFinished(input)); },
    dispose() {
      disposed = true;
      clearInterval(timer);
      timer = undefined;
      write();
    },
  };
}
