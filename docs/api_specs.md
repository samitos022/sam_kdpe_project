# API Specifications

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs` (Swagger UI)

---

## Health

### `GET /`
Returns overall application status.

**Response**
```json
{
  "status": "ok",
  "neo4j": true,
  "sessions": 2,
  "domains": ["aita", "wikipedia_history"]
}
```

### `GET /health`
```json
{ "api": "ok", "neo4j": true }
```

---

## Sessions — HITL Schema Refinement

All session endpoints are prefixed with `/sessions`.

### `POST /sessions/create`
Create a new HITL session. Loads documents, runs zero-shot schema discovery on the 10% sample, and returns schema v0.

> This is the most expensive call (~10–30 s depending on LLM latency).

**Request body**
```json
{
  "domain": "aita",
  "discovery_fraction": 0.1,
  "log_dir": "logs/schemas"
}
```
`domain` must be `"aita"` or `"wikipedia_history"`.

**Response**
```json
{
  "session_id": "a1b2c3d4",
  "domain": "aita",
  "schema": { "version": 0, "entity_classes": [...], "relation_types": [...] },
  "n_discovery_docs": 50,
  "n_validation_docs": 450,
  "message": "Session created. Discovered schema v0 with 7 classes and 9 relation types ..."
}
```

---

### `GET /sessions/{session_id}`
Get the current state of a session.

**Response**
```json
{
  "session_id": "a1b2c3d4",
  "domain": "aita",
  "schema": { ... },
  "schema_version": 3,
  "delta_history": [2.0, 1.5, 0.5],
  "converged": false,
  "frozen": false,
  "n_discovery_docs": 50,
  "n_validation_docs": 450,
  "extract_status": { "status": "not_started", "processed": 0, "total": 0 },
  "n_turns": 6
}
```

---

### `POST /sessions/{session_id}/chat`
Submit one HITL refinement turn. The LLM translates the natural language request into atomic schema edits (add/remove/rename/merge class or relation) and applies them.

**Request body**
```json
{ "message": "merge Boyfriend and Husband into Partner" }
```

**Response**
```json
{
  "schema": { "version": 4, ... },
  "schema_version": 4,
  "explanation": "Merged Boyfriend and Husband into Partner ...",
  "edits_applied": [
    { "edit_type": "merge_classes", "target": "Boyfriend", "value": "Partner", "reason": "..." },
    { "edit_type": "merge_classes", "target": "Husband",   "value": "Partner", "reason": "..." }
  ],
  "delta_s": 4.0,
  "questions": [],
  "converged": false,
  "summary": { "n_classes": 6, "n_relations": 8, ... }
}
```

Returns `409` if the schema is already frozen.

---

### `POST /sessions/{session_id}/freeze`
Lock the schema for batch extraction. No further chat refinements are accepted after this call.

**Response**
```json
{
  "message": "Schema frozen. You can now run batch extraction.",
  "schema": { "version": 4, "frozen": true, ... },
  "schema_version": 4,
  "n_classes": 6,
  "n_relations": 8,
  "delta_history": [2.0, 1.5, 0.5, 0.2],
  "converged": true
}
```

Returns `409` if already frozen.

---

### `GET /sessions/{session_id}/history`
Full schema evolution log. Used for plotting the ΔS_t convergence curve.

**Response**
```json
{
  "session_id": "a1b2c3d4",
  "versions": [
    { "version": 0, "n_classes": 7, "n_relations": 9, "frozen": false, "created_at": "..." },
    { "version": 1, "n_classes": 8, "n_relations": 10, "frozen": false, "created_at": "..." }
  ],
  "delta_history": [2.0, 1.5, 0.5, 0.2],
  "converged": true,
  "convergence_turn": 4
}
```

---

## Extraction — Batch ABox

### `POST /sessions/{session_id}/extract`
Start background extraction on the validation corpus (90% of documents). Schema must be frozen first. Returns immediately — poll `/extract/status` for progress.

| Query param | Type | Default | Description |
|---|---|---|---|
| `max_docs` | int | — | Cap the number of documents to extract (useful for quick tests) |

**Response**
```json
{
  "message": "Extraction started in background.",
  "session_id": "a1b2c3d4",
  "total_documents": 450,
  "schema_version": 4,
  "capped": false,
  "poll_url": "/sessions/a1b2c3d4/extract/status"
}
```

Returns `409` if schema is not frozen or extraction is already running.

---

### `GET /sessions/{session_id}/extract/status`
Poll extraction progress.

**Response**
```json
{
  "status": "running",
  "processed": 120,
  "total": 450,
  "progress_pct": 26.7,
  "metrics": {
    "total_entities": 840,
    "total_relations": 1230,
    "total_unmapped": 14,
    "total_repairs": 6,
    "schema_drift_count": 3
  },
  "uir": 0.0167,
  "sdr": 0.025,
  "errors": []
}
```

`status` values: `not_started` | `running` | `done` | `failed`

Metric definitions:
- **UIR** (Unmapped Instance Rate) = unmapped entities / total entities extracted
- **SDR** (Schema Drift Rate) = documents where the LLM proposed a schema change / documents processed

---

## Graph — Neo4j Queries

All graph endpoints require `?session_id=` to scope results to one extraction run. Returns `503` if Neo4j is not connected.

### `GET /graph/nodes`
| Query param | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | required | |
| `class_name` | string | — | Filter by entity class |
| `limit` | int | 200 | Max 1000 |

**Response**
```json
{ "nodes": [{ "id": "plant_chamomile", "name": "chamomile", "class_name": "Plant" }], "count": 1 }
```

---

### `GET /graph/edges`
| Query param | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | required | |
| `predicate` | string | — | Filter by relation type |
| `limit` | int | 500 | Max 2000 |

**Response**
```json
{ "edges": [{ "subject_id": "...", "predicate": "treats", "object_id": "..." }], "count": 1 }
```

---

### `GET /graph/search`
Case-insensitive substring search on node names.

| Query param | Type | Description |
|---|---|---|
| `session_id` | string | required |
| `q` | string | Search term (min 2 chars) |
| `limit` | int | Max 100, default 20 |

---

### `GET /graph/stats`
Raw graph statistics — inputs for evaluation metrics A1–A4.

**Response**
```json
{
  "n_nodes": 3200,
  "n_edges": 5400,
  "class_counts": { "Plant": 420, "Symptom": 310 },
  "relation_counts": { "TREATS": 890, "CAUSES": 210 },
  "relation_entropy": 2.31,
  "orphan_rate": 0.04,
  "orphan_count": 128
}
```

---

### `GET /graph/schema_utilization`
Compute Schema Utilization Rate (Metric A1) for a completed extraction. Schema must be frozen.

**Response**
```json
{
  "session_id": "a1b2c3d4",
  "schema_version": 4,
  "sur": 0.8333,
  "n_schema_classes": 6,
  "n_populated_classes": 5,
  "populated_classes": { "Plant": 420, "Symptom": 310, ... },
  "unpopulated_classes": ["Researcher"],
  "relation_sur": 0.875,
  "n_schema_relations": 8,
  "n_populated_relations": 7,
  "unpopulated_relations": ["co_occurs_with"],
  "relation_entropy": 2.31,
  "orphan_rate": 0.04,
  "orphan_count": 128,
  "total_nodes": 3200,
  "total_edges": 5400
}
```

---

## Error format

All errors follow FastAPI's standard format:
```json
{ "detail": "Session 'xyz' not found." }
```

Common HTTP codes:
- `404` — session or data file not found
- `409` — conflict (schema already frozen / extraction already running)
- `500` — LLM call or internal failure
- `503` — Neo4j not connected
