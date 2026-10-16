import { createReporter } from "./activity.mjs";

// Public OpenCode 1.18.30 event and disposal hooks. Each project instance gets
// a separate lease; /ping aggregates them across all OpenCode processes.
export default async function AgentCoreActivity() {
  const reporter = createReporter();
  return {
    event: async ({ event }) => reporter.event(event),
    dispose: async () => reporter.dispose(),
  };
}
