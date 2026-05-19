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
│   │   │   ├── extraction.py    # Batch ABox extraction endpoints
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
│   │   ├── core.py              # Three LLM flows: discover, refine, extract
│   │   ├── parser.py            # Pydantic models: Schema, EntityClass, RelationType, ...
│   │   ├── prompts.py           # All prompt templates (system + user)
│   │   └── schema_manager.py   # Schema versioning, ΔS_t computation, convergence detection
│   ├── data/
│   │   └── processed/           # aita.jsonl, pubmed_ethnobotany.jsonl (gitignored)
│   ├── logs/
│   │   └── schemas/             # Per-session JSON: schema_v0.json, session.json, ...
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
- Input: document text + frozen schema
- Prompt: `EXTRACTION_SYSTEM` + `extraction_user()`
- Output: `ExtractionResult` (entities + relations + metric fields)
- GIV loop: if Pydantic validation fails → `REPAIR_SYSTEM` prompt → re-validate → repeat ×3

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
| A4 | Orphan Node Rate (ONR) | nodes with no edges / total nodes | `/graph/stats` |
| B1 | Schema Edit Distance (ΔS_t) | weighted edit count per HITL turn | `schema_manager.delta_history()` |
| B2 | Convergence Turn (T*) | first turn where ΔS_t < ε for 3 turns | `/sessions/{id}/history` |
| C1 | Unmapped Instance Rate (UIR) | unmapped entities / total entities | `/sessions/{id}/extract/status` |
| C2 | Schema Drift Rate (SDR) | docs with drift proposal / docs processed | `/sessions/{id}/extract/status` |
