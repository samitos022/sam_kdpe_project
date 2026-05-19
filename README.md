# Knowledge Discovery and Pattern Extraction — Sam's Project

Conversational knowledge graph extraction from unstructured text.  
The user refines an ontology through chat (HITL); the system then extracts a full knowledge graph from the corpus and loads it into Neo4j.

---

## How to Run

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- An LLM API key (OpenAI, Anthropic, or any LiteLLM-compatible provider)

### 1. Clone

```bash
git clone https://github.com/samitos022/sam_kdpe_project.git
cd sam_kdpe_project
```

### 2. Configure environment

```bash
cp code/.env.example code/.env
```

Edit `code/.env` and set your keys:

```env
# LLM — pick one provider
LITELLM_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

# Neo4j (leave as-is for Docker)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# PubMed (only needed for the pubmed_ethnobotany domain)
ENTREZ_EMAIL=you@example.com

# Frontend
VITE_API_URL=http://localhost:8000
```

### 3. Add your data

Place processed JSONL files in `code/data/processed/`:

```
code/data/processed/
├── aita.jsonl
└── pubmed_ethnobotany.jsonl
```

Each line must be a JSON object. The backend reads `title` + `body` for AITA and `title` + `abstract` for PubMed.

### 4. Start everything

```bash
cd code
docker compose up -d
```

This starts three services:

| Service | URL | Description |
|---|---|---|
| Frontend | http://localhost:5173 | React UI |
| Backend API | http://localhost:8000 | FastAPI + Swagger docs at `/docs` |
| Neo4j | http://localhost:7474 | Browser UI (user: `neo4j`, pass: `password`) |

The backend waits for Neo4j to be healthy before starting.  
First build takes ~2–3 minutes (downloading images + installing dependencies).

### 5. Use the app

1. Open **http://localhost:5173**
2. Select a domain (`aita` or `pubmed_ethnobotany`) and create a session
3. Chat with the assistant to refine the schema
4. When satisfied, click **Freeze** to lock the schema
5. Start **Batch Extraction** — the backend processes all validation documents in the background
6. Visit the **Graph** page to visualise and explore the extracted knowledge graph

---

## Stopping

```bash
docker compose down          # stop containers, keep Neo4j data
docker compose down -v       # stop + delete Neo4j volume (wipes graph data)
```

---

## Development (without Docker)

**Backend**

```bash
cd code
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
```

**Frontend**

```bash
cd code/frontend
npm install
npm run dev
```

**Neo4j** still needs Docker (or a local installation):

```bash
docker compose up -d neo4j
```

---

## Project Structure

```
sam_kdpe_project/
├── code/
│   ├── backend/        FastAPI routes and Neo4j client
│   ├── frontend/       React + Vite UI
│   ├── llm_engine/     Schema discovery, HITL refinement, ABox extraction
│   ├── data/           Processed JSONL corpora (gitignored)
│   └── logs/           Per-session schema version logs (gitignored)
└── docs/
    ├── api_specs.md    Full REST API reference
    ├── architecture.md System design and component diagram
    └── evaluation.md   Evaluation plan and metrics
```
