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
LITELLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...

# Extraction model (optional — defaults to LITELLM_MODEL)
LITELLM_EXTRACTION_MODEL=openrouter/meta-llama/llama-3.1-8b-instruct

# Neo4j (leave as-is for Docker)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Frontend
VITE_API_URL=http://localhost:8000
```

### 3. Download and prepare data

```bash
cd code
# Reddit AITA posts (≤2000 chars combined title+text, ~500 posts)
../.venv/bin/python3 data/download_aita.py

# Wikipedia historical events (≤2000 chars combined title+summary, ~500 articles)
../.venv/bin/python3 data/download_wikipedia_history.py
```

Both scripts write to `code/data/processed/`:

```
code/data/processed/
├── aita.jsonl               # fields: title, text
└── wikipedia_history.jsonl  # fields: title, summary
```

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
2. Select a domain (`aita` or `wikipedia_history`) and create a session
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
│   ├── backend/          FastAPI routes and Neo4j client
│   ├── frontend/         React + Vite UI
│   ├── llm_engine/       Schema discovery, HITL refinement, extraction, GraphRAG, Plain-RAG
│   ├── evaluation/       Block D QA evaluation script (qa_eval.py)
│   ├── data/             Download scripts + processed JSONL corpora (gitignored)
│   └── logs/             Per-session schema logs and extraction results (gitignored)
└── docs/
    ├── api_specs.md        Full REST API reference
    ├── architecture.md     System design and component diagram
    ├── evaluation.md       Evaluation framework (presentation script)
    ├── evaluation_plan.md  Step-by-step metric computation guide
    └── block_d_qa_eval.md  Block D QA evaluation — how to run and interpret
```
