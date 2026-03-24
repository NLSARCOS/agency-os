{
  "payloads": [
    {
      "text": "⚠️ API rate limit reached. Please try again later.",
      "mediaUrl": null
    }
  ],
  "meta": {
    "durationMs": 30945,
    "agentMeta": {
      "sessionId": "ca6491bb-16b3-4b49-bb36-2a407d39a2c8",
      "provider": "openrouter",
      "model": "qwen/qwen3-coder:free",
      "lastCallUsage": {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "total": 0
      }
    },
    "aborted": false,
    "systemPromptReport": {
      "source": "run",
      "generatedAt": 1774377208452,
      "sessionId": "ca6491bb-16b3-4b49-bb36-2a407d39a2c8",
      "sessionKey": "agent:main:main",
      "provider": "openrouter",
      "model": "qwen/qwen3-coder:free",
      "workspaceDir": "/home/nelson/.openclaw/workspace",
      "bootstrapMaxChars": 20000,
      "bootstrapTotalMaxChars": 150000,
      "bootstrapTruncation": {
        "warningMode": "once",
        "warningShown": false,
        "truncatedFiles": 0,
        "nearLimitFiles": 0,
        "totalNearLimit": false
      },
      "sandbox": {
        "mode": "off",
        "sandboxed": false
      },
      "systemPrompt": {
        "chars": 35909,
        "projectContextChars": 16490,
        "nonProjectContextChars": 19419
      },
      "injectedWorkspaceFiles": [
        {
          "name": "AGENTS.md",
          "path": "/home/nelson/.openclaw/workspace/AGENTS.md",
          "missing": false,
          "rawChars": 1960,
          "injectedChars": 1960,
          "truncated": false
        },
        {
          "name": "SOUL.md",
          "path": "/home/nelson/.openclaw/workspace/SOUL.md",
          "missing": false,
          "rawChars": 5936,
          "injectedChars": 5936,
          "truncated": false
        },
        {
          "name": "TOOLS.md",
          "path": "/home/nelson/.openclaw/workspace/TOOLS.md",
          "missing": false,
          "rawChars": 850,
          "injectedChars": 850,
          "truncated": false
        },
        {
          "name": "IDENTITY.md",
          "path": "/home/nelson/.openclaw/workspace/IDENTITY.md",
          "missing": false,
          "rawChars": 231,
          "injectedChars": 231,
          "truncated": false
        },
        {
          "name": "USER.md",
          "path": "/home/nelson/.openclaw/workspace/USER.md",
          "missing": false,
          "rawChars": 204,
          "injectedChars": 204,
          "truncated": false
        },
        {
          "name": "HEARTBEAT.md",
          "path": "/home/nelson/.openclaw/workspace/HEARTBEAT.md",
          "missing": false,
          "rawChars": 1354,
          "injectedChars": 1354,
          "truncated": false
        },
        {
          "name": "BOOTSTRAP.md",
          "path": "/home/nelson/.openclaw/workspace/BOOTSTRAP.md",
          "missing": true,
          "rawChars": 0,
          "injectedChars": 68,
          "truncated": false
        },
        {
          "name": "MEMORY.md",
          "path": "/home/nelson/.openclaw/workspace/MEMORY.md",
          "missing": false,
          "rawChars": 5285,
          "injectedChars": 5285,
          "truncated": false
        }
      ],
      "skills": {
        "promptChars": 7822,
        "entries": [
          {
            "name": "clawhub",
            "blockChars": 432
          },
          {
            "name": "coding-agent",
            "blockChars": 832
          },
          {
            "name": "gh-issues",
            "blockChars": 508
          },
          {
            "name": "github",
            "blockChars": 572
          },
          {
            "name": "healthcheck",
            "blockChars": 491
          },
          {
            "name": "mcporter",
            "blockChars": 330
          },
          {
            "name": "node-connect",
            "blockChars": 541
          },
          {
            "name": "openai-whisper",
            "blockChars": 233
          },
          {
            "name": "oracle",
            "blockChars": 276
          },
          {
            "name": "skill-creator",
            "blockChars": 759
          },
          {
            "name": "video-frames",
            "blockChars": 229
          },
          {
            "name": "weather",
            "blockChars": 416
          },
          {
            "name": "b2b-sales-prospecting-agent",
            "blockChars": 548
          },
          {
            "name": "ui-development",
            "blockChars": 613
          },
          {
            "name": "learning-engine",
            "blockChars": 225
          },
          {
            "name": "marketing-strategy-pmm",
            "blockChars": 403
          }
        ]
      },
      "tools": {
        "listChars": 3103,
        "schemaChars": 19925,
        "entries": [
          {
            "name": "read",
            "summaryChars": 298,
            "schemaChars": 392,
            "propertiesCount": 4
          },
          {
            "name": "edit",
            "summaryChars": 129,
            "schemaChars": 591,
            "propertiesCount": 6
          },
          {
            "name": "write",
            "summaryChars": 127,
            "schemaChars": 313,
            "propertiesCount": 3
          },
          {
            "name": "exec",
            "summaryChars": 181,
            "schemaChars": 1086,
            "propertiesCount": 12
          },
          {
            "name": "process",
            "summaryChars": 85,
            "schemaChars": 961,
            "propertiesCount": 12
          },
          {
            "name": "browser",
            "summaryChars": 1683,
            "schemaChars": 2799,
            "propertiesCount": 48
          },
          {
            "name": "canvas",
            "summaryChars": 106,
            "schemaChars": 661,
            "propertiesCount": 18
          },
          {
            "name": "nodes",
            "summaryChars": 122,
            "schemaChars": 1800,
            "propertiesCount": 37
          },
          {
            "name": "cron",
            "summaryChars": 2689,
            "schemaChars": 690,
            "propertiesCount": 13
          },
          {
            "name": "message",
            "summaryChars": 130,
            "schemaChars": 5025,
            "propertiesCount": 94
          },
          {
            "name": "tts",
            "summaryChars": 152,
            "schemaChars": 223,
            "propertiesCount": 2
          },
          {
            "name": "gateway",
            "summaryChars": 464,
            "schemaChars": 497,
            "propertiesCount": 12
          },
          {
            "name": "agents_list",
            "summaryChars": 118,
            "schemaChars": 33,
            "propertiesCount": 0
          },
          {
            "name": "sessions_list",
            "summaryChars": 54,
            "schemaChars": 212,
            "propertiesCount": 4
          },
          {
            "name": "sessions_history",
            "summaryChars": 36,
            "schemaChars": 161,
            "propertiesCount": 3
          },
          {
            "name": "sessions_send",
            "summaryChars": 84,
            "schemaChars": 273,
            "propertiesCount": 5
          },
          {
            "name": "sessions_yield",
            "summaryChars": 97,
            "schemaChars": 60,
            "propertiesCount": 1
          },
          {
            "name": "sessions_spawn",
            "summaryChars": 198,
            "schemaChars": 1179,
            "propertiesCount": 17
          },
          {
            "name": "subagents",
            "summaryChars": 105,
            "schemaChars": 191,
            "propertiesCount": 4
          },
          {
            "name": "session_status",
            "summaryChars": 207,
            "schemaChars": 89,
            "propertiesCount": 2
          },
          {
            "name": "web_search",
            "summaryChars": 188,
            "schemaChars": 1443,
            "propertiesCount": 10
          },
          {
            "name": "web_fetch",
            "summaryChars": 129,
            "schemaChars": 374,
            "propertiesCount": 3
          },
          {
            "name": "agency_orchestrate",
            "summaryChars": 257,
            "schemaChars": 235,
            "propertiesCount": 2
          },
          {
            "name": "agency_mission_feedback",
            "summaryChars": 342,
            "schemaChars": 370,
            "propertiesCount": 3
          },
          {
            "name": "memory_search",
            "summaryChars": 334,
            "schemaChars": 139,
            "propertiesCount": 3
          },
          {
            "name": "memory_get",
            "summaryChars": 151,
            "schemaChars": 128,
            "propertiesCount": 3
          }
        ]
      }
    },
    "stopReason": "error"
  }
}