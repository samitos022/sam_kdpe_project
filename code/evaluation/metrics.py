"""
evaluation/metrics.py — Ground-truth-free metric computation from log files.

Computable purely from logs (no Neo4j, no live session):
  A1 — SUR   Schema Utilization Rate          (from extraction_results.jsonl + schema)
  A3 — SCR   Schema Consistency Rate          (from extraction_results.jsonl)
  C1 — UIR   Unmapped Instance Rate           (from extraction_results.jsonl)
  C2 — SDR   Schema Drift Rate                (from extraction_results.jsonl)
  B1 — ΔS_t  Schema edit distance per turn   (from {sid}_session.json)
  B2 — UAR   User Acceptance Rate             (from {sid}_session.json)

Metrics A2 (RTE) and A4 (ONR) require the live Neo4j graph and are computed
by graph_api.py → /graph/stats and /graph/schema_utilization.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from llm_engine.parser import ExtractionResult, Schema


# ─────────────────────────────────────────────
#  Block A3 / C1 / C2  —  from extraction logs
# ─────────────────────────────────────────────

def compute_extraction_metrics(
    results: list[ExtractionResult],
    schema: Schema,
) -> dict:
    """
    Compute A1 (SUR), A3 (SCR pre/post), C1 (UIR), C2 (SDR) from
    a list of ExtractionResult objects.

    Args:
        results: All ExtractionResult objects for one session.
        schema:  The frozen Schema (TBox) used for extraction.

    Returns a flat dict suitable for JSON serialization.
    """
    if not results:
        return _empty_extraction_metrics()

    total_entities      = sum(len(r.entities) for r in results)
    total_relations     = sum(len(r.relations) for r in results)
    total_unmapped      = sum(len(r.unmapped_entities) for r in results)
    total_repairs       = sum(r.repair_iterations for r in results)
    drift_count         = sum(1 for r in results if r.schema_modification_proposed)

    # A3 — SCR (pre-repair: errors before GIV loop; post-repair: errors that survived)
    total_triples       = total_entities + total_relations
    pre_repair_errors   = sum(len(r.validation_errors_pre_repair) for r in results)
    post_repair_errors  = sum(len(r.validation_errors_post_repair) for r in results)

    scr_pre  = 1.0 - (pre_repair_errors  / total_triples) if total_triples else 1.0
    scr_post = 1.0 - (post_repair_errors / total_triples) if total_triples else 1.0

    # C1 — UIR
    uir = total_unmapped / total_entities if total_entities else 0.0

    # C2 — SDR
    sdr = drift_count / len(results) if results else 0.0

    # A1 — SUR (from class_name distribution in extracted entities)
    schema_classes  = {c.name for c in schema.entity_classes}
    populated       = {e.class_name for r in results for e in r.entities} & schema_classes
    unpopulated     = schema_classes - populated
    sur             = len(populated) / len(schema_classes) if schema_classes else 0.0

    schema_relations = {r.name for r in schema.relation_types}
    used_relations   = {rel.predicate for res in results for rel in res.relations} & schema_relations
    unused_relations = schema_relations - used_relations
    rel_sur          = len(used_relations) / len(schema_relations) if schema_relations else 0.0

    # Per-document repair distribution (useful for reporting variance)
    repair_counts = [r.repair_iterations for r in results]
    mean_repairs  = _mean(repair_counts)
    std_repairs   = _std(repair_counts)

    return {
        # Counts
        "total_documents":       len(results),
        "total_entities":        total_entities,
        "total_relations":       total_relations,
        "total_triples":         total_triples,
        "total_unmapped":        total_unmapped,
        "total_repair_iterations": total_repairs,
        "schema_drift_count":    drift_count,

        # A1 — Schema Utilization Rate
        "sur":                   round(sur, 4),
        "n_schema_classes":      len(schema_classes),
        "n_populated_classes":   len(populated),
        "populated_classes":     sorted(populated),
        "unpopulated_classes":   sorted(unpopulated),
        "relation_sur":          round(rel_sur, 4),
        "n_schema_relations":    len(schema_relations),
        "n_populated_relations": len(used_relations),
        "unused_relations":      sorted(unused_relations),

        # A3 — Schema Consistency Rate
        "scr_pre_repair":        round(scr_pre, 4),
        "scr_post_repair":       round(scr_post, 4),
        "pre_repair_errors":     pre_repair_errors,
        "post_repair_errors":    post_repair_errors,
        "mean_repair_iterations": round(mean_repairs, 3),
        "std_repair_iterations":  round(std_repairs, 3),

        # C1 — Unmapped Instance Rate
        "uir":                   round(uir, 4),

        # C2 — Schema Drift Rate
        "sdr":                   round(sdr, 4),
    }


# ─────────────────────────────────────────────
#  Block B1 / B2  —  from HITLSession JSON
# ─────────────────────────────────────────────

def compute_convergence_metrics(session_data: dict) -> dict:
    """
    Compute B1 (ΔS_t series) and B2 (UAR) from a deserialized HITLSession dict.

    Args:
        session_data: Dict loaded from {session_id}_session.json

    Returns a flat dict with convergence metrics.
    """
    turns = session_data.get("turns", [])
    assistant_turns = [t for t in turns if t.get("role") == "assistant"]

    # B1 — ΔS_t series
    delta_series = [t["delta_s"] for t in assistant_turns if t.get("delta_s") is not None]
    convergence_turn = session_data.get("convergence_turn")
    converged = session_data.get("converged", False)

    # B2 — UAR
    acceptance_labels = [
        t.get("user_acceptance")
        for t in assistant_turns
        if t.get("user_acceptance") is not None
    ]
    n_proposals  = len(acceptance_labels)
    n_accepted   = acceptance_labels.count("accepted")
    n_modified   = acceptance_labels.count("modified")
    n_rejected   = acceptance_labels.count("rejected")
    uar = n_accepted / n_proposals if n_proposals else None

    return {
        # B1
        "n_turns":           len(assistant_turns),
        "delta_series":      delta_series,
        "delta_mean":        round(_mean(delta_series), 3) if delta_series else None,
        "delta_final":       delta_series[-1] if delta_series else None,
        "converged":         converged,
        "convergence_turn":  convergence_turn,

        # B2
        "n_proposals_with_acceptance_label": n_proposals,
        "uar":               round(uar, 4) if uar is not None else None,
        "n_accepted":        n_accepted,
        "n_modified":        n_modified,
        "n_rejected":        n_rejected,
    }


# ─────────────────────────────────────────────
#  Combined report loader
# ─────────────────────────────────────────────

def load_all_metrics(
    session_id: str,
    eval_dir: Path,
    schemas_dir: Path,
) -> dict:
    """
    Load and return all available metrics for a completed session.

    Reads:
      eval_dir/{session_id}/session_summary.json     → A1, A3, C1, C2
      schemas_dir/{session_id}_session.json           → B1, B2

    Metrics A2 (RTE) and A4 (ONR) are not included here — query Neo4j
    via GET /graph/stats instead.
    """
    report: dict = {"session_id": session_id}

    # A1, A3, C1, C2 — from extraction summary
    summary_path = eval_dir / session_id / "session_summary.json"
    if summary_path.exists():
        report["extraction"] = json.loads(summary_path.read_text())
    else:
        report["extraction"] = None

    # B1, B2 — from schema manager session log
    session_path = schemas_dir / f"{session_id}_session.json"
    if session_path.exists():
        session_data = json.loads(session_path.read_text())
        report["convergence"] = compute_convergence_metrics(session_data)
    else:
        report["convergence"] = None

    return report


# ─────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _empty_extraction_metrics() -> dict:
    return {
        "total_documents": 0, "total_entities": 0, "total_relations": 0,
        "total_triples": 0, "total_unmapped": 0, "total_repair_iterations": 0,
        "schema_drift_count": 0, "sur": 0.0, "n_schema_classes": 0,
        "n_populated_classes": 0, "populated_classes": [], "unpopulated_classes": [],
        "relation_sur": 0.0, "n_schema_relations": 0, "n_populated_relations": 0,
        "unused_relations": [], "scr_pre_repair": 1.0, "scr_post_repair": 1.0,
        "pre_repair_errors": 0, "post_repair_errors": 0,
        "mean_repair_iterations": 0.0, "std_repair_iterations": 0.0,
        "uir": 0.0, "sdr": 0.0,
    }
