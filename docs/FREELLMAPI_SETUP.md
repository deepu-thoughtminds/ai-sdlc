# FreeLLMAPI Setup Guide

FreeLLMAPI is an open-source proxy that routes requests to free LLM providers (Gemini, OpenRouter, etc.) via an OpenAI-compatible API. The AI-SDLC Jira stack builds it from source at `./freellmapi` (a git submodule from `tashfeenahmed/freellmapi`).

---

## One-Time Setup

### 1. Generate the encryption key

FreeLLMAPI encrypts provider API keys at rest. You must generate a 64-character hex key:

```bash
openssl rand -hex 32
```

Copy the output into your `.env` file:

```
FREELLMAPI_ENCRYPTION_KEY=<your-64-char-hex-key>
```

### 2. Start the freellmapi service

```bash
docker compose up freellmapi -d
```

The first build compiles the Node.js monorepo (server + client). This may take 2-5 minutes.

### 3. Access the dashboard

Visit http://localhost:3001 in your browser to open the FreeLLMAPI dashboard.

---

## Adding Provider API Keys

Provider keys are configured through the FreeLLMAPI dashboard, not via environment variables. They are stored encrypted in the `freellmapi_data` Docker volume.

### Google Gemini

1. Get an API key from https://aistudio.google.com/apikey
2. Open http://localhost:3001/settings (or the Providers section in the dashboard)
3. Add your Gemini API key

### OpenRouter

1. Get an API key from https://openrouter.ai/keys
2. Open http://localhost:3001/settings (or the Providers section in the dashboard)
3. Add your OpenRouter API key

OpenRouter provides access to many free-tier models including Llama, Mistral, and others.

---

## Generating the FreeLLMAPI API Key

The `FREELLMAPI_API_KEY` is the unified key used by the hermes agent to authenticate requests to FreeLLMAPI.

1. Open http://localhost:3001 in your browser
2. Navigate to the API Keys section
3. Click "Generate API Key" (or "Create key")
4. Copy the generated key
5. Add it to your `.env` file:

```
FREELLMAPI_API_KEY=<your-generated-api-key>
```

6. Restart the hermes service to pick up the new key:

```bash
docker compose restart hermes
```

---

## Testing the Setup

Once a provider key and API key are configured, verify the proxy is working:

```bash
# List available models
curl http://localhost:3001/v1/models \
  -H "Authorization: Bearer $FREELLMAPI_API_KEY"

# Send a test completion
curl http://localhost:3001/v1/chat/completions \
  -H "Authorization: Bearer $FREELLMAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-2.0-flash",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

---

## Troubleshooting

### Container fails to start

Check logs:
```bash
docker compose logs freellmapi
```

Common causes:
- Missing `FREELLMAPI_ENCRYPTION_KEY` in `.env` (required — service won't start without it)
- Build failure — check if the `freellmapi` submodule is initialized:
  ```bash
  git submodule update --init freellmapi
  ```

### Provider requests failing

- Ensure you have added at least one provider API key via the dashboard
- Confirm the model name matches a provider you have configured
- Check the FreeLLMAPI dashboard for request logs

### Port conflict on 3001

If another service is already using port 3001, you can remap it in `docker-compose.yml`:
```yaml
ports:
  - "3002:3001"
```
Then update `FREELLMAPI_BASE_URL` in `.env` to `http://localhost:3002` for external access (inter-container communication always uses `http://freellmapi:3001`).

---

## Architecture Notes

- FreeLLMAPI runs inside the `ai-sdlc-net` Docker network as the `freellmapi` service
- Hermes (the AI agent) connects to it at `http://freellmapi:3001` (internal Docker hostname)
- The dashboard is exposed externally on `http://localhost:3001`
- Provider API keys are stored encrypted in the `freellmapi_data` named Docker volume
- The encryption key (`FREELLMAPI_ENCRYPTION_KEY`) is the only secret that must be in `.env`

---

## Submodule Management

FreeLLMAPI source is included as a git submodule. To update to a newer version:

```bash
cd freellmapi
git fetch origin
git checkout <new-tag-or-commit>
cd ..
git add freellmapi
git commit -m "chore: update freellmapi submodule to <version>"
```

To initialize after cloning this repo:
```bash
git submodule update --init freellmapi
```
