// Local, metadata-only OpenCode activity leases. No prompts, tool arguments,
// credentials, or conversation contents are written to disk.
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const HEARTBEAT_MS = 10_000;
export const ACTIVITY_DIRECTORY = "/tmp/herdr-agentcore-activity";

export class ActivityTracker {
  sessions = new Map();

  handle(event) {
    const properties = event?.properties;
    const sessionID = properties?.sessionID;
    if (typeof sessionID !== "string" || !sessionID) return false;
    const type = event.type;
    if (typeof type !== "string") return false;
    if (type === "session.idle" || type === "session.error") {
      return this.sessions.delete(sessionID);
    }
    if (type === "session.status") {
      const status = properties.status?.type;
      if (status === "idle") return this.sessions.delete(sessionID);
      if (status !== "busy" && status !== "retry") return false;
      const session = this.sessions.get(sessionID) ?? { active: false, waiting: new Set() };
      session.active = true;
      this.sessions.set(sessionID, session);
      return true;
    }
    const [kind, action] = type.split(".");
    if (kind !== "permission" && kind !== "question") return false;
    if (action === "asked" && typeof properties.id === "string") {
      const session = this.sessions.get(sessionID) ?? { active: false, waiting: new Set() };
      session.waiting.add(`${kind}:${properties.id}`);
      this.sessions.set(sessionID, session);
      return true;
    }
    if (action === "replied" || action === "rejected") {
      return this.sessions.get(sessionID)?.waiting.delete(`${kind}:${properties.requestID}`) ?? false;
    }
    return false;
  }

  get busy() {
    return [...this.sessions.values()].some((session) => session.active && session.waiting.size === 0);
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

  return {
    event(event) {
      if (disposed || !tracker.handle(event)) return;
      write();
      if (tracker.busy && !timer) {
        timer = setInterval(write, interval);
        timer.unref();
      } else if (!tracker.busy && timer) {
        clearInterval(timer);
        timer = undefined;
      }
    },
    dispose() {
      disposed = true;
      clearInterval(timer);
      timer = undefined;
      write();
    },
  };
}
