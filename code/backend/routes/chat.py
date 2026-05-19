"""
routes/chat.py — HITL session management and schema refinement.

Endpoints:
  POST /sessions/create          Create session, run discovery, return schema v0
  GET  /sessions/{id}            Get session state and current schema
  POST /sessions/{id}/chat       Send refinement message, get updated schema
  POST /sessions/{id}/freeze     Lock schema for batch extraction
  GET  /sessions/{id}/history    Get schema version history + ΔS_t series
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ── Path + imports ───────────────────────────────────────────────────────────
_CODE_DIR = Path(__file__).parent.parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from llm_engine.core import discover_schema, refine_schema
from llm_engine.schema_manager import SchemaManager

# Import session store from app (avoids circular imports by importing lazily)
import backend.app as _app

router = APIRouter()


# ─────────────────────────────────────────────
#  Request / Response models
# ─────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    domain: str                       # 'aita' or 'pubmed_ethnobotany'
    discovery_fraction: float = 0.10  # fraction of corpus used for schema discovery
    log_dir: str = "logs/schemas"     # where to persist schema versions


class ChatRequest(BaseModel):
    message: str                      # user's natural language request


class SessionResponse(BaseModel):
    session_id: str
    domain: str
    schema_version: int
    n_classes: int
    n_relations: int
    converged: bool
    frozen: bool
    n_discovery_docs: int
    n_validation_docs: int


# ─────────────────────────────────────────────
#  POST /sessions/create
# ─────────────────────────────────────────────

@router.post("/create")
async def create_session(req: CreateSessionRequest):
    """
    Create a new HITL session.

    1. Load documents from data/processed/{domain}.jsonl
    2. Split into discovery (10%) and validation (90%)
    3. Call discover_schema() on the discovery subset → Schema v0
    4. Return the session_id and initial schema

    This is the most expensive endpoint (~10-30s depending on LLM latency).
    """
    # Load and split documents
    try:
        docs = _app.load_documents(req.domain)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    discovery_docs, validation_docs = _app.split_discovery_validation(
        docs, discovery_fraction=req.discovery_fraction
    )

    # Create SchemaManager for this session
    log_dir = Path(req.log_dir)
    manager = SchemaManager(domain=req.domain, log_dir=log_dir)
    session_id = manager.session_id

    # Store session state
    _app.sessions[session_id] = {
        "manager":        manager,
        "domain":         req.domain,
        "discovery":      discovery_docs,
        "validation":     validation_docs,
        "extract_status": {"status": "not_started", "processed": 0, "total": 0, "errors": []},
        "chat_history":   [],
    }

    # Run discovery on the 10% sample
    discovery_texts = [d["_text"] for d in discovery_docs]
    try:
        schema = discover_schema(
            documents=discovery_texts,
            domain=req.domain,
            manager=manager,
        )
    except Exception as e:
        # Clean up on failure
        del _app.sessions[session_id]
        raise HTTPException(status_code=500, detail=f"Schema discovery failed: {e}")

    return {
        "session_id":        session_id,
        "domain":            req.domain,
        "schema":            schema.model_dump(),
        "n_discovery_docs":  len(discovery_docs),
        "n_validation_docs": len(validation_docs),
        "message":           (
            f"Session created. Discovered schema v0 with "
            f"{len(schema.entity_classes)} classes and "
            f"{len(schema.relation_types)} relation types from "
            f"{len(discovery_docs)} documents. "
            f"Review the schema and refine it through chat."
        ),
    }


# ─────────────────────────────────────────────
#  GET /sessions/{session_id}
# ─────────────────────────────────────────────

@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get current session state, schema, and convergence status."""
    session = _get_session(session_id)
    manager: SchemaManager = session["manager"]

    return {
        "session_id":        session_id,
        "domain":            session["domain"],
        "schema":            manager.current.model_dump(),
        "schema_version":    manager.version,
        "delta_history":     manager.delta_history(),
        "converged":         manager.has_converged(),
        "frozen":            manager.current.frozen,
        "n_discovery_docs":  len(session["discovery"]),
        "n_validation_docs": len(session["validation"]),
        "extract_status":    session["extract_status"],
        "n_turns":           len(session["chat_history"]),
    }


# ─────────────────────────────────────────────
#  POST /sessions/{session_id}/chat
# ─────────────────────────────────────────────

@router.post("/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    """
    Process one HITL refinement turn.

    The user sends a natural language request (e.g. 'merge Boyfriend and
    Husband into Partner').  The LLM translates it into atomic schema edits.
    SchemaManager applies the edits and records ΔS_t.

    Returns the updated schema, the LLM's explanation, and the delta.
    """
    session = _get_session(session_id)
    manager: SchemaManager = session["manager"]

    if manager.current.frozen:
        raise HTTPException(
            status_code=409,
            detail="Schema is frozen. Start batch extraction or create a new session.",
        )

    history = session["chat_history"]
    turn_id = len(history) + 1

    try:
        new_schema, proposal = refine_schema(
            user_message=req.message,
            manager=manager,
            turn_id=turn_id,
            conversation_history=history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Refinement failed: {e}")

    # Update chat history
    history.append({"role": "user",      "message": req.message})
    history.append({"role": "assistant", "message": proposal.explanation})

    delta = manager.delta_history()[-1] if manager.delta_history() else 0.0

    return {
        "schema":          new_schema.model_dump(),
        "schema_version":  new_schema.version,
        "explanation":     proposal.explanation,
        "edits_applied":   [e.model_dump() for e in proposal.edits],
        "delta_s":         delta,
        "questions":       proposal.questions,
        "converged":       manager.has_converged(),
        "summary":         manager.summary(),
    }


# ─────────────────────────────────────────────
#  POST /sessions/{session_id}/freeze
# ─────────────────────────────────────────────

@router.post("/{session_id}/freeze")
async def freeze_schema(session_id: str):
    """
    Lock the current schema for batch extraction.

    After freezing:
      - No more chat refinements are accepted
      - POST /sessions/{id}/extract becomes available
      - The frozen schema is logged to disk
    """
    session = _get_session(session_id)
    manager: SchemaManager = session["manager"]

    if manager.current.frozen:
        raise HTTPException(status_code=409, detail="Schema is already frozen.")

    frozen_schema = manager.freeze()

    return {
        "message":         "Schema frozen. You can now run batch extraction.",
        "schema":          frozen_schema.model_dump(),
        "schema_version":  frozen_schema.version,
        "n_classes":       len(frozen_schema.entity_classes),
        "n_relations":     len(frozen_schema.relation_types),
        "delta_history":   manager.delta_history(),
        "converged":       manager.has_converged(),
    }


# ─────────────────────────────────────────────
#  GET /sessions/{session_id}/history
# ─────────────────────────────────────────────

@router.get("/{session_id}/history")
async def get_schema_history(session_id: str):
    """
    Return the full schema evolution history.

    Used for plotting the ΔS_t convergence curve (Metric B1)
    and for computing Schema Utilization Rate (Metric A1) post-extraction.
    """
    session = _get_session(session_id)
    manager: SchemaManager = session["manager"]

    # Load each schema version from disk
    versions = []
    for v in range(manager.version + 1):
        try:
            s = manager.load_schema_version(v)
            versions.append({
                "version":      s.version,
                "n_classes":    len(s.entity_classes),
                "n_relations":  len(s.relation_types),
                "frozen":       s.frozen,
                "created_at":   s.created_at.isoformat(),
            })
        except FileNotFoundError:
            pass

    return {
        "session_id":    session_id,
        "versions":      versions,
        "delta_history": manager.delta_history(),
        "converged":     manager.has_converged(),
        "convergence_turn": (
            next(
                (i + 3 for i, _ in enumerate(manager.delta_history()[2:])
                 if all(d < 1.0 for d in manager.delta_history()[i:i+3])),
                None,
            )
        ),
    }


# ─────────────────────────────────────────────
#  Helper
# ─────────────────────────────────────────────

def _get_session(session_id: str) -> dict:
    session = _app.sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    return session