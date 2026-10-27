# Private LLM Deployment

Aiwana supports external provider mode and private-only mode.

External mode:

```env
LLM_PRIVACY_MODE=external_allowed
LLM_PROVIDER=groq
```

Private OpenAI-compatible endpoint:

```env
LLM_PRIVACY_MODE=private_only
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://private-vllm:8000/v1
LLM_API_KEY=
LLM_MODEL=
```

Ollama:

```env
LLM_PRIVACY_MODE=private_only
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
LLM_MODEL=
```

When private-only mode is active, public Groq/OpenAI providers are blocked. Aiwana must not silently fall back to a public provider.

