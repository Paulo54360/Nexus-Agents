# Nexus Agents — Plateforme Multi-Agents IA Auto-Hébergée

Plateforme personnelle d'orchestration d'agents IA pensée avec une approche **DevOps / LLMOps** (0 € à ~4 €/mois) :
- **Orchestration** : [LangGraph](https://github.com/langchain-ai/langgraph) (pattern *Supervisor*, mémoire persistante PostgreSQL, *Human-in-the-Loop* via `interrupt()`).
- **Outils modulaires** : **MCP (Model Context Protocol)** via `langchain-mcp-adapters` (Gmail, Google Calendar, Notion, et extensible vers Discord asso / GitHub Dev).
- **Routage LLM hybride** : **LiteLLM Proxy** (APIs Open-Source/Free Tier : Groq, Gemini, Mistral, GitHub Models + option **Ollama** sur Mac via Tailscale).
- **Interface multi-appareils** : Bot **Discord privé** (PC, Mac, iOS, Android — WebSocket sortant, zéro port public ouvert) avec boutons interactifs ✅/❌ pour valider les actions sensibles.
- **Observabilité & Ops** : Docker Compose multi-stage (`uv`), **Langfuse** auto-hébergé, métriques Prometheus (`/metrics`), CI **GitHub Actions**.

---

## Démarrage rapide (5 minutes en mode `MOCK_TOOLS=true`)

Le mode `MOCK_TOOLS=true` te permet de tester immédiatement le **Supervisor**, le routage **LiteLLM**, les **agents Gmail / Calendar / Notion** et les **boutons de validation Discord ✅/❌** avant même de configurer OAuth.

### 1. Configuration
```bash
cp .env.example .env
```
Renseigne au minimum :
- Une clé API gratuite : `GROQ_API_KEY` ou `GEMINI_API_KEY` (ou `GITHUB_TOKEN` via GitHub Models).
- Optionnel pour Discord dès le départ : `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_ID` et `DISCORD_COMMAND_CENTER_CHANNEL_ID`.

### 2. Lancer la stack avec Docker Compose
```bash
# Stack cœur (PostgreSQL pgvector + LiteLLM + Nexus)
docker compose up --build -d

# Avec Langfuse (observabilité LLM sur http://127.0.0.1:3000)
docker compose --profile observability up --build -d
```

### 3. Tester via HTTP (même sans bot Discord)
```bash
# Vérifier la santé
curl http://127.0.0.1:8000/health

# Demander un tri + envoi (va déclencher une pause HITL !)
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "demo-1", "message": "Lis mes mails non lus et envoie une réponse au recruteur pour confirmer mardi 14h"}'

# Valider l'action en attente
curl -X POST http://127.0.0.1:8000/approvals/demo-1 \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
```

---

## Développement local (sans Docker)

```bash
uv sync --extra dev
uv run ruff check src tests
uv run pytest -v
```

---

## Passer aux vraies APIs (Gmail, Google Calendar, Notion via MCP)

1. Crée un projet Google Cloud (gratuit), active **Gmail API** et **Google Calendar API**, télécharge tes identifiants OAuth dans `secrets/google_credentials.json`.
2. Crée une intégration interne sur [Notion Developers](https://www.notion.so/my-integrations), partage ta base de tâches avec elle, et ajoute `NOTION_API_KEY` dans `.env`.
3. Active les serveurs souhaités (`enabled: true`) dans `config/mcp_servers.yaml` et passe `MOCK_TOOLS=false` dans `.env`.
   - *Astuce DevOps* : en production Docker, privilégie des conteneurs sidecars MCP exposés en `streamable_http` sur le réseau interne `nexus-net` plutôt que `npx` dans le conteneur Python.

---

## Structure du projet

```text
nexus-agents/
├── config/
│   ├── litellm_config.yaml      # Routage LLM hybride & fallbacks
│   └── mcp_servers.yaml         # Registre déclaratif des serveurs MCP
├── docker/postgres/init.sql     # Création DB Langfuse + extension pgvector
├── src/nexus/
│   ├── config.py                # Configuration typée (Pydantic Settings)
│   ├── llm.py                   # Factory LiteLLM + Langfuse callbacks
│   ├── runtime.py               # Exécution LangGraph + gestion interrupt/resume
│   ├── mcp/registry.py          # Chargeur MCP + outils mock pour dev local
│   ├── graph/
│   │   ├── state.py             # État partagé LangGraph
│   │   ├── hitl.py              # Politique d'autonomie + wrapper interrupt()
│   │   ├── supervisor.py        # Nœud Supervisor avec routage structuré
│   │   ├── builder.py           # Compilation StateGraph + PostgresSaver
│   │   └── agents/              # Sous-agents Gmail & Productivité (Calendar/Notion)
│   ├── interfaces/
│   │   ├── discord_bot.py       # Bot Discord (#command-center + boutons HITL)
│   │   └── api.py               # FastAPI (/health, /metrics, /chat, /approvals)
│   └── scheduler/jobs.py        # Jobs proactifs APScheduler (briefing, triage)
├── tests/test_hitl_policy.py    # Tests unitaires HITL
├── Dockerfile                   # Multi-stage uv, non-root, HEALTHCHECK
├── docker-compose.yml           # Postgres pgvector + LiteLLM + Nexus + Langfuse
└── .github/workflows/ci.yml     # CI GitHub Actions (ruff, pytest, docker build)
```
