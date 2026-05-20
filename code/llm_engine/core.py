"""
core.py — LiteLLM integration and the three main LLM flows.

Flows:
  1. discover_schema()    Initial TBox from sample documents
  2. refine_schema()      One HITL refinement turn
  3. extract_document()   ABox extraction with GIV self-repair loop

The GIV (Guided Iterative Verification) loop:
  - Call LLM → parse JSON → validate with Pydantic
  - If validation fails → call repair prompt → re-validate
  - Repeat up to MAX_REPAIR_ATTEMPTS times
  - Log pre/post repair errors for SCR metric

All LLM calls go through _call_llm() which handles:
  - Model selection via LiteLLM (any provider: Anthropic, OpenAI, etc.)
  - Structured JSON output enforcement
  - Retry on malformed JSON (up to JSON_PARSE_RETRIES)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import litellm
from dotenv import load_dotenv
from pydantic import ValidationError

_CODE_DIR = Path(__file__).parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from logging_config import get_logger, setup_logging

from .parser import (
    ExtractionResult, LLMSchemaProposal, Schema,
)
from .prompts import (
    DISCOVERY_SYSTEM, EXTRACTION_SYSTEM, QA_GENERATION_SYSTEM,
    QA_JUDGE_SYSTEM, REFINEMENT_SYSTEM, REPAIR_SYSTEM,
    discovery_user, extraction_user, qa_generation_user,
    qa_judge_user, refinement_user, repair_user,
)
from .schema_manager import SchemaManager

load_dotenv()
setup_logging()
logger = get_logger(__name__)

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────

MODEL = os.getenv("LITELLM_MODEL", "claude-sonnet-4-20250514")
MAX_REPAIR_ATTEMPTS = 3       # GIV repair iterations before giving up
JSON_PARSE_RETRIES = 2        # Retries on pure JSON parse failure (not Pydantic)
TEMPERATURE = 0.2             # Low temperature for consistent structured output
MAX_TOKENS = 4096


# ─────────────────────────────────────────────
#  Low-level LLM caller
# ─────────────────────────────────────────────

def _call_llm(
    system: str,
    user: str,
    *,
    flow: str = "unknown",
    session_id: str | None = None,
    doc_id: str | None = None,
) -> str:
    """
    Single LLM call via LiteLLM. Returns the raw response text.

    LiteLLM routes to the correct provider based on the model string:
      'claude-sonnet-4-20250514'  → Anthropic API
      'gpt-4o'                    → OpenAI API
      'ollama/llama3'             → local Ollama
    The model is set in .env as LITELLM_MODEL — no code changes needed
    to switch providers during experimentation.

    Every call is logged as a structured event with timing + token counts.
    """
    t0 = time.perf_counter()
    response = litellm.completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    latency = round(time.perf_counter() - t0, 3)

    usage = getattr(response, "usage", None)
    prompt_tokens    = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)

    logger.info(
        "llm_call flow=%s latency=%.2fs model=%s",
        flow, latency, MODEL,
        extra={
            "event":             "llm_call",
            "flow":              flow,
            "model":             MODEL,
            "latency_s":         latency,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "session_id":        session_id,
            "doc_id":            doc_id,
        },
    )

    return response.choices[0].message.content or ""


def _extract_json(text: str) -> str:
    """
    Extract a JSON object from LLM output.
    LLMs sometimes wrap JSON in markdown code blocks (```json ... ```)
    even when asked not to.  This strips those wrappers.
    """
    # Try to extract from ```json ... ``` block
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1).strip()
    # Otherwise assume the entire response is JSON
    return text.strip()


def _parse_json_with_retry(
    system: str,
    user: str,
    retries: int = JSON_PARSE_RETRIES,
    *,
    flow: str = "unknown",
    session_id: str | None = None,
    doc_id: str | None = None,
) -> dict:
    """
    Call LLM and parse JSON. Retries if JSON is malformed (not if Pydantic fails).
    Pydantic failures are handled by the GIV repair loop, not here.
    """
    for attempt in range(retries + 1):
        raw = _call_llm(system, user, flow=flow, session_id=session_id, doc_id=doc_id)
        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            if attempt == retries:
                logger.warning(
                    "JSON parse failed after %d retries (flow=%s, doc=%s)",
                    retries, flow, doc_id,
                    extra={"event": "json_parse_failed", "flow": flow,
                           "doc_id": doc_id, "session_id": session_id},
                )
                raise ValueError(
                    f"LLM returned invalid JSON after {retries} retries.\n"
                    f"Last response:\n{raw[:500]}\n"
                    f"Error: {e}"
                )
            user = user + f"\n\nYour previous response was not valid JSON. Error: {e}\nPlease return ONLY a JSON object."


# ─────────────────────────────────────────────
#  Flow 1 — Schema Discovery
# ─────────────────────────────────────────────

def discover_schema(
    documents: list[str],
    domain: str,
    manager: SchemaManager,
) -> Schema:
    """
    Generate the initial TBox from a sample of documents.

    This is the zero-shot starting point (version 0).
    The user has not yet seen or approved this schema.

    Args:
        documents: Texts from the 10% discovery subset.
        domain:    'aita' or 'pubmed_ethnobotany'.
        manager:   SchemaManager to store the result.

    Returns:
        The initial Schema (version 0).
    """
    output_format = json.dumps(Schema.model_json_schema(), indent=2)

    user_prompt = discovery_user(
        documents=documents,
        domain=domain,
        output_schema_json=output_format,
    )

    sid = manager.session_id
    logger.info(
        "Starting schema discovery session=%s domain=%s n_docs=%d",
        sid, domain, len(documents),
        extra={"event": "discovery_start", "session_id": sid,
               "domain": domain, "n_docs": len(documents)},
    )
    t0 = time.perf_counter()

    data = _parse_json_with_retry(
        DISCOVERY_SYSTEM, user_prompt,
        flow="discovery", session_id=sid,
    )

    # Validate with Pydantic — if the LLM produced an inconsistent schema
    # (e.g. relation referencing a non-existent class), this raises immediately.
    try:
        schema = Schema.model_validate(data)
    except ValidationError as e:
        errors = [str(err) for err in e.errors()]
        logger.warning(
            "Initial schema validation failed, attempting repair (session=%s)", sid,
            extra={"event": "discovery_repair", "session_id": sid, "errors": errors},
        )
        repair_hint = (
            "Your schema had validation errors:\n"
            + "\n".join(f"  - {err}" for err in errors)
            + "\nPlease fix and return a valid schema."
        )
        data = _parse_json_with_retry(
            DISCOVERY_SYSTEM,
            user_prompt + "\n\n" + repair_hint,
            flow="discovery_repair", session_id=sid,
        )
        schema = Schema.model_validate(data)

    schema = schema.model_copy(update={"domain": domain, "version": 0})
    manager.set_initial_schema(schema)

    logger.info(
        "Discovery done session=%s n_classes=%d n_relations=%d duration=%.1fs",
        sid, len(schema.entity_classes), len(schema.relation_types),
        time.perf_counter() - t0,
        extra={
            "event":       "discovery_done",
            "session_id":  sid,
            "domain":      domain,
            "n_classes":   len(schema.entity_classes),
            "n_relations": len(schema.relation_types),
            "duration_s":  round(time.perf_counter() - t0, 2),
        },
    )
    return schema


# ─────────────────────────────────────────────
#  Flow 2 — HITL Refinement
# ─────────────────────────────────────────────

def refine_schema(
    user_message: str,
    manager: SchemaManager,
    turn_id: int,
    conversation_history: list[dict] | None = None,
) -> tuple[Schema, LLMSchemaProposal]:
    """
    Process one user refinement message and produce an updated schema.

    The LLM receives the current schema and the user message, and returns
    a LLMSchemaProposal (list of atomic edits + explanation).
    SchemaManager applies the edits and increments the version.

    Args:
        user_message:          What the user typed in the chat.
        manager:               SchemaManager holding the current schema.
        turn_id:               Sequential turn number.
        conversation_history:  Previous turns for context.

    Returns:
        (new_schema, proposal) — the updated schema and the edits that were applied.
    """
    sid = manager.session_id
    output_format = json.dumps(LLMSchemaProposal.model_json_schema(), indent=2)

    user_prompt = refinement_user(
        current_schema_json=manager.current.model_dump_json(indent=2),
        user_message=user_message,
        output_schema_json=output_format,
        conversation_history=conversation_history,
    )

    data = _parse_json_with_retry(
        REFINEMENT_SYSTEM, user_prompt,
        flow="refinement", session_id=sid,
    )

    try:
        proposal = LLMSchemaProposal.model_validate(data)
    except ValidationError as e:
        logger.warning(
            "Proposal validation failed (session=%s turn=%d): %s", sid, turn_id, e,
            extra={"event": "refinement_parse_failed", "session_id": sid, "turn_id": turn_id},
        )
        proposal = LLMSchemaProposal(
            edits=[],
            explanation="I could not parse your request. Could you rephrase it?",
        )

    # Infer whether the user's message accepts, modifies, or rejects the
    # previous LLM proposal — used to populate UAR (Metric B2).
    acceptance = _infer_acceptance(user_message)

    # Record the user turn first (no schema changes yet)
    manager.record_user_turn(turn_id=turn_id - 1, message=user_message, acceptance=acceptance)

    # Apply edits and record the assistant turn
    new_schema = manager.apply_proposal(proposal, turn_id=turn_id)

    logger.info(
        "Refinement turn=%d session=%s delta=%.1f acceptance=%s n_edits=%d",
        turn_id, sid,
        manager.delta_history()[-1] if manager.delta_history() else 0.0,
        acceptance,
        len(proposal.edits),
        extra={
            "event":       "refinement_turn",
            "session_id":  sid,
            "turn_id":     turn_id,
            "n_edits":     len(proposal.edits),
            "delta_s":     manager.delta_history()[-1] if manager.delta_history() else 0.0,
            "acceptance":  acceptance,
            "converged":   manager.has_converged(),
        },
    )

    return new_schema, proposal


# ─────────────────────────────────────────────
#  Flow 3 — ABox Extraction with GIV loop
# ─────────────────────────────────────────────

def extract_document(
    document: str,
    doc_id: str,
    schema: Schema,
) -> ExtractionResult:
    """
    Extract entities and relations from one document using the frozen schema.

    Implements the GIV (Guided Iterative Verification) loop:
      1. Call LLM → parse JSON → validate with Pydantic
      2. If validation fails → log errors → call repair prompt
      3. Repeat up to MAX_REPAIR_ATTEMPTS
      4. Return result with repair metadata for SCR/UIR metrics.

    Args:
        document: Full text of the document.
        doc_id:   Unique identifier for this document.
        schema:   The frozen Schema (TBox) to extract against.

    Returns:
        ExtractionResult with entities, relations, and metric logging fields.
    """
    if not schema.frozen:
        raise RuntimeError(
            "Schema must be frozen before batch extraction. Call manager.freeze() first."
        )

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    output_format = json.dumps(ExtractionResult.model_json_schema(), indent=2)

    user_prompt = extraction_user(
        document=document,
        doc_id=doc_id,
        schema_json=schema.model_dump_json(indent=2),
        schema_version=schema.version,
        output_schema_json=output_format,
    )

    # ── First attempt ────────────────────────────────────────────────────────
    data = _parse_json_with_retry(
        EXTRACTION_SYSTEM, user_prompt,
        flow="extract", doc_id=doc_id,
    )

    pre_repair_errors: list[str] = []
    post_repair_errors: list[str] = []
    repair_iterations = 0

    try:
        result = ExtractionResult.model_validate(data)
        # Extra semantic check: entity IDs referenced in relations must exist
        result = _validate_relation_ids(result)
        result.validation_errors_pre_repair = []
        result.schema_version = schema.version

    except (ValidationError, ValueError) as e:
        # ── GIV repair loop ──────────────────────────────────────────────────
        pre_repair_errors = _collect_errors(e)
        current_json = json.dumps(data)

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            repair_iterations += 1

            repair_prompt = repair_user(
                failed_json=current_json,
                validation_errors=pre_repair_errors if attempt == 1 else post_repair_errors,
                schema_json=schema.model_dump_json(indent=2),
                output_schema_json=output_format,
                attempt=attempt,
            )

            try:
                repaired_data = _parse_json_with_retry(
                    REPAIR_SYSTEM, repair_prompt,
                    flow="giv_repair", doc_id=doc_id,
                )
                result = ExtractionResult.model_validate(repaired_data)
                result = _validate_relation_ids(result)
                post_repair_errors = []
                break  # Repair succeeded

            except (ValidationError, ValueError) as repair_err:
                post_repair_errors = _collect_errors(repair_err)
                current_json = json.dumps(repaired_data if 'repaired_data' in dir() else data)

                if attempt == MAX_REPAIR_ATTEMPTS:
                    logger.warning(
                        "GIV repair gave up after %d attempts doc=%s errors=%s",
                        MAX_REPAIR_ATTEMPTS, doc_id, post_repair_errors,
                        extra={
                            "event":            "giv_repair_exhausted",
                            "doc_id":           doc_id,
                            "repair_attempts":  MAX_REPAIR_ATTEMPTS,
                            "final_errors":     post_repair_errors,
                        },
                    )
                    result = ExtractionResult(
                        doc_id=doc_id,
                        schema_version=schema.version,
                    )

        result.validation_errors_pre_repair = pre_repair_errors
        result.validation_errors_post_repair = post_repair_errors
        result.repair_iterations = repair_iterations

    duration = round(time.perf_counter() - t0, 3)
    result.doc_id = doc_id
    result.schema_version = schema.version
    result.extraction_started_at = started_at.isoformat()
    result.extraction_duration_s = duration

    logger.info(
        "Extracted doc=%s entities=%d relations=%d repairs=%d duration=%.2fs",
        doc_id,
        len(result.entities),
        len(result.relations),
        repair_iterations,
        duration,
        extra={
            "event":              "doc_extracted",
            "doc_id":             doc_id,
            "schema_version":     schema.version,
            "n_entities":         len(result.entities),
            "n_relations":        len(result.relations),
            "n_unmapped":         len(result.unmapped_entities),
            "repair_iterations":  repair_iterations,
            "pre_repair_errors":  len(pre_repair_errors),
            "post_repair_errors": len(post_repair_errors),
            "schema_drift":       result.schema_modification_proposed,
            "duration_s":         duration,
        },
    )

    return result


def _validate_relation_ids(result: ExtractionResult) -> ExtractionResult:
    """
    Semantic validation not covered by Pydantic:
    every relation's subject_id and object_id must reference an existing entity.
    Removes invalid relations and logs them.
    """
    valid_ids = {e.id for e in result.entities}
    valid_relations = []
    invalid = []

    for rel in result.relations:
        if rel.subject_id in valid_ids and rel.object_id in valid_ids:
            valid_relations.append(rel)
        else:
            invalid.append(
                f"Relation '{rel.predicate}' references unknown ID(s): "
                f"subject={rel.subject_id}, object={rel.object_id}"
            )

    result.relations = valid_relations
    result.validation_errors_post_repair.extend(invalid)
    return result


def _infer_acceptance(user_message: str) -> str | None:
    """
    Heuristic classifier for UAR (Metric B2).

    Inspects the user's message to label whether they accepted, modified,
    or rejected the previous LLM proposal.  Returns None when ambiguous.

    Rules (order matters — more specific first):
      "rejected"  — explicit negation words (no, non va, sbagliato, …)
      "accepted"  — acknowledgment-only message with no new instructions
      "modified"  — acknowledgment + additional instructions in same message
    """
    msg = user_message.strip().lower()

    # Tokenise first — all matching uses word tokens, not substring matching
    tokens = set(re.split(r"[\s,;.!?]+", msg)) - {""}

    _REJECT_TOKENS = {
        "no", "nope", "sbagliato", "wrong", "revert", "undo",
        "annulla", "ricomincia", "riparti", "restart",
    }
    _REJECT_PHRASES = {
        "non va", "non mi piace", "non va bene",
        "non è corretto", "not right",
    }
    _ACCEPT_TOKENS = {
        "ok", "sì", "si", "yes", "yep", "yeah", "perfetto", "bene",
        "ottimo", "esatto", "giusto", "corretto", "great", "perfect",
        "good", "approved", "accetto", "accept", "confermo", "conferma",
    }
    _ACCEPT_PHRASES = {
        "va bene", "va bene così", "ok così",
    }
    _STOPS = {
        "e", "a", "di", "il", "la", "le", "lo", "un", "una", "the",
        "and", "to", "of", "per", "in", "da", "del", "della", "dei",
        "ma", "però", "anche", "con", "but", "and",
    }

    # Check for explicit rejection (tokens first, then phrases)
    if tokens & _REJECT_TOKENS:
        return "rejected"
    for phrase in _REJECT_PHRASES:
        if phrase in msg:
            return "rejected"

    # Check for acceptance
    accept_hit = bool(tokens & _ACCEPT_TOKENS)
    if not accept_hit:
        for phrase in _ACCEPT_PHRASES:
            if phrase in msg:
                accept_hit = True
                break

    if not accept_hit:
        return None  # Ambiguous: pure instruction, no acceptance signal

    # Acceptance detected — does the message also carry new instructions?
    content_tokens = tokens - _ACCEPT_TOKENS - _STOPS
    has_instruction = len(content_tokens) > 2

    return "modified" if has_instruction else "accepted"


def _collect_errors(exc: ValidationError | ValueError) -> list[str]:
    if isinstance(exc, ValidationError):
        return [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


# ─────────────────────────────────────────────
#  Evaluation helpers (Block D)
# ─────────────────────────────────────────────

def generate_qa_questions(document: str, n: int = 5) -> list[str]:
    """Generate n factual questions from a document (for downstream QA eval)."""
    user_prompt = qa_generation_user(document, n)
    raw = _call_llm(QA_GENERATION_SYSTEM.format(n=n), user_prompt)
    try:
        questions = json.loads(_extract_json(raw))
        return [q for q in questions if isinstance(q, str)][:n]
    except Exception:
        return []


def judge_qa_answer(question: str, answer: str, source_passage: str) -> dict:
    """
    LLM-as-judge: evaluate a GraphRAG answer against the source text.
    Returns {'verdict': 'YES'|'NO'|'PARTIAL', 'reason': str}.
    """
    user_prompt = qa_judge_user(question, answer, source_passage)
    raw = _call_llm(QA_JUDGE_SYSTEM, user_prompt)
    try:
        return json.loads(_extract_json(raw))
    except Exception:
        return {"verdict": "NO", "reason": "Could not parse judge response."}