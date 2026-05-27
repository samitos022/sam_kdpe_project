# System Architecture

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite + TypeScript + TailwindCSS v4 + D3.js |
| Backend | FastAPI (Python 3.11) + Uvicorn |
| LLM Engine | LiteLLM (multi-provider) + Pydantic v2 |
| Graph DB | Neo4j 5 |
| Containerisation | Docker + Docker Compose |

---

## Directory Structure

```
sam_kdpe_project/
├── code/
│   ├── backend/
│   │   ├── app.py               # FastAPI entry point, session store, document loader
│   │   ├── routes/
│   │   │   ├── chat.py          # HITL session + schema refinement endpoints
│   │   │   ├── extraction.py    # Batch ABox extraction endpoints (supports ?max_docs=N)
│   │   │   └── graph_api.py     # Neo4j query endpoints
│   │   └── services/
│   │       └── neo4j_client.py  # Neo4j driver wrapper
│   ├── frontend/
│   │   └── src/
│   │       ├── api/client.ts    # Typed fetch wrappers for all backend endpoints
│   │       ├── pages/           # ChatPage, ExtractionPage, GraphPage, HomePage
│   │       ├── components/      # chat/, extraction/, graph/, schema/, ui/
│   │       └── hooks/           # useSession, useExtraction, useGraph
│   ├── llm_engine/
│   │   ├── core.py              # LLM flows: discover, refine, extract, qa_generate, judge
│   │   ├── parser.py            # Pydantic models: Schema, EntityClass, RelationType, ...
│   │   ├── prompts.py           # All prompt templates (system + user); compact schema format
│   │   ├── schema_manager.py    # Schema versioning, ΔS_t computation, convergence detection
│   │   ├── graphrag.py          # GraphRAG: keyword search → 1-hop neighborhood → LLM answer
│   │   └── plain_rag.py         # Plain-RAG: word-overlap retrieval → LLM answer (baseline)
│   ├── evaluation/
│   │   ├── qa_eval.py           # Block D: standalone QA evaluation script
│   │   ├── metrics.py           # Blocks A/B/C metric computation from logs
│   │   └── logger.py            # EvaluationLogger (session_summary.json writer)
│   ├── data/
│   │   ├── download_aita.py           # Reddit AITA scraper (≤2000 chars)
│   │   ├── download_wikipedia_history.py  # Wikipedia historical events (≤2000 chars)
│   │   └── processed/           # aita.jsonl, wikipedia_history.jsonl (gitignored)
│   ├── logs/
│   │   ├── run.log              # Rotating text log
│   │   ├── events.jsonl         # Structured JSONL events (one per LLM call / extraction)
│   │   ├── schemas/             # Per-session JSON: schema_v0.json, session.json, ...
│   │   └── eval/{session_id}/   # extraction_results.jsonl, qa_results.jsonl, qa_summary.json
│   ├── docker-compose.yml
│   ├── Dockerfile.backend
│   └── requirements.txt
└── docs/
```

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Browser                                                    │
│                                                             │
│  React Frontend (localhost:5173)                            │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────────────┐ │
│  │ ChatPage │  │ ExtractionPage│  │ GraphPage (D3 canvas)│ │
│  └────┬─────┘  └──────┬────────┘  └──────────┬───────────┘ │
│       │               │                       │             │
│       └───────────────┴───────────────────────┘             │
│                       │  fetch (VITE_API_URL)               │
└───────────────────────┼─────────────────────────────────────┘
                        │ HTTP / REST
┌───────────────────────▼─────────────────────────────────────┐
│  FastAPI Backend (localhost:8000)                           │
│                                                             │
│  /sessions/*    /graph/*                                    │
│  ┌────────────────────────────┐  ┌────────────────────────┐ │
│  │ chat.py                    │  │ graph_api.py           │ │
│  │ extraction.py              │  │ (read-only Cypher)     │ │
│  └───────────┬────────────────┘  └──────────┬─────────────┘ │
│              │                              │               │
│  ┌───────────▼────────────────┐             │               │
│  │ llm_engine/                │             │               │
│  │  core.py      prompts.py   │             │               │
│  │  parser.py    schema_manager│            │               │
│  └───────────┬────────────────┘             │               │
└──────────────┼───────────────────────────────┼──────────────┘
               │ LiteLLM (HTTP)                │ Bolt (7687)
               ▼                               ▼
      LLM Provider                    Neo4j 5 (localhost:7474/7687)
      (OpenAI / Anthropic /           └─> Nodes: EntityInstance
       local Ollama)                  └─> Edges: RelationInstance
                                      └─> Scoped by session_id property
```

---

## Session Lifecycle

```
POST /sessions/create
        │
        ▼
[1] Load domain JSONL → split 10% discovery / 90% validation
        │
        ▼
[2] discover_schema()  ←── LLM (zero-shot)  →  Schema v0
        │
        ▼  (loop)
[3] POST /sessions/{id}/chat  (user refinement message)
        │
        ├── refine_schema()  ←── LLM  →  LLMSchemaProposal (list of SchemaEdits)
        ├── SchemaManager.apply_proposal()  →  Schema v(n+1)
        └── Record ΔS_t;  check convergence (3 consecutive turns < ε=1.0)
        │
        ▼  (user satisfied)
[4] POST /sessions/{id}/freeze  →  Schema locked
        │
        ▼
[5] POST /sessions/{id}/extract  (background task)
        │
        ├── For each validation doc:
        │     extract_document()  ←── LLM  →  ExtractionResult
        │     GIV repair loop (up to 3 attempts if Pydantic validation fails)
        │     neo4j_client.write_extraction_result()
        │
        └── Poll GET /sessions/{id}/extract/status  →  { status, metrics }
        │
        ▼
[6] GET /graph/*  →  visualise + compute evaluation metrics (SUR, UIR, SDR, RTE, ONR)
```

---

## LLM Engine — Three Flows

### Flow 1 — Schema Discovery (`discover_schema`)
- Input: sample document texts + domain name
- Prompt: `DISCOVERY_SYSTEM` + `discovery_user()`
- Output: `Schema` (TBox) — validated by Pydantic; one repair pass if invalid

### Flow 2 — HITL Refinement (`refine_schema`)
- Input: current schema JSON + user message + last 4 turns of history
- Prompt: `REFINEMENT_SYSTEM` + `refinement_user()`
- Output: `LLMSchemaProposal` (ordered list of `SchemaEdit` objects)
- Edit types: `add_class`, `remove_class`, `rename_class`, `merge_classes`, `add_relation`, `remove_relation`, `rename_relation`, `update_description`

### Flow 3 — ABox Extraction with GIV loop (`extract_document`)
- Input: document text + frozen schema (compact format, ~244 tokens vs ~1916 for full JSON)
- Prompt: `EXTRACTION_SYSTEM` + `extraction_user()`
- Output: `ExtractionResult` (entities + relations + metric fields)
- GIV loop: if Pydantic validation fails → `REPAIR_SYSTEM` prompt → re-validate → repeat ×3
- `EXTRACTION_MAX_TOKENS = 1000` (vs 4096 default) — extraction output is compact JSON
- Separate `EXTRACTION_MODEL` env var allows routing extraction to a cheaper/faster model

### Flow 4 — QA Generation (`generate_qa_questions`)
- Input: document text, n questions
- Prompt: `QA_GENERATION_SYSTEM` + `qa_generation_user()`
- Output: list of factual questions (used by Block D eval)

### Flow 5 — LLM-as-Judge (`judge_qa_answer`)
- Input: question, system answer, source passage (first 1000 chars)
- Prompt: `QA_JUDGE_SYSTEM` + `qa_judge_user()`
- Output: `{"verdict": "YES"|"PARTIAL"|"NO", "reason": str}`

---

## Schema Versioning & Convergence (Metrics B1/B2)

`SchemaManager` tracks every schema version and computes:

- **ΔS_t** (edit distance per turn) = weighted sum of edit operations  
  Weights: `add/remove_class/relation = 1.0`, `rename = 0.5`, `merge = 2.0`, `update_description = 0.2`

- **Convergence T\*** = first turn where ΔS_t < ε (= 1.0) for 3 consecutive turns

Every schema version is persisted to `logs/schemas/{session_id}_schema_v{n}.json` for post-hoc analysis.

---

## Evaluation Metrics

| ID | Name | Formula | Source |
|---|---|---|---|
| A1 | Schema Utilization Rate (SUR) | classes with ≥1 instance / total classes | `/graph/schema_utilization` |
| A2 | Relation Type Entropy (RTE) | Shannon entropy of relation type distribution | `/graph/stats` |
| A3 | Schema Consistency Rate (SCR) | 1 − (validation errors / total triples), pre+post repair | `extraction_results.jsonl` |
| A4 | Orphan Node Rate (ONR) | nodes with no edges / total nodes | `/graph/stats` |
| B1 | Schema Edit Distance (ΔS_t) | weighted edit count per HITL turn | `schema_manager.delta_history()` |
| B2 | User Acceptance Rate (UAR) | proposals accepted as-is / total labelled turns | `/sessions/{id}/history` |
| C1 | Unmapped Instance Rate (UIR) | unmapped entities / total entities | `/sessions/{id}/extract/status` |
| C2 | Schema Drift Rate (SDR) | docs with drift proposal / docs processed | `/sessions/{id}/extract/status` |
| D1 | QA Accuracy / Δ | (YES + 0.5×PARTIAL) / total, vs Plain-RAG baseline | `evaluation/qa_eval.py` |
