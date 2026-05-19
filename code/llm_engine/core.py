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
from pathlib import Path

import litellm
from dotenv import load_dotenv
from pydantic import ValidationError

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

def _call_llm(system: str, user: str) -> str:
    """
    Single LLM call via LiteLLM. Returns the raw response text.

    LiteLLM routes to the correct provider based on the model string:
      'claude-sonnet-4-20250514'  → Anthropic API
      'gpt-4o'                    → OpenAI API
      'ollama/llama3'             → local Ollama
    The model is set in .env as LITELLM_MODEL — no code changes needed
    to switch providers during experimentation.
    """
    response = litellm.completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
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
) -> dict:
    """
    Call LLM and parse JSON. Retries if JSON is malformed (not if Pydantic fails).
    Pydantic failures are handled by the GIV repair loop, not here.
    """
    for attempt in range(retries + 1):
        raw = _call_llm(system, user)
        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            if attempt == retries:
                raise ValueError(
                    f"LLM returned invalid JSON after {retries} retries.\n"
                    f"Last response:\n{raw[:500]}\n"
                    f"Error: {e}"
                )
            # Append the error to the user prompt and retry
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

    data = _parse_json_with_retry(DISCOVERY_SYSTEM, user_prompt)

    # Validate with Pydantic — if the LLM produced an inconsistent schema
    # (e.g. relation referencing a non-existent class), this raises immediately.
    try:
        schema = Schema.model_validate(data)
    except ValidationError as e:
        # Attempt one repair pass for the schema itself
        errors = [str(err) for err in e.errors()]
        print(f"[core] Initial schema validation failed: {errors}")
        # Re-call with repair hint
        repair_hint = (
            f"Your schema had validation errors:\n"
            + "\n".join(f"  - {err}" for err in errors)
            + "\nPlease fix and return a valid schema."
        )
        data = _parse_json_with_retry(
            DISCOVERY_SYSTEM,
            user_prompt + "\n\n" + repair_hint,
        )
        schema = Schema.model_validate(data)

    schema = schema.model_copy(update={"domain": domain, "version": 0})
    manager.set_initial_schema(schema)
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
    output_format = json.dumps(LLMSchemaProposal.model_json_schema(), indent=2)

    user_prompt = refinement_user(
        current_schema_json=manager.current.model_dump_json(indent=2),
        user_message=user_message,
        output_schema_json=output_format,
        conversation_history=conversation_history,
    )

    data = _parse_json_with_retry(REFINEMENT_SYSTEM, user_prompt)

    try:
        proposal = LLMSchemaProposal.model_validate(data)
    except ValidationError as e:
        # If the proposal itself is malformed, return an empty proposal
        # (no changes) rather than crashing the session.
        print(f"[core] Proposal validation failed: {e}")
        proposal = LLMSchemaProposal(
            edits=[],
            explanation="I could not parse your request. Could you rephrase it?",
        )

    # Record the user turn first (no schema changes yet)
    manager.record_user_turn(turn_id=turn_id - 1, message=user_message)

    # Apply edits and record the assistant turn
    new_schema = manager.apply_proposal(proposal, turn_id=turn_id)

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

    output_format = json.dumps(ExtractionResult.model_json_schema(), indent=2)

    user_prompt = extraction_user(
        document=document,
        doc_id=doc_id,
        schema_json=schema.model_dump_json(indent=2),
        schema_version=schema.version,
        output_schema_json=output_format,
    )

    # ── First attempt ────────────────────────────────────────────────────────
    data = _parse_json_with_retry(EXTRACTION_SYSTEM, user_prompt)

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
                repaired_data = _parse_json_with_retry(REPAIR_SYSTEM, repair_prompt)
                result = ExtractionResult.model_validate(repaired_data)
                result = _validate_relation_ids(result)
                post_repair_errors = []
                break  # Repair succeeded

            except (ValidationError, ValueError) as repair_err:
                post_repair_errors = _collect_errors(repair_err)
                current_json = json.dumps(repaired_data if 'repaired_data' in dir() else data)

                if attempt == MAX_REPAIR_ATTEMPTS:
                    # Give up: return empty result with error log
                    print(
                        f"[core] GIV repair failed after {MAX_REPAIR_ATTEMPTS} attempts "
                        f"for doc {doc_id}. Errors: {post_repair_errors}"
                    )
                    result = ExtractionResult(
                        doc_id=doc_id,
                        schema_version=schema.version,
                    )

        result.validation_errors_pre_repair = pre_repair_errors
        result.validation_errors_post_repair = post_repair_errors
        result.repair_iterations = repair_iterations

    result.doc_id = doc_id
    result.schema_version = schema.version
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