"""
routes/extraction.py — Batch ABox extraction on the validation corpus.

Endpoints:
  POST /sessions/{id}/extract         Start background extraction
  GET  /sessions/{id}/extract/status  Poll extraction progress

Flow:
  1. Check schema is frozen
  2. Launch background task that iterates over validation_docs
  3. Each doc → extract_document() with GIV loop → write to Neo4j
  4. Track progress in session["extract_status"]
  5. Client polls /status until status == "done"

The background approach means the HTTP response is immediate (~100ms)
and the client polls for completion.  This is important because
extracting 450 documents can take 10-30 minutes depending on LLM latency.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

_CODE_DIR = Path(__file__).parent.parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from llm_engine.core import extract_document
from llm_engine.schema_manager import SchemaManager

import backend.app as _app

router = APIRouter()


# ─────────────────────────────────────────────
#  POST /sessions/{session_id}/extract
# ─────────────────────────────────────────────

@router.post("/{session_id}/extract")
async def start_extraction(
    session_id: str,
    background_tasks: BackgroundTasks,
):
    """
    Start batch extraction on the validation corpus (90% of documents).

    The schema must be frozen first (POST /sessions/{id}/freeze).
    Returns immediately with status 'started'.
    Poll GET /sessions/{id}/extract/status for progress.

    Metrics logged per document (saved to disk by SchemaManager):
      - repair_iterations   → for SCR computation
      - unmapped_entities   → for UIR computation
      - schema_modification_proposed → for SDR computation
    """
    session = _get_session(session_id)
    manager: SchemaManager = session["manager"]

    if not manager.current.frozen:
        raise HTTPException(
            status_code=409,
            detail="Schema must be frozen before extraction. POST /sessions/{id}/freeze first.",
        )

    status = session["extract_status"]
    if status["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Extraction is already running.",
        )

    validation_docs = session["validation"]
    if not validation_docs:
        raise HTTPException(
            status_code=400,
            detail="No validation documents available for this session.",
        )

    # Reset status
    session["extract_status"] = {
        "status":    "running",
        "processed": 0,
        "total":     len(validation_docs),
        "errors":    [],
        "metrics":   {
            "total_entities":   0,
            "total_relations":  0,
            "total_unmapped":   0,
            "total_repairs":    0,
            "schema_drift_count": 0,
        },
    }

    # Launch background task
    background_tasks.add_task(
        _run_extraction,
        session_id=session_id,
        validation_docs=validation_docs,
        manager=manager,
    )

    return {
        "message":          "Extraction started in background.",
        "session_id":       session_id,
        "total_documents":  len(validation_docs),
        "schema_version":   manager.version,
        "poll_url":         f"/sessions/{session_id}/extract/status",
    }


# ─────────────────────────────────────────────
#  GET /sessions/{session_id}/extract/status
# ─────────────────────────────────────────────

@router.get("/{session_id}/extract/status")
async def get_extraction_status(session_id: str):
    """
    Poll extraction progress.

    Returns:
      status:    'not_started' | 'running' | 'done' | 'failed'
      processed: number of documents completed
      total:     total documents to process
      metrics:   running totals for evaluation metrics
      errors:    list of doc_ids that failed after all repair attempts
    """
    session = _get_session(session_id)
    status = session["extract_status"]

    # Compute derived metrics
    processed = status["processed"]
    metrics = status.get("metrics", {})

    # UIR (Unmapped Instance Rate): unmapped / total entities extracted
    total_entities = metrics.get("total_entities", 0)
    total_unmapped = metrics.get("total_unmapped", 0)
    uir = total_unmapped / total_entities if total_entities > 0 else 0.0

    # SDR (Schema Drift Rate): drift proposals / docs processed
    drift = metrics.get("schema_drift_count", 0)
    sdr = drift / processed if processed > 0 else 0.0

    return {
        **status,
        "progress_pct": round(100 * processed / status["total"], 1) if status["total"] else 0,
        "uir":          round(uir, 4),
        "sdr":          round(sdr, 4),
    }


# ─────────────────────────────────────────────
#  Background task
# ─────────────────────────────────────────────

def _run_extraction(
    session_id: str,
    validation_docs: list[dict],
    manager: SchemaManager,
) -> None:
    """
    Background function: extract all validation documents and write to Neo4j.

    Runs synchronously in a thread pool (FastAPI handles this automatically
    for functions passed to BackgroundTasks).
    """
    session = _app.sessions.get(session_id)
    if not session:
        return

    status = session["extract_status"]
    frozen_schema = manager.current
    neo4j = _app.neo4j

    for doc in validation_docs:
        doc_id = doc["_id"]
        text   = doc["_text"]

        try:
            result = extract_document(
                document=text,
                doc_id=doc_id,
                schema=frozen_schema,
            )

            # Write to Neo4j if available
            if neo4j:
                neo4j.write_extraction_result(result, session_id=session_id)

            # Update running metrics
            m = status["metrics"]
            m["total_entities"]   += len(result.entities)
            m["total_relations"]  += len(result.relations)
            m["total_unmapped"]   += len(result.unmapped_entities)
            m["total_repairs"]    += result.repair_iterations
            if result.schema_modification_proposed:
                m["schema_drift_count"] += 1

        except Exception as e:
            status["errors"].append({"doc_id": doc_id, "error": str(e)})

        status["processed"] += 1

    status["status"] = "done"
    print(
        f"[extraction] Session {session_id} done. "
        f"Processed: {status['processed']}, "
        f"Errors: {len(status['errors'])}"
    )


# ─────────────────────────────────────────────
#  Helper
# ─────────────────────────────────────────────

def _get_session(session_id: str) -> dict:
    session = _app.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session