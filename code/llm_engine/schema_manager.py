"""
schema_manager.py — Manages the lifecycle of a Schema across a HITL session.

Responsibilities:
  1. Apply atomic edits (from LLMSchemaProposal) to produce new schema versions
  2. Compute ΔS_t (weighted schema edit distance) between versions  →  Metric B1
  3. Detect convergence (T*) when ΔS_t < ε for 3 consecutive turns  →  Metric B2
  4. Persist every schema version to disk (JSON) for post-hoc analysis
  5. Freeze the schema when the user approves  →  locks batch extraction

All state is kept in memory during a session.  Call save() to persist.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from .parser import (
    EditType, EntityClass, HITLSession, LLMSchemaProposal,
    RelationType, Schema, SchemaEdit, ConversationTurn,
)


# ─────────────────────────────────────────────
#  Edit distance weights
#  Merge is penalised more than add/remove because it destroys information.
# ─────────────────────────────────────────────

EDIT_WEIGHTS: dict[EditType, float] = {
    "add_class":          1.0,
    "remove_class":       1.0,
    "merge_classes":      2.0,   # destructive — counts double
    "rename_class":       0.5,   # cosmetic — counts half
    "add_relation":       1.0,
    "remove_relation":    1.0,
    "rename_relation":    0.5,
    "update_description": 0.2,   # almost free — metadata only
}


class SchemaManager:
    """
    Manages one schema through its entire discovery session.

    Usage:
        mgr = SchemaManager(domain="pubmed_ethnobotany", log_dir=Path("logs"))
        mgr.set_initial_schema(schema)          # version 0
        proposal = ...                           # from core.py / LLM
        new_schema = mgr.apply_proposal(proposal, turn_id=1)
        if mgr.has_converged():
            frozen = mgr.freeze()
    """

    def __init__(self, domain: str, log_dir: Path | None = None):
        self.domain = domain
        self.log_dir = log_dir or Path("logs/schemas")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = str(uuid.uuid4())[:8]
        self._schemas: list[Schema] = []          # index = version number
        self._delta_history: list[float] = []     # ΔS_t per turn
        self._convergence_window = 3              # consecutive turns below ε
        self._epsilon = 1.0                       # minimum meaningful change
        self._session = HITLSession(
            session_id=self.session_id,
            domain=domain,
            discovery_doc_ids=[],
        )

    # ─────────────────────────────────────────
    #  Schema lifecycle
    # ─────────────────────────────────────────

    def set_initial_schema(self, schema: Schema) -> None:
        """
        Store the zero-shot seed schema (version 0).
        Called once after the initial LLM discovery call.
        """
        schema = schema.model_copy(update={"version": 0, "frozen": False})
        self._schemas.append(schema)
        self._save_version(schema)

    @property
    def current(self) -> Schema:
        if not self._schemas:
            raise RuntimeError("No schema set yet. Call set_initial_schema() first.")
        return self._schemas[-1]

    @property
    def version(self) -> int:
        return self.current.version

    def apply_proposal(
        self,
        proposal: LLMSchemaProposal,
        turn_id: int,
        user_message: str = "",
    ) -> Schema:
        """
        Apply all edits in an LLMSchemaProposal to produce a new schema version.
        Records the ΔS_t and adds a ConversationTurn to the session log.

        Returns the new Schema (or current if no edits were applied).
        """
        if self.current.frozen:
            raise RuntimeError("Schema is frozen. No edits allowed after freezing.")

        version_before = self.version
        new_schema = self._apply_edits(self.current, proposal.edits)
        new_schema = new_schema.model_copy(update={"version": version_before + 1})

        delta = self._compute_delta(proposal.edits)
        self._delta_history.append(delta)
        self._schemas.append(new_schema)
        self._save_version(new_schema)

        # Log the turn
        turn = ConversationTurn(
            turn_id=turn_id,
            role="assistant",
            message=proposal.explanation,
            schema_version_before=version_before,
            schema_version_after=new_schema.version,
            edits_applied=proposal.edits,
            delta_s=delta,
        )
        self._session.turns.append(turn)
        self._save_session()

        # Check convergence
        if self.has_converged():
            self._session.converged = True
            self._session.convergence_turn = turn_id

        return new_schema

    def record_user_turn(
        self,
        turn_id: int,
        message: str,
        acceptance: str | None = None,
    ) -> None:
        """
        Log a user message to the session (does not modify the schema).
        'acceptance' is the result of interpreting the user's response
        to the previous assistant proposal: 'accepted' | 'modified' | 'rejected'.
        """
        turn = ConversationTurn(
            turn_id=turn_id,
            role="user",
            message=message,
        )
        self._session.turns.append(turn)

        # Retroactively tag the previous assistant turn's acceptance
        if acceptance and len(self._session.turns) >= 2:
            prev_assistant_turns = [
                t for t in self._session.turns if t.role == "assistant"
            ]
            if prev_assistant_turns:
                prev_assistant_turns[-1].user_acceptance = acceptance  # type: ignore[assignment]

        self._save_session()

    def freeze(self) -> Schema:
        """
        Lock the current schema for batch extraction.
        After this, apply_proposal() raises an error.
        """
        frozen = self.current.model_copy(update={"frozen": True})
        self._schemas[-1] = frozen
        self._session.final_schema_version = frozen.version
        self._save_version(frozen)
        self._save_session()
        return frozen

    # ─────────────────────────────────────────
    #  Edit application
    # ─────────────────────────────────────────

    def _apply_edits(self, schema: Schema, edits: list[SchemaEdit]) -> Schema:
        """
        Apply a list of atomic edits to a schema, returning a new Schema.
        Edits are applied in order — order matters (e.g. add then reference).
        """
        classes = {c.name: c.model_copy() for c in schema.entity_classes}
        relations = {r.name: r.model_copy() for r in schema.relation_types}

        for edit in edits:
            t = edit.edit_type

            if t == "add_class":
                classes[edit.target] = EntityClass(
                    name=edit.target,
                    description=edit.value or "",
                )

            elif t == "remove_class":
                classes.pop(edit.target, None)
                # Remove relations that reference this class
                relations = {
                    n: r for n, r in relations.items()
                    if r.domain != edit.target and r.range != edit.target
                }

            elif t == "merge_classes":
                # Rename all occurrences of target → value in relations
                survivor = edit.value or edit.target
                old_class = classes.pop(edit.target, None)
                if old_class and survivor not in classes:
                    classes[survivor] = EntityClass(
                        name=survivor,
                        description=old_class.description,
                        examples=old_class.examples,
                    )
                # Update relations that referenced the old class
                for r in relations.values():
                    if r.domain == edit.target:
                        r.domain = survivor
                    if r.range == edit.target:
                        r.range = survivor

            elif t == "rename_class":
                old = classes.pop(edit.target, None)
                new_name = edit.value or edit.target
                if old:
                    classes[new_name] = old.model_copy(update={"name": new_name})
                for r in relations.values():
                    if r.domain == edit.target:
                        r.domain = new_name
                    if r.range == edit.target:
                        r.range = new_name

            elif t == "add_relation":
                domain = edit.domain or ""
                range_ = edit.range or ""
                relations[edit.target] = RelationType(
                    name=edit.target,
                    domain=domain,
                    range=range_,
                    description=edit.reason,
                )

            elif t == "remove_relation":
                relations.pop(edit.target, None)

            elif t == "rename_relation":
                old = relations.pop(edit.target, None)
                new_name = edit.value or edit.target
                if old:
                    relations[new_name] = old.model_copy(update={"name": new_name})

            elif t == "update_description":
                if edit.target in classes:
                    classes[edit.target] = classes[edit.target].model_copy(
                        update={"description": edit.value or ""}
                    )
                elif edit.target in relations:
                    relations[edit.target] = relations[edit.target].model_copy(
                        update={"description": edit.value or ""}
                    )

        # Rebuild schema — model_validator will re-check domain/range consistency
        # If edits left the schema inconsistent, we catch the error here.
        try:
            return Schema(
                domain=schema.domain,
                entity_classes=list(classes.values()),
                relation_types=list(relations.values()),
            )
        except Exception as e:
            # Log the error but return the previous schema to avoid data loss
            print(f"[SchemaManager] Edit produced invalid schema: {e}")
            return schema

    # ─────────────────────────────────────────
    #  Convergence (Metric B1)
    # ─────────────────────────────────────────

    def _compute_delta(self, edits: list[SchemaEdit]) -> float:
        """
        ΔS_t = weighted sum of edit operations.
        Defined formally in the evaluation plan, Block B.
        """
        return sum(EDIT_WEIGHTS.get(e.edit_type, 1.0) for e in edits)

    def has_converged(self) -> bool:
        """
        True if ΔS_t < ε for the last _convergence_window turns.
        T* = first turn where this condition is first satisfied.
        """
        if len(self._delta_history) < self._convergence_window:
            return False
        recent = self._delta_history[-self._convergence_window:]
        return all(d < self._epsilon for d in recent)

    def delta_history(self) -> list[float]:
        """Returns the full ΔS_t time series for plotting."""
        return list(self._delta_history)

    # ─────────────────────────────────────────
    #  Persistence
    # ─────────────────────────────────────────

    def _save_version(self, schema: Schema) -> None:
        path = self.log_dir / f"{self.session_id}_schema_v{schema.version}.json"
        path.write_text(schema.model_dump_json(indent=2))

    def _save_session(self) -> None:
        path = self.log_dir / f"{self.session_id}_session.json"
        path.write_text(self._session.model_dump_json(indent=2))

    def load_schema_version(self, version: int) -> Schema:
        """Load a specific schema version from disk (for post-hoc analysis)."""
        path = self.log_dir / f"{self.session_id}_schema_v{version}.json"
        return Schema.model_validate_json(path.read_text())

    def summary(self) -> dict:
        """Quick summary for logging / debugging."""
        return {
            "session_id": self.session_id,
            "domain": self.domain,
            "current_version": self.version,
            "n_classes": len(self.current.entity_classes),
            "n_relations": len(self.current.relation_types),
            "delta_history": self._delta_history,
            "converged": self.has_converged(),
            "frozen": self.current.frozen,
        }