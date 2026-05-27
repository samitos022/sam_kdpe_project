"""
graphrag.py — GraphRAG answer generation for Block D evaluation.

Given a natural language question and a Neo4j session graph, retrieves
the relevant subgraph context (1-hop neighborhood of matched entities)
and generates an answer via LLM.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from logging_config import get_logger
from llm_engine.core import _call_llm, MODEL

logger = get_logger(__name__)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "what", "which", "who", "whom", "how", "when", "where", "why",
    "that", "this", "these", "those", "it", "its", "they", "them", "their",
    "he", "she", "his", "her", "we", "our", "you", "your", "i", "me", "my",
    "did", "do", "get", "got", "use", "used",
}

_QA_SYSTEM = """\
You are answering a factual question using evidence from a knowledge graph.
The graph context shows entities and their typed relationships extracted from source documents.
Answer concisely and directly in 1-3 sentences.
If the graph context does not contain enough information, say exactly: "Not enough information in the graph."
Do not speculate beyond what the graph shows.
"""


def _search_terms(question: str) -> list[str]:
    """Extract meaningful tokens from a question for graph lookup."""
    tokens = re.findall(r"[a-zA-Z]+", question.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def answer_with_graph(
    question: str,
    session_id: str,
    neo4j,
    *,
    max_triples: int = 30,
) -> str:
    """
    Answer a question via GraphRAG over a Neo4j session.

    Strategy:
      1. Extract key terms from the question
      2. For each term, find nodes whose name contains it
      3. Retrieve their 1-hop neighborhood as typed triples
      4. Feed the context to the LLM

    Args:
        question:    Natural language question.
        session_id:  Extraction session to query.
        neo4j:       Neo4jClient instance.
        max_triples: Max triples to include in context (controls token count).

    Returns:
        LLM-generated answer string.
    """
    terms = _search_terms(question)
    if not terms:
        return "Not enough information in the graph."

    all_triples: list[str] = []

    for term in terms[:5]:
        with neo4j._driver.session() as s:
            rows = s.run(
                "MATCH (n {session_id: $sid})-[r]-(m) "
                "WHERE toLower(n.name) CONTAINS toLower($term) "
                "RETURN n.name AS src, labels(n)[0] AS src_class, "
                "       type(r) AS rel, m.name AS tgt, labels(m)[0] AS tgt_class "
                "LIMIT 10",
                sid=session_id,
                term=term,
            )
            for row in rows:
                rel_label = row["rel"].lower().replace("_", " ")
                triple = (
                    f"{row['src']} ({row['src_class']}) "
                    f"--[{rel_label}]--> "
                    f"{row['tgt']} ({row['tgt_class']})"
                )
                all_triples.append(triple)

    if not all_triples:
        logger.debug("graphrag: no triples found for question=%r session=%s", question, session_id)
        return "Not enough information in the graph."

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_triples = []
    for t in all_triples:
        if t not in seen:
            seen.add(t)
            unique_triples.append(t)

    context = "\n".join(f"  • {t}" for t in unique_triples[:max_triples])

    user_prompt = f"""\
Question: {question}

Knowledge graph context:
{context}

Answer the question using only the graph context above.
"""
    try:
        return _call_llm(_QA_SYSTEM, user_prompt, flow="graphrag", max_tokens=200)
    except Exception as e:
        logger.error("graphrag LLM call failed: %s", e)
        return "Error generating answer."
