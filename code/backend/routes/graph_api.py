"""
routes/graph_api.py — Neo4j graph query endpoints.

Endpoints:
  GET /graph/nodes              Paginated node list
  GET /graph/edges              Paginated edge list
  GET /graph/search             Full-text node search
  GET /graph/stats              Graph statistics (SUR, RTE, ONR inputs)
  GET /graph/schema_utilization Schema Utilization Rate (Metric A1)

All endpoints require ?session_id= to scope queries to one extraction run.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

_CODE_DIR = Path(__file__).parent.parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

import backend.app as _app

router = APIRouter()


# ─────────────────────────────────────────────
#  GET /graph/nodes
# ─────────────────────────────────────────────

@router.get("/nodes")
async def get_nodes(
    session_id: str = Query(..., description="Session ID from POST /sessions/create"),
    class_name: str | None = Query(None, description="Filter by entity class"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Return nodes for the frontend graph visualizer."""
    _require_neo4j()
    _require_session(session_id)

    nodes = _app.neo4j.get_nodes(
        session_id=session_id,
        class_name=class_name,
        limit=limit,
    )
    return {"nodes": nodes, "count": len(nodes)}


# ─────────────────────────────────────────────
#  GET /graph/edges
# ─────────────────────────────────────────────

@router.get("/edges")
async def get_edges(
    session_id: str = Query(...),
    predicate: str | None = Query(None, description="Filter by relation type"),
    limit: int = Query(500, ge=1, le=2000),
):
    """Return edges for the frontend graph visualizer."""
    _require_neo4j()
    _require_session(session_id)

    edges = _app.neo4j.get_edges(
        session_id=session_id,
        predicate=predicate,
        limit=limit,
    )
    return {"edges": edges, "count": len(edges)}


# ─────────────────────────────────────────────
#  GET /graph/search
# ─────────────────────────────────────────────

@router.get("/search")
async def search_nodes(
    session_id: str = Query(...),
    q: str = Query(..., min_length=2, description="Search term"),
    limit: int = Query(20, ge=1, le=100),
):
    """Case-insensitive substring search on node names."""
    _require_neo4j()
    _require_session(session_id)

    results = _app.neo4j.search_nodes(
        session_id=session_id,
        query=q,
        limit=limit,
    )
    return {"results": results, "count": len(results), "query": q}


# ─────────────────────────────────────────────
#  GET /graph/stats
# ─────────────────────────────────────────────

@router.get("/stats")
async def get_graph_stats(session_id: str = Query(...)):
    """
    Raw graph statistics from Neo4j.

    Returns the inputs needed for evaluation Metrics A1-A4:
      class_counts    → SUR numerator (which classes got populated)
      relation_counts → RTE computation
      orphan_rate     → ONR (Metric A4)
      relation_entropy→ RTE (Metric A2)
    """
    _require_neo4j()
    _require_session(session_id)

    return _app.neo4j.get_stats(session_id=session_id)


# ─────────────────────────────────────────────
#  GET /graph/schema_utilization
# ─────────────────────────────────────────────

@router.get("/schema_utilization")
async def get_schema_utilization(session_id: str = Query(...)):
    """
    Compute Schema Utilization Rate (Metric A1) for a completed extraction.

    SUR = |{classes with at least 1 instance}| / |{all schema classes}|

    Also returns per-class population counts so you can see which classes
    were populated and which were never instantiated.
    """
    _require_neo4j()
    session = _require_session(session_id)
    manager = session["manager"]

    if not manager.current.frozen:
        raise HTTPException(
            status_code=409,
            detail="Schema must be frozen and extraction must be complete to compute SUR.",
        )

    stats = _app.neo4j.get_stats(session_id=session_id)
    class_counts = stats["class_counts"]

    schema_classes = [c.name for c in manager.current.entity_classes]
    populated = [c for c in schema_classes if class_counts.get(c, 0) > 0]
    unpopulated = [c for c in schema_classes if class_counts.get(c, 0) == 0]

    sur = len(populated) / len(schema_classes) if schema_classes else 0.0

    # Schema Relation Utilization (same idea for relations)
    schema_relations = [r.name for r in manager.current.relation_types]
    rel_counts_normalized = {
        r.upper().replace(" ", "_"): count
        for r, count in stats["relation_counts"].items()
    }
    populated_rels = [
        r for r in schema_relations
        if rel_counts_normalized.get(r.upper(), 0) > 0
    ]
    rel_sur = len(populated_rels) / len(schema_relations) if schema_relations else 0.0

    return {
        "session_id":          session_id,
        "schema_version":      manager.version,

        # Metric A1 — Schema Utilization Rate
        "sur":                 round(sur, 4),
        "n_schema_classes":    len(schema_classes),
        "n_populated_classes": len(populated),
        "populated_classes":   {c: class_counts.get(c, 0) for c in populated},
        "unpopulated_classes": unpopulated,

        # Relation utilization
        "relation_sur":            round(rel_sur, 4),
        "n_schema_relations":      len(schema_relations),
        "n_populated_relations":   len(populated_rels),
        "unpopulated_relations":   [r for r in schema_relations if r not in populated_rels],

        # Metric A2 — Relation Type Entropy
        "relation_entropy":    stats["relation_entropy"],

        # Metric A4 — Orphan Node Rate
        "orphan_rate":         stats["orphan_rate"],
        "orphan_count":        stats["orphan_count"],

        # Totals
        "total_nodes":         stats["n_nodes"],
        "total_edges":         stats["n_edges"],
    }


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _require_neo4j():
    if not _app.neo4j:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is not connected. Start docker-compose up first.",
        )


def _require_session(session_id: str) -> dict:
    session = _app.sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    return session