"""
parser.py — Pydantic models for the entire system.

Two layers:
  TBox: Schema, EntityClass, RelationType  (the ontology)
  ABox: EntityInstance, RelationInstance   (the extracted facts)

Plus: conversation types for HITL and evaluation logging.

All models are Pydantic v2.  Every field has a description so that
model_json_schema() generates a self-documenting JSON Schema we can
paste directly into LLM prompts as the expected output format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────
#  TBox  —  the schema (ontology)
# ─────────────────────────────────────────────

class EntityClass(BaseModel):
    """
    One node type in the ontology.
    e.g.  name="Plant", description="A plant used in traditional medicine"
    """
    name: str = Field(
        description="PascalCase identifier, no spaces. e.g. 'Plant', 'Symptom', 'Person'."
    )
    description: str = Field(
        description="One sentence explaining what entities of this class represent."
    )
    examples: list[str] = Field(
        default_factory=list,
        description="2-3 surface-form examples. e.g. ['chamomile', 'ginger', 'turmeric']."
    )


class RelationType(BaseModel):
    """
    One edge type in the ontology, with domain and range constraints.
    e.g.  name="treats", domain="Plant", range="Symptom"
    """
    name: str = Field(
        description="snake_case identifier. e.g. 'treats', 'causes', 'involves_actor'."
    )
    domain: str = Field(
        description="Name of the EntityClass that is the subject of this relation."
    )
    range: str = Field(
        description="Name of the EntityClass that is the object of this relation."
    )
    description: str = Field(
        description="One sentence explaining what this relation means."
    )

    # ── Validation ──────────────────────────────────────────────────────────
    # We validate domain/range against the schema in Schema.model_validator,
    # not here, because RelationType doesn't know its parent Schema.


class Schema(BaseModel):
    """
    The full TBox: a versioned ontology with entity classes and relation types.
    One Schema object is created at the start of a discovery session and
    mutated (producing new versions) with each HITL turn.
    """
    version: int = Field(
        default=0,
        description="Monotonically increasing version number. Starts at 0 (zero-shot seed)."
    )
    domain: str = Field(
        description="Dataset identifier. e.g. 'aita' or 'pubmed_ethnobotany'."
    )
    entity_classes: list[EntityClass] = Field(
        default_factory=list,
        description="All node types in this schema."
    )
    relation_types: list[RelationType] = Field(
        default_factory=list,
        description="All edge types in this schema."
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when this version was created."
    )
    frozen: bool = Field(
        default=False,
        description="If True, this schema is locked for batch extraction. No more edits."
    )

    # ── Computed helpers ─────────────────────────────────────────────────────

    def class_names(self) -> set[str]:
        return {c.name for c in self.entity_classes}

    def relation_names(self) -> set[str]:
        return {r.name for r in self.relation_types}

    def get_class(self, name: str) -> EntityClass | None:
        return next((c for c in self.entity_classes if c.name == name), None)

    def get_relation(self, name: str) -> RelationType | None:
        return next((r for r in self.relation_types if r.name == name), None)

    # ── Cross-field validation ───────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_relation_domain_range(self) -> "Schema":
        """
        Every RelationType's domain and range must reference an existing EntityClass.
        This is the fundamental ontology consistency check (GIV: domain-range constraint).
        """
        known = self.class_names()
        errors: list[str] = []
        for rel in self.relation_types:
            if rel.domain not in known:
                errors.append(
                    f"Relation '{rel.name}' has domain '{rel.domain}' "
                    f"which is not a known EntityClass."
                )
            if rel.range not in known:
                errors.append(
                    f"Relation '{rel.name}' has range '{rel.range}' "
                    f"which is not a known EntityClass."
                )
        if errors:
            raise ValueError("\n".join(errors))
        return self


# ─────────────────────────────────────────────
#  ABox  —  the extracted instances
# ─────────────────────────────────────────────

class EntityInstance(BaseModel):
    """
    One extracted node: a real-world entity found in a document.
    e.g.  name="chamomile", class_name="Plant", source_doc_id="pubmed_123"
    """
    id: str = Field(
        description="Unique identifier. Format: '{class_name}_{slug}'. e.g. 'plant_chamomile'."
    )
    name: str = Field(
        description="Surface form as it appears (or normalized). e.g. 'chamomile'."
    )
    class_name: str = Field(
        description="Must match an EntityClass.name in the frozen schema."
    )
    source_doc_id: str = Field(
        description="ID of the source document this entity was extracted from."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0, le=1.0,
        description="LLM confidence score. 1.0 = certain, 0.0 = highly uncertain."
    )


class RelationInstance(BaseModel):
    """
    One extracted edge: a typed relation between two entities.
    e.g.  subject_id="plant_chamomile", predicate="treats", object_id="symptom_insomnia"
    """
    subject_id: str = Field(
        description="ID of the subject EntityInstance."
    )
    predicate: str = Field(
        description="Must match a RelationType.name in the frozen schema."
    )
    object_id: str = Field(
        description="ID of the object EntityInstance."
    )
    source_doc_id: str = Field(
        description="ID of the source document."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0, le=1.0,
        description="LLM confidence score."
    )


class ExtractionResult(BaseModel):
    """
    Full output of extracting one document against a frozen schema.
    Includes both successful extractions and validation failures (for UIR/SCR metrics).
    """
    doc_id: str
    schema_version: int = Field(
        description="Version of the schema used for this extraction."
    )
    entities: list[EntityInstance] = Field(default_factory=list)
    relations: list[RelationInstance] = Field(default_factory=list)

    # ── Metric logging fields ────────────────────────────────────────────────
    unmapped_entities: list[str] = Field(
        default_factory=list,
        description=(
            "Entity surface forms that the LLM could not assign to any schema class. "
            "Used to compute UIR (Unmapped Instance Rate)."
        )
    )
    validation_errors_pre_repair: list[str] = Field(
        default_factory=list,
        description=(
            "Pydantic validation errors BEFORE the GIV repair loop ran. "
            "Used to compute SCR pre-repair."
        )
    )
    validation_errors_post_repair: list[str] = Field(
        default_factory=list,
        description=(
            "Pydantic errors that survived all repair attempts. "
            "Used to compute SCR post-repair."
        )
    )
    repair_iterations: int = Field(
        default=0,
        description="Number of GIV repair iterations needed. 0 = clean first pass."
    )
    schema_modification_proposed: bool = Field(
        default=False,
        description=(
            "True if the LLM proposed a schema change during extraction of this doc. "
            "Used to compute SDR (Schema Drift Rate)."
        )
    )


# ─────────────────────────────────────────────
#  HITL  —  the conversation types
# ─────────────────────────────────────────────

EditType = Literal[
    "add_class",
    "remove_class",
    "merge_classes",   # merge two classes into one
    "rename_class",
    "add_relation",
    "remove_relation",
    "rename_relation",
    "update_description",
]


class SchemaEdit(BaseModel):
    """
    A single atomic edit proposed by the LLM in response to a user message.
    The LLM returns a list of these; SchemaManager applies them to produce
    the next schema version.
    """
    edit_type: EditType
    target: str = Field(
        description="The class or relation name being edited."
    )
    value: str | None = Field(
        default=None,
        description=(
            "For rename/merge: the new name or the merge target. "
            "For update_description: the new description text. "
            "Not used for add_relation (use domain/range fields instead)."
        )
    )
    domain: str | None = Field(
        default=None,
        description=(
            "For add_relation only: the EntityClass name that is the subject "
            "(left side) of this relation. Must match an existing class name."
        )
    )
    range: str | None = Field(
        default=None,
        description=(
            "For add_relation only: the EntityClass name that is the object "
            "(right side) of this relation. Must match an existing class name."
        )
    )
    reason: str = Field(
        default="",
        description="One sentence explaining why this edit is proposed."
    )


class LLMSchemaProposal(BaseModel):
    """
    What the LLM returns during a HITL refinement turn.
    Contains both the list of edits and a natural-language explanation for the user.
    """
    edits: list[SchemaEdit] = Field(
        description="Ordered list of atomic schema edits to apply."
    )
    explanation: str = Field(
        description="Human-readable summary of changes to show the user."
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Clarification questions the assistant wants to ask the user (max 1)."
    )


class ConversationTurn(BaseModel):
    """
    One turn in the HITL conversation.
    Stores the full before/after schema snapshot for computing ΔS_t.
    """
    turn_id: int
    role: Literal["user", "assistant"]
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Schema snapshots (populated only on assistant turns)
    schema_version_before: int | None = None
    schema_version_after: int | None = None
    edits_applied: list[SchemaEdit] = Field(default_factory=list)

    # Metric fields
    delta_s: float | None = Field(
        default=None,
        description="Schema edit distance ΔS_t for this turn. Computed by SchemaManager."
    )
    user_acceptance: Literal["accepted", "modified", "rejected"] | None = Field(
        default=None,
        description=(
            "Did the user accept the assistant's proposal? "
            "Populated on the NEXT user turn by inspecting their message."
        )
    )


class HITLSession(BaseModel):
    """
    The complete record of one schema discovery session.
    Serialized to JSON after each turn for the convergence analysis.
    """
    session_id: str
    domain: str
    discovery_doc_ids: list[str] = Field(
        description="IDs of documents used in the 10% discovery subset."
    )
    turns: list[ConversationTurn] = Field(default_factory=list)
    final_schema_version: int | None = None
    converged: bool = False
    convergence_turn: int | None = Field(
        default=None,
        description="Turn T* at which ΔS_t dropped below ε for 3 consecutive turns."
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)