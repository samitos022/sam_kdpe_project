"""
evaluation/logger.py — Structured per-session logging for post-hoc metric computation.

Artifacts written per session:
  logs/eval/{session_id}/
      extraction_results.jsonl   ← one ExtractionResult per doc  (A3, C1, C2)
      session_summary.json       ← aggregated metrics at end of extraction

Schema history (B1, B2) is already written by SchemaManager:
  logs/schemas/{session_id}_session.json   ← HITLSession with ΔS_t and UAR
  logs/schemas/{session_id}_schema_vN.json ← frozen TBox per version
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from llm_engine.parser import ExtractionResult, Schema
from evaluation.metrics import compute_extraction_metrics


class EvaluationLogger:
    """
    Lifecycle:
        logger = EvaluationLogger(session_id, eval_dir=Path("logs/eval"))
        # during batch extraction, once per document:
        logger.log_result(result)
        # when extraction is complete:
        summary = logger.finalize(frozen_schema)
    """

    def __init__(self, session_id: str, eval_dir: Path):
        self.session_id = session_id
        self.session_dir = eval_dir / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._results_path = self.session_dir / "extraction_results.jsonl"

    # ── Per-document ──────────────────────────────────────────────────────────

    def log_result(self, result: ExtractionResult) -> None:
        """Append one ExtractionResult to the JSONL log (one line per document)."""
        with open(self._results_path, "a") as f:
            f.write(result.model_dump_json() + "\n")

    # ── End of extraction ─────────────────────────────────────────────────────

    def finalize(self, schema: Schema) -> dict:
        """
        Read back all logged results, compute Block A3 / C1 / C2 metrics,
        and persist a session_summary.json.

        Returns the summary dict (same content as the written file).
        """
        results = self._load_results()
        metrics = compute_extraction_metrics(results, schema)

        summary = {
            "session_id":        self.session_id,
            "finalized_at":      datetime.now(timezone.utc).isoformat(),
            "n_documents":       len(results),
            "schema_version":    schema.version,
            "schema_n_classes":  len(schema.entity_classes),
            "schema_n_relations": len(schema.relation_types),
            **metrics,
        }

        path = self.session_dir / "session_summary.json"
        path.write_text(json.dumps(summary, indent=2))
        return summary

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_results(self) -> list[ExtractionResult]:
        if not self._results_path.exists():
            return []
        results = []
        with open(self._results_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(ExtractionResult.model_validate_json(line))
        return results

    def summary_path(self) -> Path:
        return self.session_dir / "session_summary.json"

    def load_summary(self) -> dict | None:
        p = self.summary_path()
        if not p.exists():
            return None
        return json.loads(p.read_text())
