# Open Questions & Research Directions

## 1. How do you measure schema quality when there is no ground-truth ontology?
Since the ontology is a moving target that depends entirely on user intent, traditional F1-scores against a static gold standard do not apply. We evaluate schema quality through indirect and structural metrics:
*   **Downstream Task Performance:** Evaluating the generated graph on a specific task, such as Retrieval-Augmented Generation (GraphRAG). If the conversational schema allows the LLM to answer questions about the corpus more accurately than a zero-shot schema, it is of higher quality.
*   **Structural Metrics (Information Theoretic):** Measuring graph density, connectivity, and edge type distribution. A poor schema tends to have high fragmentation (many orphan nodes) or excessive entropy in relation types (e.g., creating `related_to`, `connected_with`, `links_to` instead of a single merged relation).
*   **Schema Stability (Cross-Validation):** Splitting the corpus. If the schema generated on a small discovery subset generalizes well to the rest of the corpus (without forcing the LLM to hallucinate new entity types), the schema is solid.

## 2. What does the conversation contribute beyond what a careful one-shot prompt would produce?
The limitation of one-shot prompts (and traditional Open Information Extraction tools) is their *rigidity* and *lack of alignment with tacit user intent*. 
The conversation acts as an **Active Learning mechanism for ontology design**. Users often *do not know* what they want to extract until they see the data miscategorized by the LLM. The conversational loop handles edge cases, merges overlapping concepts (conceptual Entity Resolution), and ignores irrelevant relations that a one-shot prompt would have otherwise extracted, thus preventing graph pollution.

## 3. How do you detect convergence — when should the system stop asking?
Convergence can be modeled both mathematically and pragmatically:
*   **Schema Delta (Rate of Change):** Measuring the edit distance of the ontology (nodes/edges added, removed, merged) between iteration $T$ and $T-1$. When the Delta drops below a certain threshold across a sample of new documents, the system has stabilized.
*   **Mappability / LLM Confidence:** When the LLM successfully maps 95%+ of the information extracted from a new text chunk using the existing schema without proposing modifications.
*   **Human Sign-off:** An explicit "Approve Schema" action from the user, which triggers batch extraction on the remaining corpus.

## 4. Generalization vs. Overfitting: Is the schema reusable?
This is a central empirical question. The system will extract the initial schema on a "Discovery Subset" (e.g., 10% of the corpus, selected via semantic clustering to maximize diversity). The generalization test occurs on the remaining 90%. If batch extraction yields a high rate of "Unmapped Entities/Relations", the schema was likely overfitted to the user's local preferences during the chat session.

## State of the Art (SOTA)
Recent literature (2024-2026) has shifted from fully automated OpenIE to Human-in-the-Loop (HITL) extraction:
*   **LLMs4SchemaDiscovery (2025):** A HITL workflow for scientific schema mining via LLMs. Demonstrates the efficacy of expert feedback coupled with LLMs.
*   **CLARE: Context-Aware Interactive KG Construction (2025):** Explores interactive KG construction from transcripts, proving that conversational context improves extraction.
*   **Microsoft GraphRAG (2024):** Validated massive schema-less extraction but lacks a continuous interactive loop for user-guided ontology synthesis.
*   **Prompt-guided LLM Agents for Ontology Learning (2025):** Proposes a loop of "schema generation / fix-instances" to achieve consistency via LLM agents.

## Target Datasets
