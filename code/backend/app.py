"""
app.py — FastAPI application entry point.

Run with:
    cd code/
    uvicorn backend.app:app --reload --port 8000

Session store:
    Sessions are kept in a module-level dict.  Each entry holds the
    SchemaManager and extraction state for one HITL session.
    This is intentionally simple — for a research project, in-memory
    state is fine.  For production you'd use Redis.

Document loading:
    Documents are loaded lazily from the JSONL files in data/processed/.
    The corpus is split into discovery (10%) and validation (90%) at
    session creation time, using semantic clustering via sentence-transformers
    for diversity.  For simplicity, we use random sampling here and
    provide a hook to swap in the clustering approach.
"""

from __future__ import annotations

import json
import random
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Path setup ──────────────────────────────────────────────────────────────
# app.py is at code/backend/app.py
# llm_engine is at code/llm_engine/
# We add code/ to sys.path so both packages are importable.
_CODE_DIR = Path(__file__).parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from logging_config import setup_logging, get_logger
from backend.services.neo4j_client import Neo4jClient
from backend.routes import chat, extraction, graph_api

logger = get_logger(__name__)

# ─────────────────────────────────────────────
#  Global state
# ─────────────────────────────────────────────

# Session store: session_id → session dict
# Each session dict holds:
#   manager      : SchemaManager
#   discovery    : list[dict]   — 10% sample used for schema discovery
#   validation   : list[dict]   — 90% held out for batch extraction
#   domain       : str
#   extract_status: dict        — progress for background extraction
sessions: dict[str, dict[str, Any]] = {}

# Shared Neo4j client (one connection pool for the whole app)
neo4j: Neo4jClient | None = None


# ─────────────────────────────────────────────
#  Lifespan — startup / shutdown
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Code before 'yield' runs at startup; after 'yield' at shutdown.
    """
    global neo4j

    # Re-run logging setup here so our handlers are always the last ones
    # added — uvicorn calls dictConfig before loading the app, which can
    # wipe module-level handlers added during import.
    setup_logging()
    logger.info("Logging initialised", extra={"event": "logging_init"})

    # Startup: connect to Neo4j
    try:
        neo4j = Neo4jClient()
        if neo4j.verify_connection():
            logger.info("Neo4j connected", extra={"event": "neo4j_connected"})
        else:
            logger.warning("Neo4j connection failed — graph features disabled",
                           extra={"event": "neo4j_unavailable"})
            neo4j = None
    except Exception as e:
        logger.warning("Neo4j unavailable: %s — graph features disabled", e,
                       extra={"event": "neo4j_unavailable", "error": str(e)})
        neo4j = None

    yield  # app is running

    # Shutdown: close Neo4j
    if neo4j:
        neo4j.close()
        logger.info("Neo4j disconnected", extra={"event": "neo4j_disconnected"})


# ─────────────────────────────────────────────
#  App
# ─────────────────────────────────────────────

app = FastAPI(
    title="Conversational Graph Extraction API",
    description=(
        "HITL knowledge graph extraction from unstructured data. "
        "Schema is discovered through conversation, then used for batch extraction."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the frontend (Streamlit on 8501 or React on 5173) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",   # Streamlit
        "http://localhost:5173",   # React + Vite
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(chat.router,       prefix="/sessions",  tags=["HITL Chat"])
app.include_router(extraction.router, prefix="/sessions",  tags=["Extraction"])
app.include_router(graph_api.router,  prefix="/graph",     tags=["Graph"])


# ─────────────────────────────────────────────
#  Document loader
# ─────────────────────────────────────────────

_DATA_DIR = _CODE_DIR / "data" / "processed"

DOMAIN_FILES: dict[str, Path] = {
    "aita":               _DATA_DIR / "aita.jsonl",
    "wikipedia_history":  _DATA_DIR / "wikipedia_history.jsonl",
}

# Field names per domain (how to extract text from each JSONL record)
DOMAIN_TEXT_FIELDS: dict[str, list[str]] = {
    "aita":               ["title", "text"],
    "wikipedia_history":  ["title", "summary"],
}


def load_documents(domain: str) -> list[dict]:
    """Load all documents for a domain from the processed JSONL file."""
    path = DOMAIN_FILES.get(domain)
    if not path or not path.exists():
        raise FileNotFoundError(f"No data file for domain '{domain}': {path}")

    docs = []
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            # Build a single text field from the relevant fields
            fields = DOMAIN_TEXT_FIELDS.get(domain, ["body"])
            text_parts = [str(record.get(f, "")) for f in fields if record.get(f)]
            record["_text"] = "\n\n".join(text_parts)
            record["_id"] = record.get("pmcid") or f"{domain}_{i}"
            docs.append(record)
    return docs


def split_discovery_validation(
    docs: list[dict],
    discovery_fraction: float = 0.10,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """
    Split documents into discovery (10%) and validation (90%) sets.

    Uses random sampling with a fixed seed for reproducibility.
    In a more rigorous setup, replace this with semantic clustering
    (e.g. sentence-transformers + k-means) to maximize diversity
    of the discovery subset.
    """
    random.seed(seed)
    shuffled = docs.copy()
    random.shuffle(shuffled)

    n_discovery = max(5, int(len(shuffled) * discovery_fraction))
    return shuffled[:n_discovery], shuffled[n_discovery:]


# ─────────────────────────────────────────────
#  Root
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "ok",
        "neo4j": neo4j is not None,
        "sessions": len(sessions),
        "domains": list(DOMAIN_FILES.keys()),
    }


@app.get("/health")
async def health():
    return {
        "api": "ok",
        "neo4j": neo4j.verify_connection() if neo4j else False,
    }