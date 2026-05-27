"""
qa_eval.py — Block D: Downstream QA evaluation.

Compares three retrieval systems on the same factual questions:
  - Graph-HITL   : GraphRAG over the HITL knowledge graph
  - Graph-ZeroShot: GraphRAG over the Zero-Shot (v0) graph  [optional]
  - Plain-RAG    : word-overlap retrieval over raw document text

Two test sets per run:
  - top30 : 30 documents with the most extracted entities (richest in graph)
  - rand30 : 30 randomly sampled documents (unbiased)

Usage:
    python3 evaluation/qa_eval.py \\
        --session   <hitl_session_id> \\
        --domain    <aita|pubmed_ethnobotany> \\
        [--zeroshot-session <zeroshot_session_id>] \\
        [--questions-per-doc <n>]   # default 1

Output:
    logs/eval/<session_id>/qa_results.jsonl   ← one record per (doc, question, system)
    logs/eval/<session_id>/qa_summary.json    ← aggregated accuracy table
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

_CODE_DIR = Path(__file__).parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from dotenv import load_dotenv
load_dotenv()

from logging_config import get_logger, setup_logging
from llm_engine.core import generate_qa_questions, judge_qa_answer
from llm_engine.graphrag import answer_with_graph
from llm_engine.plain_rag import PlainRAG
from backend.services.neo4j_client import Neo4jClient

logger = get_logger(__name__)

# ─────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────

_DATA_DIR  = _CODE_DIR / "data" / "processed"
_EVAL_DIR  = _CODE_DIR / "logs" / "eval"

DOMAIN_TEXT_FIELDS = {
    "aita":              ["title", "text"],
    "wikipedia_history": ["title", "summary"],
}


# ─────────────────────────────────────────────
#  Document loading
# ─────────────────────────────────────────────

def load_corpus(domain: str) -> dict[str, dict]:
    """Load all documents keyed by their _id."""
    path = _DATA_DIR / f"{domain}.jsonl"
    docs: dict[str, dict] = {}
    fields = DOMAIN_TEXT_FIELDS.get(domain, ["body"])
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            parts = [str(rec.get(field, "")) for field in fields if rec.get(field)]
            rec["_text"] = "\n\n".join(parts)
            rec["_id"]   = rec.get("pmcid") or f"{domain}_{i}"
            docs[rec["_id"]] = rec
    return docs


def load_extraction_results(session_id: str) -> list[dict]:
    """Load per-document extraction results for a session."""
    path = _EVAL_DIR / session_id / "extraction_results.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"No extraction results found for session '{session_id}'.\n"
            f"Expected: {path}\n"
            "Run batch extraction first."
        )
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


# ─────────────────────────────────────────────
#  Document selection
# ─────────────────────────────────────────────

def select_test_sets(
    extraction_results: list[dict],
    corpus: dict[str, dict],
    n: int = 30,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (top_n, rand_n):
      - top_n : docs with the most extracted entities
      - rand_n: random sample from the remaining docs
    """
    # Keep only docs that exist in the corpus and had at least 1 entity
    valid = [
        r for r in extraction_results
        if r["doc_id"] in corpus and len(r.get("entities", [])) > 0
    ]
    if not valid:
        raise ValueError("No valid extraction results with entities found.")

    # Sort by entity count descending
    valid.sort(key=lambda r: len(r.get("entities", [])), reverse=True)

    top_ids  = {r["doc_id"] for r in valid[:n]}
    top_docs = [corpus[r["doc_id"]] for r in valid[:n]]

    # Random sample from the remaining
    remaining = [corpus[r["doc_id"]] for r in valid[n:] if r["doc_id"] in corpus]
    rng = random.Random(seed)
    rand_docs = rng.sample(remaining, min(n, len(remaining)))

    logger.info(
        "Test sets: top%d (min entities=%d), rand%d (from %d remaining)",
        len(top_docs),
        len(valid[len(top_docs)-1].get("entities", [])) if top_docs else 0,
        len(rand_docs),
        len(remaining),
    )
    return top_docs, rand_docs


# ─────────────────────────────────────────────
#  QA evaluation
# ─────────────────────────────────────────────

def run_qa_eval(
    session_id: str,
    domain: str,
    zeroshot_session_id: str | None,
    questions_per_doc: int,
    output_dir: Path,
    neo4j: Neo4jClient,
) -> dict:
    """
    Full Block D evaluation pipeline.

    Returns the summary dict (also written to disk).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "qa_results.jsonl"
    summary_path = output_dir / "qa_summary.json"

    # ── Load data ──────────────────────────────────────────────────────────────
    corpus = load_corpus(domain)
    extraction_results = load_extraction_results(session_id)
    top_docs, rand_docs = select_test_sets(extraction_results, corpus)

    # ── Build Plain-RAG index over full corpus ─────────────────────────────────
    plain_rag = PlainRAG(list(corpus.values()))

    # ── Determine which systems to run ─────────────────────────────────────────
    systems = ["hitl", "plain_rag"]
    if zeroshot_session_id:
        systems.insert(1, "zeroshot")

    # ── Tracking ───────────────────────────────────────────────────────────────
    counts: dict[str, dict[str, int]] = {
        split: {sys: {"yes": 0, "no": 0, "partial": 0, "total": 0}
                for sys in systems}
        for split in ["top30", "rand30"]
    }

    test_sets = [("top30", top_docs), ("rand30", rand_docs)]

    with open(results_path, "w") as out:
        for split_name, docs in test_sets:
            logger.info("=== Split: %s (%d docs) ===", split_name, len(docs))

            for doc in docs:
                doc_id = doc["_id"]
                text   = doc["_text"]

                # Generate questions for this doc
                questions = generate_qa_questions(text, n=questions_per_doc)
                if not questions:
                    logger.warning("No questions generated for doc=%s", doc_id)
                    continue

                for question in questions:
                    source_passage = text[:1000]

                    # Collect answers from all systems
                    answers: dict[str, str] = {}
                    answers["hitl"]      = answer_with_graph(question, session_id, neo4j)
                    answers["plain_rag"] = plain_rag.answer(question)
                    if zeroshot_session_id:
                        answers["zeroshot"] = answer_with_graph(
                            question, zeroshot_session_id, neo4j
                        )

                    # Judge each answer
                    verdicts: dict[str, dict] = {}
                    for sys_name, answer in answers.items():
                        verdict = judge_qa_answer(question, answer, source_passage)
                        verdicts[sys_name] = verdict
                        v = verdict.get("verdict", "NO").upper()
                        counts[split_name][sys_name]["total"] += 1
                        if v == "YES":
                            counts[split_name][sys_name]["yes"] += 1
                        elif v == "PARTIAL":
                            counts[split_name][sys_name]["partial"] += 1
                        else:
                            counts[split_name][sys_name]["no"] += 1

                    record = {
                        "ts":         datetime.now(timezone.utc).isoformat(),
                        "session_id": session_id,
                        "split":      split_name,
                        "doc_id":     doc_id,
                        "question":   question,
                        "answers":    answers,
                        "verdicts":   verdicts,
                    }
                    out.write(json.dumps(record) + "\n")

                    _log_progress(split_name, doc_id, question, answers, verdicts)

    # ── Build summary ──────────────────────────────────────────────────────────
    summary = _build_summary(counts, session_id, zeroshot_session_id, domain)
    summary_path.write_text(json.dumps(summary, indent=2))

    _print_summary_table(summary)
    return summary


# ─────────────────────────────────────────────
#  Summary helpers
# ─────────────────────────────────────────────

def _build_summary(
    counts: dict,
    session_id: str,
    zeroshot_session_id: str | None,
    domain: str,
) -> dict:
    summary: dict = {
        "session_id":          session_id,
        "zeroshot_session_id": zeroshot_session_id,
        "domain":              domain,
        "finalized_at":        datetime.now(timezone.utc).isoformat(),
        "results":             {},
    }

    for split, sys_counts in counts.items():
        summary["results"][split] = {}
        for sys_name, c in sys_counts.items():
            total = c["total"]
            if total == 0:
                continue
            yes_rate     = c["yes"] / total
            partial_rate = c["partial"] / total
            # Partial counts as 0.5 for the "accuracy" score
            accuracy     = (c["yes"] + 0.5 * c["partial"]) / total
            summary["results"][split][sys_name] = {
                "total":        total,
                "yes":          c["yes"],
                "partial":      c["partial"],
                "no":           c["no"],
                "yes_rate":     round(yes_rate, 4),
                "partial_rate": round(partial_rate, 4),
                "accuracy":     round(accuracy, 4),
            }

        # Delta: Graph-HITL vs Plain-RAG
        if "hitl" in summary["results"][split] and "plain_rag" in summary["results"][split]:
            delta = (
                summary["results"][split]["hitl"]["accuracy"]
                - summary["results"][split]["plain_rag"]["accuracy"]
            )
            summary["results"][split]["delta_hitl_vs_rag"] = round(delta, 4)

    return summary


def _log_progress(split, doc_id, question, answers, verdicts):
    verdicts_str = "  |  ".join(
        f"{sys}: {v.get('verdict','?')}"
        for sys, v in verdicts.items()
    )
    logger.info("[%s] doc=%s  Q: %s", split, doc_id, question[:60])
    logger.info("  Verdicts: %s", verdicts_str)


def _print_summary_table(summary: dict) -> None:
    print("\n" + "=" * 60)
    print(f"Block D QA Summary — session {summary['session_id']}")
    print("=" * 60)
    for split, systems in summary["results"].items():
        print(f"\n  [{split}]")
        print(f"  {'System':<20} {'Accuracy':>9} {'YES':>6} {'PARTIAL':>8} {'NO':>6} {'N':>5}")
        print(f"  {'-'*20} {'-'*9} {'-'*6} {'-'*8} {'-'*6} {'-'*5}")
        for sys_name, m in systems.items():
            if isinstance(m, dict) and "accuracy" in m:
                print(
                    f"  {sys_name:<20} {m['accuracy']:>9.1%} "
                    f"{m['yes']:>6} {m['partial']:>8} {m['no']:>6} {m['total']:>5}"
                )
        if "delta_hitl_vs_rag" in systems:
            delta = systems["delta_hitl_vs_rag"]
            sign  = "+" if delta >= 0 else ""
            print(f"\n  Δ HITL vs Plain-RAG: {sign}{delta:.1%}")
    print("=" * 60 + "\n")


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Block D — GraphRAG QA evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--session", required=True,
        help="HITL session ID (extraction must be complete)",
    )
    parser.add_argument(
        "--domain", required=True, choices=["aita", "wikipedia_history"],
        help="Dataset domain",
    )
    parser.add_argument(
        "--zeroshot-session", default=None,
        help="Optional: session ID of the Zero-Shot (v0 schema) baseline",
    )
    parser.add_argument(
        "--questions-per-doc", type=int, default=1,
        help="Questions to generate per document (default: 1)",
    )
    args = parser.parse_args()

    output_dir = _EVAL_DIR / args.session

    # Connect to Neo4j
    try:
        neo4j = Neo4jClient()
        if not neo4j.verify_connection():
            print("ERROR: Cannot connect to Neo4j. Is Docker running?", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Neo4j connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        summary = run_qa_eval(
            session_id          = args.session,
            domain              = args.domain,
            zeroshot_session_id = args.zeroshot_session,
            questions_per_doc   = args.questions_per_doc,
            output_dir          = output_dir,
            neo4j               = neo4j,
        )
    finally:
        neo4j.close()

    print(f"Results written to: {output_dir / 'qa_results.jsonl'}")
    print(f"Summary written to: {output_dir / 'qa_summary.json'}")


if __name__ == "__main__":
    main()
