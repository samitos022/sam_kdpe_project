"""
neo4j_client.py — Neo4j driver wrapper.

Responsibilities:
  1. Write ExtractionResult (entities + relations) to Neo4j
  2. Query nodes and edges for the frontend graph viewer
  3. Compute graph statistics for evaluation metrics (SUR, RTE, ONR)

Design:
  Every node carries a `session_id` property so multiple extraction
  sessions can coexist in the same database without interfering.
  The session_id is the SchemaManager.session_id.

Node labels follow the EntityClass.name from the schema  (e.g. :Plant, :Symptom).
Edge types follow RelationType.name in SCREAMING_SNAKE_CASE  (e.g. :TREATS).
"""

from __future__ import annotations

import os
from collections import Counter

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

load_dotenv()


class Neo4jClient:
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self._driver: Driver = GraphDatabase.driver(
            uri      or os.getenv("NEO4J_URI",      "bolt://localhost:7687"),
            auth=(
                user     or os.getenv("NEO4J_USER",     "neo4j"),
                password or os.getenv("NEO4J_PASSWORD", "password"),
            ),
        )

    def close(self) -> None:
        self._driver.close()

    def verify_connection(self) -> bool:
        with self._driver.session() as s:
            return s.run("RETURN 1 AS ok").single()["ok"] == 1

    # ─────────────────────────────────────────
    #  Write
    # ─────────────────────────────────────────

    def write_extraction_result(
        self,
        result,           # ExtractionResult — avoid circular import
        session_id: str,
    ) -> None:
        """
        Persist one ExtractionResult to Neo4j.

        Entities become nodes labelled with their class_name.
        Relations become directed edges labelled with the predicate.
        MERGE is used so re-running extraction is idempotent.
        """
        with self._driver.session() as s:
            # Write entities
            for entity in result.entities:
                label = entity.class_name          # e.g. "Plant"
                s.run(
                    f"MERGE (n:{label} {{id: $id, session_id: $sid}}) "
                    "SET n.name = $name, "
                    "    n.source_doc = $doc, "
                    "    n.confidence = $conf",
                    id=entity.id,
                    sid=session_id,
                    name=entity.name,
                    doc=entity.source_doc_id,
                    conf=entity.confidence,
                )

            # Write relations
            for rel in result.relations:
                # Edge type must be a valid Cypher identifier → SCREAMING_SNAKE_CASE
                edge_type = rel.predicate.upper().replace(" ", "_").replace("-", "_")
                s.run(
                    f"MATCH (a {{id: $subj, session_id: $sid}}), "
                    f"      (b {{id: $obj,  session_id: $sid}}) "
                    f"MERGE (a)-[r:{edge_type}]->(b) "
                    "SET r.source_doc  = $doc, "
                    "    r.confidence  = $conf, "
                    "    r.session_id  = $sid",
                    subj=rel.subject_id,
                    obj=rel.object_id,
                    sid=session_id,
                    doc=rel.source_doc_id,
                    conf=rel.confidence,
                )

    def clear_session(self, session_id: str) -> None:
        """Delete all nodes and edges belonging to a session."""
        with self._driver.session() as s:
            s.run(
                "MATCH (n {session_id: $sid}) DETACH DELETE n",
                sid=session_id,
            )

    # ─────────────────────────────────────────
    #  Read — for the frontend graph viewer
    # ─────────────────────────────────────────

    def get_nodes(
        self,
        session_id: str,
        class_name: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Return nodes for the frontend.
        Optionally filter by class (label).
        """
        with self._driver.session() as s:
            if class_name:
                result = s.run(
                    f"MATCH (n:{class_name} {{session_id: $sid}}) "
                    "RETURN elementId(n) AS id, labels(n) AS labels, "
                    "       n.name AS name, n.confidence AS confidence "
                    "LIMIT $limit",
                    sid=session_id,
                    limit=limit,
                )
            else:
                result = s.run(
                    "MATCH (n {session_id: $sid}) "
                    "RETURN elementId(n) AS id, labels(n) AS labels, "
                    "       n.name AS name, n.confidence AS confidence "
                    "LIMIT $limit",
                    sid=session_id,
                    limit=limit,
                )
            return [dict(r) for r in result]

    def get_edges(
        self,
        session_id: str,
        predicate: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return edges for the frontend."""
        with self._driver.session() as s:
            if predicate:
                edge_type = predicate.upper().replace(" ", "_")
                result = s.run(
                    f"MATCH (a)-[r:{edge_type}]->(b) "
                    "WHERE r.session_id = $sid "
                    "RETURN elementId(a) AS source, elementId(b) AS target, "
                    "       type(r) AS predicate, r.confidence AS confidence "
                    "LIMIT $limit",
                    sid=session_id,
                    limit=limit,
                )
            else:
                result = s.run(
                    "MATCH (a)-[r]->(b) "
                    "WHERE r.session_id = $sid "
                    "RETURN elementId(a) AS source, elementId(b) AS target, "
                    "       type(r) AS predicate, r.confidence AS confidence "
                    "LIMIT $limit",
                    sid=session_id,
                    limit=limit,
                )
            return [dict(r) for r in result]

    def search_nodes(self, session_id: str, query: str, limit: int = 20) -> list[dict]:
        """Case-insensitive substring search on node names."""
        with self._driver.session() as s:
            result = s.run(
                "MATCH (n {session_id: $sid}) "
                "WHERE toLower(n.name) CONTAINS toLower($q) "
                "RETURN elementId(n) AS id, labels(n) AS labels, n.name AS name "
                "LIMIT $limit",
                sid=session_id,
                q=query,
                limit=limit,
            )
            return [dict(r) for r in result]

    # ─────────────────────────────────────────
    #  Stats — for evaluation metrics
    # ─────────────────────────────────────────

    def get_stats(self, session_id: str) -> dict:
        """
        Compute graph-level statistics used in Block A of the evaluation plan.

        Returns:
          n_nodes         — total nodes
          n_edges         — total edges
          class_counts    — {ClassName: count}   (for SUR)
          relation_counts — {predicate: count}    (for RTE)
          orphan_count    — nodes with degree 0   (for ONR)
          orphan_rate     — ONR = orphan_count / n_nodes
          relation_entropy— H(R) = -Σ p(r) log₂ p(r)  (RTE)
        """
        import math

        with self._driver.session() as s:
            # Node count and class distribution
            node_res = s.run(
                "MATCH (n {session_id: $sid}) "
                "RETURN labels(n)[0] AS label, count(*) AS cnt",
                sid=session_id,
            )
            class_counts: dict[str, int] = {}
            n_nodes = 0
            for row in node_res:
                class_counts[row["label"]] = row["cnt"]
                n_nodes += row["cnt"]

            # Edge count and relation distribution
            edge_res = s.run(
                "MATCH ()-[r]->()"
                "WHERE r.session_id = $sid "
                "RETURN type(r) AS rel, count(*) AS cnt",
                sid=session_id,
            )
            relation_counts: dict[str, int] = {}
            n_edges = 0
            for row in edge_res:
                relation_counts[row["rel"]] = row["cnt"]
                n_edges += row["cnt"]

            # Orphan nodes (degree = 0)
            orphan_res = s.run(
                "MATCH (n {session_id: $sid}) "
                "WHERE NOT (n)--() "
                "RETURN count(n) AS cnt",
                sid=session_id,
            )
            orphan_count = orphan_res.single()["cnt"]

        # Relation type entropy H(R)
        entropy = 0.0
        if n_edges > 0:
            for cnt in relation_counts.values():
                p = cnt / n_edges
                entropy -= p * math.log2(p)

        return {
            "n_nodes":          n_nodes,
            "n_edges":          n_edges,
            "class_counts":     class_counts,
            "relation_counts":  relation_counts,
            "orphan_count":     orphan_count,
            "orphan_rate":      orphan_count / n_nodes if n_nodes else 0.0,
            "relation_entropy": round(entropy, 4),
        }