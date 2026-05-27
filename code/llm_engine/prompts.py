"""
prompts.py — All LLM prompt templates.

Design principles:
  1. Every prompt requests JSON output matching a specific Pydantic model.
     The JSON schema is injected at call time (not hardcoded here) so that
     it stays in sync with parser.py automatically.
  2. System prompts define the LLM's role and the output format.
     User prompts carry the actual data (documents, user messages, errors).
  3. Prompts are plain functions returning strings — no magic, easy to test.
"""

from __future__ import annotations


# ─────────────────────────────────────────────
#  Phase 1A — Initial schema discovery
#  Input:  sample documents + domain name
#  Output: Schema (TBox)
# ─────────────────────────────────────────────

DISCOVERY_SYSTEM = """\
You are an expert ontology engineer helping to design a knowledge graph schema.
You will read a small sample of documents and propose an initial schema.

The schema has two parts:
  - entity_classes: the types of nodes (e.g. Person, Plant, Event, Time, etc)
  - relation_types: the types of edges between nodes (e.g. treats, caused_by, located_in, involves_actor, etc)

Rules:
  - Use PascalCase for class names (e.g. "MedicinalPlant", not "medicinal plant")
  - Use snake_case for relation names (e.g. "treats", "involves_actor")
  - Every relation must have a domain and range that are valid entity class names
  - Prefer specific over generic (e.g. "MedicinalPlant" over "Thing")
  - Do NOT include entity classes with zero possible examples in this corpus

Respond ONLY with a valid JSON object matching the provided schema.
Do not include any explanation outside the JSON.
"""

def discovery_user(
    documents: list[str],
    domain: str,
    output_schema_json: str,
) -> str:
    """
    Generates the user prompt for initial schema discovery.

    Args:
        documents:          List of document texts (the 10% discovery sample).
        domain:             Dataset name ('aita' or 'pubmed_ethnobotany').
        output_schema_json: JSON schema of the Schema Pydantic model (for LLM guidance).
    """
    docs_block = "\n\n---\n\n".join(
        f"[Document {i+1}]\n{doc[:1500]}"   # truncate to avoid token overflow
        for i, doc in enumerate(documents)
    )
    return f"""\
Domain: {domain}

Here are {len(documents)} sample documents from this corpus:

{docs_block}

Based on these documents, propose an initial knowledge graph schema.
Return a JSON object with this exact structure:

{output_schema_json}
"""


# ─────────────────────────────────────────────
#  Phase 1B — HITL refinement
#  Input:  current schema + user message
#  Output: LLMSchemaProposal (list of edits + explanation)
# ─────────────────────────────────────────────

REFINEMENT_SYSTEM = """\
You are a knowledge graph schema assistant helping a user iteratively refine
their ontology through conversation.

You will receive:
  1. The current schema (entity classes and relation types)
  2. A message from the user requesting changes

Your job is to translate the user's intent into a list of atomic schema edits.

Supported edit types:
  - add_class:          add a new entity class
  - remove_class:       remove an entity class (also removes dependent relations)
  - merge_classes:      merge two classes into one (target = surviving class name)
  - rename_class:       rename a class (value = new name)
  - add_relation:       add a new relation type; set "domain" to the subject class
                        name and "range" to the object class name (both required)
  - remove_relation:    remove a relation type
  - rename_relation:    rename a relation (value = new name)
  - update_description: update the description of a class or relation

Rules:
  - Always maintain domain-range consistency: if you add a relation, its domain
    and range must be valid class names AFTER all edits are applied
  - If the user says "merge X and Y into Z", use merge_classes with target=X, value=Z,
    then another merge_classes with target=Y, value=Z
  - If the user's request is ambiguous, list it in 'questions' (max 1 question)
  - Be conservative: only propose what the user explicitly asked for

Respond ONLY with a valid JSON object. No text outside the JSON.
"""

def refinement_user(
    current_schema_json: str,
    user_message: str,
    output_schema_json: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Generates the user prompt for a HITL refinement turn.

    Args:
        current_schema_json: JSON of the current Schema.
        user_message:        The user's natural language request.
        output_schema_json:  JSON schema of LLMSchemaProposal.
        conversation_history: Previous turns for context (optional).
    """
    history_block = ""
    if conversation_history:
        lines = []
        for turn in conversation_history[-4:]:  # last 4 turns max
            lines.append(f"[{turn['role'].upper()}] {turn['message']}")
        history_block = "Recent conversation:\n" + "\n".join(lines) + "\n\n"

    return f"""\
{history_block}Current schema:
{current_schema_json}

User request: {user_message}

Propose the edits needed to fulfill this request.
Return a JSON object with this exact structure:

{output_schema_json}
"""


# ─────────────────────────────────────────────
#  Phase 2 — Batch extraction (ABox)
#  Input:  document + frozen schema
#  Output: ExtractionResult
# ─────────────────────────────────────────────

EXTRACTION_SYSTEM = """\
You are a knowledge graph extraction engine.
Extract entities and relations from a document using the provided schema.

Rules:
  - Extract ONLY classes and relations defined in the schema
  - Entity IDs: '{class_lowercase}_{slug}'  e.g. 'person_narrator', 'emotion_anger'
  - Slugs: lowercase, underscores only
  - CRITICAL: every entity_id used in a relation MUST exist in the entities list.
    If you want to express "narrator feels anger", you MUST add the Emotion entity first,
    then add the relation. A relation without its entity is invalid and will be removed.
  - source_doc_id in every entity and relation must equal the document's doc_id
  - Add unrepresentable content to 'unmapped_entities' (do NOT invent new classes)
  - Confidence: 1.0 certain, 0.5 plausible, 0.0 guess

Respond ONLY with a valid JSON object. No text outside the JSON.
"""


def _compact_schema(schema_json: str) -> str:
    """Convert full Schema JSON to a compact text representation (~4x fewer tokens)."""
    import json
    s = json.loads(schema_json)
    classes = ", ".join(c["name"] for c in s["entity_classes"])
    rels = "\n".join(
        f"  {r['name']}: {r['domain']} → {r['range']}"
        for r in s["relation_types"]
    )
    return f"Entity classes: {classes}\n\nRelations (predicate: domain → range):\n{rels}"


def extraction_user(
    document: str,
    doc_id: str,
    schema_json: str,
    schema_version: int,
    output_schema_json: str,  # kept for API compatibility, no longer injected
) -> str:
    """
    Generates the user prompt for extracting ABox from one document.

    The full Pydantic JSON schema (output_schema_json) is intentionally NOT
    injected — it adds ~1350 tokens with no quality benefit. A compact example
    is used instead.
    """
    compact = _compact_schema(schema_json)
    return f"""\
Document ID: {doc_id}
Schema version: {schema_version}

Schema:
{compact}

Document:
{document}

Extract all entities and relations. Return this JSON (copy doc_id and schema_version exactly):
{{
  "doc_id": "{doc_id}",
  "schema_version": {schema_version},
  "entities": [
    {{"id": "person_narrator", "class_name": "Person", "name": "narrator", "source_doc_id": "{doc_id}", "confidence": 1.0}}
  ],
  "relations": [
    {{"subject_id": "person_narrator", "predicate": "performs_action", "object_id": "action_refusing", "source_doc_id": "{doc_id}", "confidence": 0.9}}
  ],
  "unmapped_entities": [],
  "schema_modification_proposed": false
}}
"""


# ─────────────────────────────────────────────
#  Phase 3 — GIV self-repair
#  Input:  failed JSON + validation errors
#  Output: corrected ExtractionResult JSON
# ─────────────────────────────────────────────

REPAIR_SYSTEM = """\
You are a JSON repair assistant for a knowledge graph extraction system.
You will receive a JSON object that failed Pydantic validation and the list of errors.
Your job is to fix the JSON so it passes validation.

Rules:
  - Fix ONLY what the errors describe. Do not change valid fields.
  - The most common errors are:
      * class_name not in schema → change to closest valid class
      * predicate not in schema → change to closest valid relation or remove the triple
      * subject_id or object_id references a non-existent entity → remove the relation
      * id format wrong → reformat as '{class_name_lowercase}_{slug}'
  - If an error cannot be fixed without inventing data, remove the offending item
  - Return the complete corrected JSON, not just the diff

Respond ONLY with a valid JSON object. No text outside the JSON.
"""

def repair_user(
    failed_json: str,
    validation_errors: list[str],
    schema_json: str,
    output_schema_json: str,
    attempt: int,
) -> str:
    """
    Generates the user prompt for a GIV repair iteration.

    Args:
        failed_json:        The JSON that failed validation.
        validation_errors:  List of Pydantic error messages.
        schema_json:        The frozen schema for reference.
        output_schema_json: JSON schema of ExtractionResult.
        attempt:            Current repair attempt number (1-indexed).
    """
    errors_block = "\n".join(f"  - {e}" for e in validation_errors)
    return f"""\
Repair attempt {attempt}.

The following JSON failed validation with these errors:
{errors_block}

Schema (for reference — valid class and relation names):
{schema_json}

Failed JSON to repair:
{failed_json}

Return the corrected JSON matching this structure:

{output_schema_json}
"""


# ─────────────────────────────────────────────
#  Phase 4 — Downstream QA (evaluation only)
#  Used in Block D of the evaluation plan
# ─────────────────────────────────────────────

QA_GENERATION_SYSTEM = """\
You are generating factual questions from a document for a knowledge graph evaluation.

Rules:
  - Generate exactly {n} questions
  - Each question must be answerable from the document text alone
  - Questions should be factual and specific (who, what, which, how many)
  - Do NOT ask questions about structure, formatting, or metadata
  - Do NOT generate yes/no questions
  - Questions must be answerable without the knowledge graph — they test if
    the graph PRESERVES information, not if it adds new information

Return ONLY a JSON array of strings. Example:
["What plant is used to treat fever?", "Which symptom does ginger address?"]
"""

def qa_generation_user(document: str, n: int = 5) -> str:
    return f"""\
Generate {n} factual questions from this document:

{document[:2000]}
"""

QA_JUDGE_SYSTEM = """\
You are evaluating whether a knowledge graph answer correctly addresses a question,
based on evidence from the original source document.

You will receive:
  1. A question
  2. An answer produced by querying a knowledge graph
  3. The relevant passage from the original document

Your job: does the answer correctly and completely address the question,
according to the source passage?

Respond with a JSON object:
  { "verdict": "YES" | "NO" | "PARTIAL", "reason": "one sentence explanation" }
"""

def qa_judge_user(question: str, answer: str, source_passage: str) -> str:
    return f"""\
Question: {question}

Knowledge graph answer: {answer}

Source passage:
{source_passage}
"""