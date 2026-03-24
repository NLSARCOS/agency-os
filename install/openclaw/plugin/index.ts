/**
 * Agency OS Plugin for OpenClaw
 *
 * Registers native tools so OpenClaw can:
 * - orchestrate: send tasks to Agency OS (async, non-blocking)
 * - mission_feedback: review deliverables and send back for revision
 * - mission_status: check mission status and artifacts
 * - missions_active: list all queued/running missions
 *
 * This is PROGRAMMATIC integration — not markdown instructions.
 * Tools appear in OpenClaw's tool palette automatically.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk/llm-task";

const AGENCY_API = process.env.AGENCY_API_URL || "http://localhost:8080";

// ── Helper: Call Agency OS API ──────────────────────────────

async function agencyFetch(path: string, options?: RequestInit) {
  const url = `${AGENCY_API}${path}`;
  try {
    const resp = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      },
      signal: AbortSignal.timeout(300000), // 5 minutes timeout for synchronous execution
    });
    return await resp.json();
  } catch (err: any) {
    return { error: `Agency OS unreachable at ${url}: ${err.message}` };
  }
}

// ── Tool Definitions ────────────────────────────────────────

const orchestrateTool = {
  name: "agency_orchestrate",
  description:
    "Send a task/objective to Agency OS for autonomous execution. " +
    "This tool executes synchronously and might take up to 5 minutes to complete. " +
    "Do not panic if it takes a while! When it returns, it will contain the final result. " +
    "Use this for ANY business objective: build apps, find leads, run campaigns, etc.",
  parameters: {
    type: "object" as const,
    properties: {
      prompt: {
        type: "string",
        description: "The task or objective to execute",
      },
      priority: {
        type: "number",
        description: "Priority 1-10 (default 5, higher = more urgent)",
        default: 5,
      },
    },
    required: ["prompt"],
  },
  async execute(args: { prompt: string; priority?: number }) {
    return await agencyFetch("/api/orchestrate?sync=true", {
      method: "POST",
      body: JSON.stringify({
        prompt: args.prompt,
        priority: args.priority || 5,
        sync: true
      }),
    });
  },
};

const missionFeedbackTool = {
  name: "agency_mission_feedback",
  description:
    "Review a completed mission's deliverable. " +
    "Use 'revise' if the output is incomplete or has issues — " +
    "this sends it back to the agent for improvement with your feedback. " +
    "Use 'approve' if the output is good. " +
    "IMPORTANT: Always review mission results before presenting to user. " +
    "If you send a revision, tell the user you sent it back for completion.",
  parameters: {
    type: "object" as const,
    properties: {
      mission_id: {
        type: "number",
        description: "The mission ID to review",
      },
      action: {
        type: "string",
        enum: ["revise", "approve"],
        description: "'revise' to send back for improvement, 'approve' to accept",
      },
      feedback: {
        type: "string",
        description: "What needs to be fixed/improved (required for 'revise')",
      },
    },
    required: ["mission_id", "action"],
  },
  async execute(args: { mission_id: number; action: string; feedback?: string }) {
    return await agencyFetch(`/api/mission/${args.mission_id}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        action: args.action,
        feedback: args.feedback || "",
      }),
    });
  },
};

const missionStatusTool = {
  name: "agency_mission_status",
  description:
    "Check the status of a specific mission. " +
    "Returns status, result summary, and generated artifacts. " +
    "Note: results are also delivered automatically via callback.",
  parameters: {
    type: "object" as const,
    properties: {
      mission_id: {
        type: "number",
        description: "The mission ID to check",
      },
    },
    required: ["mission_id"],
  },
  async execute(args: { mission_id: number }) {
    return await agencyFetch(`/api/mission/${args.mission_id}/status`);
  },
};

const missionsActiveTool = {
  name: "agency_missions_active",
  description:
    "List all currently active (queued or running) missions in Agency OS. " +
    "Use this to see what the agency is working on right now.",
  parameters: {
    type: "object" as const,
    properties: {},
  },
  async execute() {
    return await agencyFetch("/api/missions/active");
  },
};

// ── Plugin Registration ─────────────────────────────────────

export default function register(api: OpenClawPluginApi) {
  api.registerTool(orchestrateTool as any, { optional: false });
  api.registerTool(missionFeedbackTool as any, { optional: false });
  api.registerTool(missionStatusTool as any, { optional: true });
  api.registerTool(missionsActiveTool as any, { optional: true });
}
