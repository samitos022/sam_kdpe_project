"""
plain_rag.py — Plain-RAG baseline for Block D evaluation.

Retrieves the most relevant documents via word-overlap scoring (no graph),
then answers the question with an LLM using those chunks as context.
No external dependencies beyond the standard library.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from logging_config import get_logger
from llm_engine.core import _call_llm

logger = get_logger(__name__)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "what", "which", "who", "whom", "how", "when", "where", "why",
    "that", "this", "these", "those", "it", "its", "they", "them", "their",
    "he", "she", "his", "her", "we", "our", "you", "your", "i", "me", "my",
}

_QA_SYSTEM = """\
You are answering a factual question using text excerpts from source documents as context.
Answer concisely and directly in 1-3 sentences.
If the context does not contain enough information, say exactly: "Not enough information in the documents."
Do not speculate beyond what the context shows.
"""


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def _overlap_score(question_tokens: set[str], doc_text: str) -> float:
    """Jaccard-like overlap between question terms and document."""
    doc_tokens = _tokenize(doc_text)
    if not question_tokens:
        return 0.0
    return len(question_tokens & doc_tokens) / len(question_tokens)


class PlainRAG:
    """
    Lightweight Plain-RAG retriever over a fixed document corpus.

    Initialize once per evaluation run, then call answer() for each question.
    Uses word-overlap retrieval — no embeddings, no vector store needed.
    """

    def __init__(self, docs: list[dict], text_field: str = "_text") -> None:
        """
        Args:
            docs:       List of document dicts (each must have text_field).
            text_field: Key that holds the full document text.
        """
        self._docs = [d for d in docs if d.get(text_field)]
        self._texts = [d[text_field] for d in self._docs]
        logger.debug("PlainRAG indexed %d documents", len(self._docs))

    def retrieve(self, question: str, top_k: int = 3) -> list[str]:
        """Return the top-k most relevant document excerpts for a question."""
        q_tokens = _tokenize(question)
        scored = [
            (i, _overlap_score(q_tokens, text))
            for i, text in enumerate(self._texts)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [self._texts[i][:1200] for i, _ in scored[:top_k]]

    def answer(self, question: str, top_k: int = 3) -> str:
        """
        Retrieve relevant passages and generate an answer with the LLM.

        Args:
            question: Natural language question.
            top_k:    Number of passages to retrieve.

        Returns:
            LLM-generated answer string.
        """
        passages = self.retrieve(question, top_k=top_k)
        if not passages:
            return "Not enough information in the documents."

        context = "\n\n---\n\n".join(
            f"[Passage {i+1}]\n{p}" for i, p in enumerate(passages)
        )
        user_prompt = f"""\
Question: {question}

Relevant document passages:
{context}

Answer the question using only the passages above.
"""
        try:
            return _call_llm(_QA_SYSTEM, user_prompt, flow="plain_rag", max_tokens=200)
        except Exception as e:
            logger.error("plain_rag LLM call failed: %s", e)
            return "Error generating answer."
