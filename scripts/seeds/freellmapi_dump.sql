INSERT INTO "settings" ("key","value") VALUES ('embeddings_default_family','gemini-embedding-001');
INSERT INTO "settings" ("key","value") VALUES ('unified_api_key','freellmapi-2f7230df00a7522f8c6a3a6d0ecd4996825e9a719eab9d60');
INSERT INTO "settings" ("key","value") VALUES ('catalog_applied_version','2026.06.28.065aae');
INSERT INTO "settings" ("key","value") VALUES ('catalog_applied_tier','monthly');
INSERT INTO "settings" ("key","value") VALUES ('catalog_applied_json','{
  "version": "2026.06.28.065aae",
  "generatedAt": "2026-06-28T19:38:15.292Z",
  "tier": "monthly",
  "counts": {
    "platforms": 15,
    "models": 83,
    "enabledModels": 83,
    "quirks": 17
  },
  "platforms": [
    {
      "id": "cerebras",
      "name": "Cerebras"
    },
    {
      "id": "cloudflare",
      "name": "Cloudflare Workers AI"
    },
    {
      "id": "cohere",
      "name": "Cohere"
    },
    {
      "id": "github",
      "name": "GitHub Models"
    },
    {
      "id": "google",
      "name": "Google AI Studio"
    },
    {
      "id": "groq",
      "name": "Groq"
    },
    {
      "id": "kilo",
      "name": "Kilo Gateway"
    },
    {
      "id": "llm7",
      "name": "LLM7"
    },
    {
      "id": "mistral",
      "name": "Mistral"
    },
    {
      "id": "nvidia",
      "name": "NVIDIA NIM"
    },
    {
      "id": "ollama",
      "name": "Ollama Cloud"
    },
    {
      "id": "opencode",
      "name": "OpenCode Zen"
    },
    {
      "id": "openrouter",
      "name": "OpenRouter"
    },
    {
      "id": "pollinations",
      "name": "Pollinations"
    },
    {
      "id": "zhipu",
      "name": "Zhipu AI"
    }
  ],
  "models": [
    {
      "platform": "cloudflare",
      "modelId": "@cf/moonshotai/kimi-k2.6",
      "displayName": "Kimi K2.6 (CF)",
      "intelligenceRank": 2,
      "speedRank": 11,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~10-20M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "ollama",
      "modelId": "qwen3-coder:480b",
      "displayName": "Qwen3-Coder 480B (Ollama)",
      "intelligenceRank": 2,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~5-10M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "qwen/qwen3-coder:free",
      "displayName": "Qwen3 Coder 480B (free)",
      "intelligenceRank": 2,
      "speedRank": 10,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 50,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 1048576,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "google",
      "modelId": "gemini-3.5-flash",
      "displayName": "Gemini 3.5 Flash",
      "intelligenceRank": 3,
      "speedRank": 5,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 10,
        "rpd": 20,
        "tpm": 250000,
        "tpd": null
      },
      "monthlyTokenBudget": "~3M",
      "contextWindow": 1048576,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "nvidia",
      "modelId": "deepseek-ai/deepseek-v4-pro",
      "displayName": "DeepSeek V4 Pro (NV)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "minimaxai/minimax-m2.7",
      "displayName": "MiniMax M2.7 (NV)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 196608,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "mistralai/mistral-large-3-675b-instruct-2512",
      "displayName": "Mistral Large 3 675B (NV)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "moonshotai/kimi-k2.6",
      "displayName": "Kimi K2.6 (NV)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "ollama",
      "modelId": "qwen3-coder-next",
      "displayName": "Qwen3-Coder Next (Ollama)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~10-20M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "qwen/qwen3-next-80b-a3b-instruct:free",
      "displayName": "Qwen3-Next 80B (free)",
      "intelligenceRank": 3,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "deepseek-ai/deepseek-v4-flash",
      "displayName": "DeepSeek V4 Flash (NV)",
      "intelligenceRank": 4,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "opencode",
      "modelId": "deepseek-v4-flash-free",
      "displayName": "DeepSeek V4 Flash Free (OpenCode Zen)",
      "intelligenceRank": 4,
      "speedRank": 4,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "promo (trial)",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "zen-promo-roster",
          "title": "Limited-time promo, roster rotates",
          "body": "OpenCode Zen free models are explicitly limited-time promotional access (\"available for a limited time\" per the docs), not a recurring quota. The roster rotates: qwen3.6-plus and minimax-m3 promos already ended. Expect any row here to die without notice; prompts/outputs may be used for model improvement.",
          "severity": "warning"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "z-ai/glm-5.1",
      "displayName": "GLM-5.1 (NV, slow cold-start)",
      "intelligenceRank": 5,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 200000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "openrouter/owl-alpha",
      "displayName": "Owl Alpha (OR-house)",
      "intelligenceRank": 5,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 1048576,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "cerebras",
      "modelId": "gpt-oss-120b",
      "displayName": "GPT-OSS 120B (Cerebras)",
      "intelligenceRank": 6,
      "speedRank": 1,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 5,
        "rpd": null,
        "tpm": 30000,
        "tpd": 1000000
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/openai/gpt-oss-120b",
      "displayName": "GPT-OSS 120B (CF)",
      "intelligenceRank": 6,
      "speedRank": 11,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~18-45M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "groq",
      "modelId": "groq/compound",
      "displayName": "Compound (Groq)",
      "intelligenceRank": 6,
      "speedRank": 2,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 30,
        "rpd": 250,
        "tpm": 70000,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "groq",
      "modelId": "openai/gpt-oss-120b",
      "displayName": "GPT-OSS 120B (Groq)",
      "intelligenceRank": 6,
      "speedRank": 2,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "ollama",
      "modelId": "glm-4.7",
      "displayName": "GLM-4.7 (Ollama)",
      "intelligenceRank": 6,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~5-10M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "ollama",
      "modelId": "gpt-oss:120b",
      "displayName": "GPT-OSS 120B (Ollama)",
      "intelligenceRank": 6,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~10-20M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "openai/gpt-oss-120b:free",
      "displayName": "GPT-OSS 120B (free)",
      "intelligenceRank": 6,
      "speedRank": 7,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 1000,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~120M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cerebras",
      "modelId": "zai-glm-4.7",
      "displayName": "GLM-4.7 (Cerebras)",
      "intelligenceRank": 7,
      "speedRank": 1,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 5,
        "rpd": null,
        "tpm": 30000,
        "tpd": 1000000
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 8192,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/qwen/qwen3-30b-a3b-fp8",
      "displayName": "Qwen3 30B-A3B fp8 (CF)",
      "intelligenceRank": 7,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~18-45M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "nvidia/nemotron-3-ultra-550b-a55b:free",
      "displayName": "Nemotron 3 Ultra 550B (free, slow)",
      "intelligenceRank": 7,
      "speedRank": 11,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 1000000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
      "displayName": "DeepSeek R1 Distill Qwen 32B (CF)",
      "intelligenceRank": 9,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~3-5M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/nvidia/nemotron-3-120b-a12b",
      "displayName": "Nemotron 3 120B (CF)",
      "intelligenceRank": 9,
      "speedRank": 11,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~5-10M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/zai-org/glm-4.7-flash",
      "displayName": "GLM-4.7 Flash (CF)",
      "intelligenceRank": 10,
      "speedRank": 11,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~18-45M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "opencode",
      "modelId": "big-pickle",
      "displayName": "Big Pickle (OpenCode Zen, stealth)",
      "intelligenceRank": 10,
      "speedRank": 4,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "promo (trial)",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "zen-promo-roster",
          "title": "Limited-time promo, roster rotates",
          "body": "OpenCode Zen free models are explicitly limited-time promotional access (\"available for a limited time\" per the docs), not a recurring quota. The roster rotates: qwen3.6-plus and minimax-m3 promos already ended. Expect any row here to die without notice; prompts/outputs may be used for model improvement.",
          "severity": "warning"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "meta/llama-4-maverick-17b-128e-instruct",
      "displayName": "Llama 4 Maverick (NV)",
      "intelligenceRank": 11,
      "speedRank": 6,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/meta/llama-4-scout-17b-16e-instruct",
      "displayName": "Llama 4 Scout (CF)",
      "intelligenceRank": 12,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~18-45M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cohere",
      "modelId": "command-a-reasoning-08-2025",
      "displayName": "Command A Reasoning (08-2025)",
      "intelligenceRank": 13,
      "speedRank": 11,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 33,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~1-2M",
      "contextWindow": 256000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "kilo",
      "modelId": "poolside/laguna-m.1:free",
      "displayName": "Poolside Laguna M.1 (Kilo)",
      "intelligenceRank": 13,
      "speedRank": 8,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 200/hr per IP",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "keyless-anonymous",
          "title": "No API key required",
          "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "poolside/laguna-m.1:free",
      "displayName": "Poolside Laguna M.1 (free)",
      "intelligenceRank": 13,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "kilo",
      "modelId": "stepfun/step-3.7-flash:free",
      "displayName": "StepFun Step 3.7 Flash (Kilo)",
      "intelligenceRank": 14,
      "speedRank": 3,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 200/hr per IP",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "keyless-anonymous",
          "title": "No API key required",
          "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "mistral",
      "modelId": "mistral-large-latest",
      "displayName": "Mistral Large 3",
      "intelligenceRank": 14,
      "speedRank": 8,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "mistral",
      "modelId": "mistral-medium-latest",
      "displayName": "Mistral Medium 3.5",
      "intelligenceRank": 14,
      "speedRank": 8,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "mistral",
      "modelId": "mistral-small-latest",
      "displayName": "Mistral Small 4",
      "intelligenceRank": 14,
      "speedRank": 8,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "opencode",
      "modelId": "mimo-v2.5-free",
      "displayName": "MiMo-V2.5 Free (OpenCode Zen)",
      "intelligenceRank": 14,
      "speedRank": 4,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "promo (trial)",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "zen-promo-roster",
          "title": "Limited-time promo, roster rotates",
          "body": "OpenCode Zen free models are explicitly limited-time promotional access (\"available for a limited time\" per the docs), not a recurring quota. The roster rotates: qwen3.6-plus and minimax-m3 promos already ended. Expect any row here to die without notice; prompts/outputs may be used for model improvement.",
          "severity": "warning"
        }
      ]
    },
    {
      "platform": "llm7",
      "modelId": "codestral-latest",
      "displayName": "Codestral (LLM7)",
      "intelligenceRank": 16,
      "speedRank": 8,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 100,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~2M (60-100/hr)",
      "contextWindow": 32000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "keyless-anonymous",
          "title": "No API key required",
          "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "mistral",
      "modelId": "codestral-latest",
      "displayName": "Codestral",
      "intelligenceRank": 16,
      "speedRank": 6,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 256000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "mistral",
      "modelId": "devstral-latest",
      "displayName": "Devstral",
      "intelligenceRank": 16,
      "speedRank": 8,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
      "displayName": "Llama 3.3 70B fp8-fast (CF)",
      "intelligenceRank": 17,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~18-45M",
      "contextWindow": 24000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "groq",
      "modelId": "llama-3.3-70b-versatile",
      "displayName": "Llama 3.3 70B",
      "intelligenceRank": 17,
      "speedRank": 2,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 12000,
        "tpd": 100000
      },
      "monthlyTokenBudget": "~15M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "nvidia",
      "modelId": "meta/llama-3.1-70b-instruct",
      "displayName": "Llama 3.1 70B (NV)",
      "intelligenceRank": 17,
      "speedRank": 6,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "meta/llama-3.3-70b-instruct",
      "displayName": "Llama 3.3 70B (NV)",
      "intelligenceRank": 17,
      "speedRank": 6,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "meta-llama/llama-3.3-70b-instruct:free",
      "displayName": "Llama 3.3 70B (OR free)",
      "intelligenceRank": 17,
      "speedRank": 5,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 1000,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~120M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "nousresearch/hermes-3-llama-3.1-405b:free",
      "displayName": "Hermes 3 405B (free)",
      "intelligenceRank": 17,
      "speedRank": 9,
      "sizeLabel": "Frontier",
      "limits": {
        "rpm": 20,
        "rpd": 50,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "groq",
      "modelId": "groq/compound-mini",
      "displayName": "Compound Mini (Groq)",
      "intelligenceRank": 18,
      "speedRank": 2,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 30,
        "rpd": 250,
        "tpm": 70000,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "groq",
      "modelId": "openai/gpt-oss-20b",
      "displayName": "GPT-OSS 20B (Groq)",
      "intelligenceRank": 18,
      "speedRank": 2,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "groq",
      "modelId": "openai/gpt-oss-safeguard-20b",
      "displayName": "GPT-OSS Safeguard 20B (Groq)",
      "intelligenceRank": 18,
      "speedRank": 2,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "ollama",
      "modelId": "gpt-oss:20b",
      "displayName": "GPT-OSS 20B (Ollama)",
      "intelligenceRank": 18,
      "speedRank": 10,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~20-30M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "openai/gpt-oss-20b:free",
      "displayName": "GPT-OSS 20B (free)",
      "intelligenceRank": 18,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "pollinations",
      "modelId": "openai-fast",
      "displayName": "GPT-OSS 20B (Pollinations)",
      "intelligenceRank": 18,
      "speedRank": 10,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~? (anon)",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "pollinations-degraded",
          "title": "Anon tier degraded (1 concurrent)",
          "body": "Pollinations’ legacy text API is deprecated for authenticated users (replacement enter.pollinations.ai is pay-as-you-go), but anonymous access is explicitly unaffected. Anon is queue-limited to 1 concurrent request per IP and serves a single model (openai-fast); expect 429 \"Queue full\" under any parallelism. Live-probed 2026-06-10.",
          "severity": "warning"
        },
        {
          "slug": "keyless-anonymous",
          "title": "No API key required",
          "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "zhipu",
      "modelId": "glm-4.7-flash",
      "displayName": "GLM-4.7 Flash",
      "intelligenceRank": 18,
      "speedRank": 4,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": 1000000
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "google",
      "modelId": "gemma-4-31b-it",
      "displayName": "Gemma 4 31B IT",
      "intelligenceRank": 19,
      "speedRank": 4,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 15,
        "rpd": 1000,
        "tpm": 250000,
        "tpd": null
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 32768,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "google/gemma-4-31b-it:free",
      "displayName": "Gemma 4 31B (free)",
      "intelligenceRank": 19,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "github",
      "modelId": "openai/gpt-4.1",
      "displayName": "GPT-4.1 (GitHub)",
      "intelligenceRank": 20,
      "speedRank": 7,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 10,
        "rpd": 50,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~9M",
      "contextWindow": 128000,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "google",
      "modelId": "gemini-2.5-flash",
      "displayName": "Gemini 2.5 Flash",
      "intelligenceRank": 20,
      "speedRank": 5,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 10,
        "rpd": 20,
        "tpm": 250000,
        "tpd": null
      },
      "monthlyTokenBudget": "~3M",
      "contextWindow": 1048576,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "google",
      "modelId": "gemma-4-26b-a4b-it",
      "displayName": "Gemma 4 26B IT",
      "intelligenceRank": 20,
      "speedRank": 4,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 15,
        "rpd": 1000,
        "tpm": 250000,
        "tpd": null
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 32768,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "mistral",
      "modelId": "magistral-medium-latest",
      "displayName": "Magistral Medium",
      "intelligenceRank": 21,
      "speedRank": 8,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "zhipu",
      "modelId": "glm-4.6v-flash",
      "displayName": "GLM-4.6V Flash",
      "intelligenceRank": 21,
      "speedRank": 4,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~30M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "zhipu-shared-key",
          "title": "Works with existing Zhipu key",
          "body": "glm-4.6v-flash is listed Free on Z.AI and answers 200 with the existing bigmodel.cn key; vision and structured tool calls both live-verified.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/google/gemma-4-26b-a4b-it",
      "displayName": "Gemma 4 26B-A4B it (CF)",
      "intelligenceRank": 22,
      "speedRank": 11,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~10-20M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "kilo",
      "modelId": "nvidia/nemotron-3-super-120b-a12b:free",
      "displayName": "Nemotron 3 Super 120B (Kilo)",
      "intelligenceRank": 22,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~2-3M (200/hr)",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "keyless-anonymous",
          "title": "No API key required",
          "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "nvidia/nemotron-3-nano-30b-a3b",
      "displayName": "Nemotron 3 Nano 30B (NV)",
      "intelligenceRank": 22,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "nvidia",
      "modelId": "nvidia/nemotron-3-super-120b-a12b",
      "displayName": "Nemotron 3 Super 120B (NV)",
      "intelligenceRank": 22,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 40,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "free · 40 RPM",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "nvidia-rate-limited",
          "title": "Recurring free, 40 RPM, eval-only ToS",
          "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "ollama",
      "modelId": "gemma4:31b",
      "displayName": "Gemma 4 31B (Ollama)",
      "intelligenceRank": 22,
      "speedRank": 10,
      "sizeLabel": "Large",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~20-30M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "google/gemma-4-26b-a4b-it:free",
      "displayName": "Gemma 4 26B-A4B (free)",
      "intelligenceRank": 22,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "nvidia/nemotron-3-super-120b-a12b:free",
      "displayName": "Nemotron 3 Super 120B (free)",
      "intelligenceRank": 22,
      "speedRank": 9,
      "sizeLabel": "Large",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 1000000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "nvidia/nemotron-3-nano-30b-a3b:free",
      "displayName": "Nemotron 3 Nano 30B (free)",
      "intelligenceRank": 23,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
      "displayName": "Nemotron 3 Nano 30B Reasoning (free)",
      "intelligenceRank": 23,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cohere",
      "modelId": "command-r-08-2024",
      "displayName": "Command R (08-2024)",
      "intelligenceRank": 25,
      "speedRank": 11,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 20,
        "rpd": 33,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~1-2M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
      "displayName": "Dolphin Mistral 24B Venice (free)",
      "intelligenceRank": 25,
      "speedRank": 9,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 32768,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "google",
      "modelId": "gemini-2.5-flash-lite",
      "displayName": "Gemini 2.5 Flash-Lite",
      "intelligenceRank": 26,
      "speedRank": 3,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 15,
        "rpd": 20,
        "tpm": 250000,
        "tpd": null
      },
      "monthlyTokenBudget": "~3M",
      "contextWindow": 1048576,
      "enabled": true,
      "supportsVision": true,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "poolside/laguna-xs.2:free",
      "displayName": "Poolside Laguna XS.2 (free)",
      "intelligenceRank": 26,
      "speedRank": 10,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cohere",
      "modelId": "command-a-03-2025",
      "displayName": "Command-A (03-2025)",
      "intelligenceRank": 27,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 33,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~1-2M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "cohere",
      "modelId": "command-r-plus-08-2024",
      "displayName": "Command R+ (08-2024)",
      "intelligenceRank": 27,
      "speedRank": 11,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 33,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~1-2M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "groq",
      "modelId": "llama-3.1-8b-instant",
      "displayName": "Llama 3.1 8B Instant",
      "intelligenceRank": 28,
      "speedRank": 2,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 30,
        "rpd": 14400,
        "tpm": 6000,
        "tpd": 500000
      },
      "monthlyTokenBudget": "~15M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "mistral",
      "modelId": "ministral-8b-latest",
      "displayName": "Ministral 3 8B",
      "intelligenceRank": 28,
      "speedRank": 8,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 2,
        "rpd": null,
        "tpm": 500000,
        "tpd": null
      },
      "monthlyTokenBudget": "~50-100M",
      "contextWindow": 262144,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": true,
      "quirks": []
    },
    {
      "platform": "openrouter",
      "modelId": "nvidia/nemotron-nano-9b-v2:free",
      "displayName": "Nemotron Nano 9B v2 (free)",
      "intelligenceRank": 28,
      "speedRank": 10,
      "sizeLabel": "Medium",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 128000,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "cloudflare",
      "modelId": "@cf/ibm-granite/granite-4.0-h-micro",
      "displayName": "Granite 4.0 H Micro (CF)",
      "intelligenceRank": 29,
      "speedRank": 11,
      "sizeLabel": "Small",
      "limits": {
        "rpm": null,
        "rpd": null,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~5-10M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "cloudflare-key-format",
          "title": "Key is account_id:token",
          "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "liquid/lfm-2.5-1.2b-instruct:free",
      "displayName": "Liquid LFM 2.5 1.2B (free)",
      "intelligenceRank": 30,
      "speedRank": 10,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 32768,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "liquid/lfm-2.5-1.2b-thinking:free",
      "displayName": "Liquid LFM 2.5 1.2B Thinking (free)",
      "intelligenceRank": 30,
      "speedRank": 10,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 32768,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    },
    {
      "platform": "openrouter",
      "modelId": "meta-llama/llama-3.2-3b-instruct:free",
      "displayName": "Llama 3.2 3B (free)",
      "intelligenceRank": 30,
      "speedRank": 9,
      "sizeLabel": "Small",
      "limits": {
        "rpm": 20,
        "rpd": 200,
        "tpm": null,
        "tpd": null
      },
      "monthlyTokenBudget": "~6M",
      "contextWindow": 131072,
      "enabled": true,
      "supportsVision": false,
      "supportsTools": false,
      "quirks": [
        {
          "slug": "or-free-cap-account-wide",
          "title": "Daily :free cap is account-wide",
          "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
          "severity": "info"
        }
      ]
    }
  ],
  "quirks": [
    {
      "slug": "cloudflare-key-format",
      "title": "Key is account_id:token",
      "body": "Cloudflare Workers AI authenticates with a combined credential in the form \"account_id:token\", not a bare token.",
      "severity": "info",
      "targets": [
        {
          "platform": "cloudflare",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "keyless-anonymous",
      "title": "No API key required",
      "body": "Routes anonymously — the catalog ships a keyless sentinel row and calls work with no account or key.",
      "severity": "info",
      "targets": [
        {
          "platform": "kilo",
          "modelGlob": null
        },
        {
          "platform": "llm7",
          "modelGlob": null
        },
        {
          "platform": "pollinations",
          "modelGlob": null
        },
        {
          "platform": "ovh",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "nim-gemma-hung",
      "title": "NIM gemma route hangs",
      "body": "The NVIDIA NIM gemma endpoint is listed but hangs (capacity starvation plus an upstream FlashAttention bug). Paused; probe with a 120s timeout before re-enabling.",
      "severity": "blocker",
      "targets": [
        {
          "platform": "nvidia",
          "modelGlob": "*gemma*"
        }
      ]
    },
    {
      "slug": "nvidia-rate-limited",
      "title": "Recurring free, 40 RPM, eval-only ToS",
      "body": "NVIDIA NIM replaced its depleting trial credits with a recurring per-account rate limit (40 RPM default, varies by model), verified June 2026. The trial ToS still scopes usage to evaluation/prototyping, not production.",
      "severity": "info",
      "targets": [
        {
          "platform": "nvidia",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "or-free-cap-account-wide",
      "title": "Daily :free cap is account-wide",
      "body": "OpenRouter’s :free daily cap (50/day, or 1000/day once you have ever bought $10 of credits) is shared across ALL :free models on the account, not per model. Per-row rpd values here are therefore optimistic; the router’s cooldown handling absorbs the shared 429s.",
      "severity": "info",
      "targets": [
        {
          "platform": "openrouter",
          "modelGlob": "*:free"
        }
      ]
    },
    {
      "slug": "or-ultra-hangs",
      "title": "OpenRouter ultra route hangs",
      "body": "nemotron-3-ultra (550B) on OpenRouter takes 180s+ even on trivial prompts (heavily congested), so its OR row is seeded disabled. Use the OpenCode Zen route instead.",
      "severity": "warning",
      "targets": [
        {
          "platform": "openrouter",
          "modelGlob": "*nemotron-3-ultra*"
        }
      ]
    },
    {
      "slug": "ovh-anon-trickle",
      "title": "Anonymous tier is 2 req/min",
      "body": "OVH AI Endpoints anonymous mode is documented at 2 req/min per IP per model (observed even stricter across models). The 400 req/min authenticated tier requires a Public Cloud project with a payment method, so the catalog ships the keyless path. Treat as a breadth/fallback tier, not a throughput tier.",
      "severity": "warning",
      "targets": [
        {
          "platform": "ovh",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "pollinations-degraded",
      "title": "Anon tier degraded (1 concurrent)",
      "body": "Pollinations’ legacy text API is deprecated for authenticated users (replacement enter.pollinations.ai is pay-as-you-go), but anonymous access is explicitly unaffected. Anon is queue-limited to 1 concurrent request per IP and serves a single model (openai-fast); expect 429 \"Queue full\" under any parallelism. Live-probed 2026-06-10.",
      "severity": "warning",
      "targets": [
        {
          "platform": "pollinations",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "zen-promo-roster",
      "title": "Limited-time promo, roster rotates",
      "body": "OpenCode Zen free models are explicitly limited-time promotional access (\"available for a limited time\" per the docs), not a recurring quota. The roster rotates: qwen3.6-plus and minimax-m3 promos already ended. Expect any row here to die without notice; prompts/outputs may be used for model improvement.",
      "severity": "warning",
      "targets": [
        {
          "platform": "opencode",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "zen-serves-ultra-fast",
      "title": "Zen serves the 550B fast",
      "body": "OpenCode Zen serves nemotron-3-ultra in ~2s with working tool calls where the OpenRouter route hangs — the live-verified path for this model.",
      "severity": "info",
      "targets": [
        {
          "platform": "opencode",
          "modelGlob": "*nemotron-3-ultra*"
        }
      ]
    },
    {
      "slug": "zhipu-shared-key",
      "title": "Works with existing Zhipu key",
      "body": "glm-4.6v-flash is listed Free on Z.AI and answers 200 with the existing bigmodel.cn key; vision and structured tool calls both live-verified.",
      "severity": "info",
      "targets": [
        {
          "platform": "zhipu",
          "modelGlob": "*glm-4.6v*"
        }
      ]
    },
    {
      "slug": "aihorde-anon-slow",
      "title": "Free volunteer queue, slow",
      "body": "AI Horde routes to volunteer-run workers through a priority queue, so latency is seconds to minutes, not the sub-second of hosted providers. The anonymous key 0000000000 runs at the lowest priority; register a free key at aihorde.net for higher priority. The provider uses a 120s timeout.",
      "severity": "warning",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "aihorde-no-tools",
      "title": "No tool calling",
      "body": "AI Horde''s OpenAI-compatible proxy does not support function/tool calling. The provider drops tools, tool_choice and parallel_tool_calls so a tool-using request still completes as plain chat instead of failing.",
      "severity": "info",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "aihorde-usage-estimated",
      "title": "Usage is kudos; tokens estimated",
      "body": "The proxy returns usage as {\"kudos\": N} with no token counts, and rejects max_tokens below 16 and a non-array stop. The AIHordeProvider normalizes the request (floors max_tokens, wraps stop) and synthesizes prompt/completion token estimates so analytics and savings math aren''t zero.",
      "severity": "info",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "aihorde-roster-rotates",
      "title": "Roster + context depend on online workers",
      "body": "Model availability changes as volunteer workers come and go, so a listed model can be temporarily unserved. The effective context window is set by the worker (often 4-8K), not the model''s native maximum.",
      "severity": "info",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "aihorde-quality-uneven",
      "title": "Uneven quality",
      "body": "Output quality varies by worker and quantization, and some workers append template or instruction text after the answer. Best treated as free fallback capacity, not a primary model.",
      "severity": "warning",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": null
        }
      ]
    },
    {
      "slug": "aihorde-behemoth-slow",
      "title": "123B has heavy queue (seeded disabled)",
      "body": "Behemoth-X-123B has deep queue depth (50s+ ETA even on trivial prompts). Seeded disabled; enable only if minute-scale latency is acceptable.",
      "severity": "warning",
      "targets": [
        {
          "platform": "aihorde",
          "modelGlob": "*Behemoth-X-123B*"
        }
      ]
    }
  ]
}
');
INSERT INTO "settings" ("key","value") VALUES ('catalog_last_sync_ms','1782742201447');
INSERT INTO "settings" ("key","value") VALUES ('catalog_last_error','');
INSERT INTO "settings" ("key","value") VALUES ('routing_strategy','smartest');
INSERT INTO "api_keys" ("id","platform","label","encrypted_key","iv","auth_tag","status","enabled","created_at","last_checked_at","base_url") VALUES (1,'groq','','cf048a329458c24405333e1bbdc0297fbc57a22b7c7cf146e7acf257e2105a73a23cd1a50c8f43b64bebab3fb8e387d5a03fd9b11c32c353','d3ec0c5d0d6b4e37ddf4ba3d971fd0a1','a800d7053b0dc400c79445c6cd85e020','healthy',1,'2026-06-25 05:15:31','2026-06-28 13:54:36',NULL);
INSERT INTO "api_keys" ("id","platform","label","encrypted_key","iv","auth_tag","status","enabled","created_at","last_checked_at","base_url") VALUES (2,'google','','625297ce35731d67941f95bd9d94681ef269fb93e50ee8c69fb06220b5e3edf81b525a37a1290ed7ef381774ffe4b4d99fc4c9107b','8bb1c2347f376914451462044174c09c','1b937b4bdb50eae6e7b31031935f241a','healthy',1,'2026-06-25 05:15:42','2026-06-28 13:54:37',NULL);
INSERT INTO "api_keys" ("id","platform","label","encrypted_key","iv","auth_tag","status","enabled","created_at","last_checked_at","base_url") VALUES (3,'nvidia','','f9fd821f9c452fc4f86432add3494d684c4e27dd3bfb39f36f194fc5e4b04db7cfc03a9f33f6ec97876fc2d5fb4164b0d34e5d1834a30515edebf9c1894ba64ee24f896ab6dc','083403c353965f0c2043c9a40722d6d5','7e702620cbdb2d219d1f9216f7a25505','healthy',1,'2026-06-25 05:15:55','2026-06-28 13:54:37',NULL);
INSERT INTO "api_keys" ("id","platform","label","encrypted_key","iv","auth_tag","status","enabled","created_at","last_checked_at","base_url") VALUES (4,'openrouter','','deaa28fcd826d44e019ffd09e2a937e54307506b782410ec4422cab17b63b1a65ca9130827a82d44d14dbac62455d04efd4b8e81b46f65f79441ef85142e2cdd8ef6f467de709f9257','1a5a2dc0a0f6926fd0015b8535fd8361','a7874cdea461db36105add964c8d713b','healthy',1,'2026-06-25 05:16:08','2026-06-28 13:54:37',NULL);
INSERT INTO "api_keys" ("id","platform","label","encrypted_key","iv","auth_tag","status","enabled","created_at","last_checked_at","base_url") VALUES (5,'opencode','','42ea77136b6bf4ef3197ce2aae86539f01c7fd0468f60ea2616e7681a7e6488445228e3a058a695bcd07a0681f6887f5e9511c6c2e2374cf7e797e478fd66e97a4814b','98d6b461d33f163fa33528d8d8776295','03fe9da77a1ac08c3d51a8d3f76f2b8f','healthy',1,'2026-06-25 05:16:30','2026-06-28 13:54:38',NULL);