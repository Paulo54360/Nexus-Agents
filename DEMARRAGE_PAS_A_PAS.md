# Guide Pas-à-Pas « Copier-Coller » — Nexus Agents

Tout est prêt dans ce dossier ! Suis simplement les étapes dans l'ordre : tu peux copier-coller chaque commande dans **PowerShell** (ou Terminal Windows).

---

## Étape 0 — Quoi installer sur ton PC Windows (pour tester en local)

Ouvre **PowerShell** et lance ces commandes `winget` (déjà intégré à Windows 10/11) :

```powershell
# 1. Obligatoire pour lancer toute la stack en 1 commande (Postgres + LiteLLM + Nexus + Langfuse)
winget install -e --id Docker.DockerDesktop

# 2. Git (versioning + GitHub Actions CI)
winget install -e --id Git.Git

# 3. uv (gestionnaire Python ultra-rapide pour lancer ruff / pytest en local sans Docker)
winget install -e --id astral-sh.uv

# 4. Optionnel (pour l'étape 4 — accès Zero-Trust à ton VPS depuis PC, Mac et téléphone)
winget install -e --id Tailscale.Tailscale

# 5. Optionnel (pour l'étape 4 — déployer le VPS en Infrastructure as Code)
winget install -e --id OpenTofu.Tofu
```

> **Important après l'installation de Docker Desktop** : lance l'application **Docker Desktop** et attends que l'icône en bas à gauche soit verte (*Engine running*). Si Windows te demande d'activer WSL 2, accepte et redémarre le PC.

---

## Étape 1 — Tester en local en 5 minutes (sans OAuth, 0 €)

Le fichier `.env` est déjà créé dans ce dossier avec `MOCK_TOOLS=true` (faux mails, faux agenda, fausses tâches Notion) pour tester **le vrai Supervisor LangGraph, le vrai LiteLLM et la vraie pause Human-in-the-Loop** immédiatement.

### 1.1 Récupérer une clé API gratuite (1 minute)
Choisis **au moins une** de ces 3 options gratuites :
- **Groq (ultra rapide, Llama 3.3 70B gratuit)** : https://console.groq.com/keys → colle dans `GROQ_API_KEY=`
- **Google Gemini API (Free Tier)** : https://aistudio.google.com/apikey → colle dans `GEMINI_API_KEY=`
- **GitHub Models (inclus avec ton GitHub Student)** : crée un Personal Access Token sur GitHub → colle dans `GITHUB_TOKEN=`

### 1.2 Remplir `.env` et démarrer la stack
Ouvre le fichier `.env` dans ce dossier, colle ta clé API gratuite, enregistre, puis dans PowerShell (dans ce dossier) :

```powershell
# Démarrer PostgreSQL (pgvector) + LiteLLM + Nexus
docker compose up --build -d

# Vérifier que tout tourne bien
docker compose ps
docker compose logs -f nexus
```
*(Appuie sur `Ctrl+C` pour quitter les logs — les conteneurs continuent de tourner.)*

### 1.3 Tester le multi-agents + la validation HITL
```powershell
.\scripts\test-hitl.ps1
```
Tu vas voir le Supervisor déléguer à l'Agent Gmail, lire les mails de test, **mettre le graphe en pause avant d'envoyer le mail**, et te demander `o/n` pour reprendre !

### 1.4 (Optionnel) Lancer les tests unitaires & le linter en local
```powershell
uv sync --extra dev
uv run ruff check src tests
uv run pytest -v
```

### 1.5 (Optionnel) Activer l'observabilité Langfuse en local
```powershell
docker compose --profile observability up -d
```
Ouvre ensuite **http://localhost:3000**, crée un compte local, génère une paire de clés API dans un projet Langfuse, colle `LANGFUSE_PUBLIC_KEY` et `LANGFUSE_SECRET_KEY` dans `.env`, puis relance `docker compose up -d nexus`. Chaque appel d'agent sera tracé (latence, étapes LangGraph, coûts).

---

## Étape 2 — Créer et brancher ton bot Discord privé (PC, Mac & Téléphone)

### 2.1 Créer ton serveur privé Discord
Crée un serveur Discord rien que pour toi avec ces salons textuels :
- `#command-center` (tu parles au Supervisor ici)
- `#briefing-matinal` (briefing auto à 08h00)
- `#gmail-triage` (tri périodique & brouillons Gmail)
- `#rappels` (relances tâches/mails)
- `#asso-digest` *(prêt pour la V2)*

### 2.2 Activer le mode développeur Discord & copier les IDs
1. Sur Discord : **Paramètres utilisateur → Avancés → Mode développeur (ON)**.
2. Clic droit sur ton profil → **Copier l'identifiant utilisateur** → colle dans `DISCORD_ALLOWED_USER_ID=`.
3. Clic droit sur chaque salon → **Copier l'identifiant du salon** → colle dans :
   - `DISCORD_COMMAND_CENTER_CHANNEL_ID=`
   - `DISCORD_BRIEFING_CHANNEL_ID=`
   - `DISCORD_GMAIL_TRIAGE_CHANNEL_ID=`
   - `DISCORD_REMINDERS_CHANNEL_ID=`

### 2.3 Créer le Bot sur le portail Discord
1. Va sur https://discord.com/developers/applications → **New Application** (`Nexus Agents`).
2. Onglet **Bot** :
   - Clique **Reset Token** → copie le token dans `DISCORD_BOT_TOKEN=` de ton `.env`.
   - Active **MESSAGE CONTENT INTENT** (indispensable !).
3. Onglet **OAuth2 → URL Generator** :
   - Scopes : coche `bot`.
   - Bot Permissions : coche `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`.
   - Ouvre l'URL générée et invite le bot sur ton serveur privé.

### 2.4 Redémarrer Nexus et tester depuis ton téléphone !
```powershell
docker compose up -d nexus
```
Envoie dans `#command-center` :
> *« Lis mes mails non lus, regarde mon agenda aujourd'hui et envoie un mail au recruteur pour confirmer mardi 14h »*

Tu verras apparaître une carte orange avec les boutons **✅ Valider** et **❌ Refuser** directement sur ton téléphone / PC / Mac !

---

## Étape 3 — Brancher tes vrais comptes Gmail, Google Calendar & Notion (MCP)

Une fois que tout te plaît en mode `MOCK_TOOLS=true` :

1. **Notion (2 min)** :
   - Va sur https://www.notion.so/my-integrations → **New integration** (`Nexus Agents`).
   - Copie le token (`ntn_...`) dans `NOTION_API_KEY=` de ton `.env`.
   - Ouvre ta page/base de tâches dans Notion → menu `...` en haut à droite → **Connexions** → ajoute `Nexus Agents`.
2. **Gmail & Google Calendar (5 min)** :
   - Va sur https://console.cloud.google.com/ → crée un projet `nexus-agents` (gratuit).
   - Active **Gmail API** et **Google Calendar API**.
   - **APIs & Services → OAuth consent screen** : mode *External*, ajoute ton propre email Gmail dans *Test users*.
   - **Credentials → Create Credentials → OAuth client ID (Desktop app)** → télécharge le JSON et place-le dans `secrets/google_credentials.json`.
3. **Activer les serveurs MCP** :
   - Dans `config/mcp_servers.yaml`, passe `enabled: true` sur `gmail`, `google_calendar` et `notion`.
   - Dans `.env`, passe `MOCK_TOOLS=false`.
   - *(Note Docker)* : si tu utilises des serveurs MCP `npx` à l'intérieur du conteneur, ajoute Node.js dans le `Dockerfile` ou lance-les en sidecars `streamable_http` dans `docker-compose.yml`.

---

## Étape 4 — Héberger 24h/24 sur le Cloud (0 € ou crédits GitHub Student)

Les fichiers Terraform / OpenTofu sont prêts dans `infra/` :
- **Option A — DigitalOcean (crédits 200 $ GitHub Student)** : `infra/digitalocean/`
- **Option B — Oracle Cloud Always Free (0 € à vie, 4 OCPU / 24 Go RAM)** : `infra/oracle/`

### 4.1 Générer une clé SSH (si tu n'en as pas déjà une)
```powershell
ssh-keygen -t ed25519 -C "nexus-devops"
```

### 4.2 Déployer le VPS en Infrastructure as Code (exemple DigitalOcean)
```powershell
cd infra\digitalocean
copy terraform.tfvars.example terraform.tfvars
# Édite terraform.tfvars avec ton token DigitalOcean (+ ta clé Tailscale si tu veux l'auto-join)

tofu init
tofu plan
tofu apply
```

### 4.3 Envoyer Nexus sur ton VPS (0 port exposé grâce à Tailscale)
1. Connecte-toi en SSH sur le VPS (`ssh deploy@<IP_DU_VPS>` ou `ssh deploy@nexus-vps` via Tailscale).
2. Clone ton repo GitHub dans `/opt/nexus-agents`, copie ton `.env` (jamais dans Git !) et tes `secrets/`, puis lance :
```bash
cd /opt/nexus-agents
docker compose --profile observability up --build -d
```
3. Depuis ton PC, ton Mac ou ton téléphone (avec l'app **Tailscale** active) :
   - **Discord** fonctionne partout automatiquement (WebSocket sortant, 0 port ouvert).
   - **Langfuse** est accessible en privé sur `http://nexus-vps:3000`.
   - **API / Metrics** sont accessibles en privé sur `http://nexus-vps:8000/metrics`.

### Bonus Ollama sur ton Mac (LLM 100 % local gratuit)
Si tu as un Mac Apple Silicon avec Tailscale :
1. Sur ton Mac : `OLLAMA_HOST=0.0.0.0 ollama serve` et `ollama pull qwen2.5:14b`.
2. Récupère l'IP Tailscale de ton Mac (`100.x.y.z`), mets `OLLAMA_API_BASE=http://100.x.y.z:11434` dans `.env`, et décommente le bloc `nexus-local` dans `config/litellm_config.yaml`. Quand ton Mac dort, LiteLLM bascule automatiquement sur `nexus-fast` !
