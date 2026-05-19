# Evaluation Plan
## Conversational Graph Extraction from Unstructured Data
### Ground-Truth-Free Evaluation Framework

---

## Premise and Research Questions

The central challenge of this project is epistemological: **the schema is itself the output**, so there is no external standard against which to measure it. This evaluation plan treats that constraint not as a limitation but as the core scientific question. Following the professor's explicit requirement, all metrics are computable without a gold-standard ontology.

The evaluation answers three research questions:

**RQ1 — Efficacy.** Does conversational schema discovery produce a more useful and coherent knowledge graph than non-conversational baselines?

**RQ2 — Generalization.** Does the schema discovered on a small sample transfer to the rest of the corpus without degradation?

**RQ3 — Convergence.** Can schema stabilization be detected computationally, and does it correlate with graph quality?

---

## Experimental Setup

### Datasets

| Dataset | Domain | Size | Ontology ambiguity |
|---|---|---|---|
| AITA (Reddit) | Social / moral reasoning | 500 posts | Very high — no canonical schema |
| PubMed Ethnobotany | Scientific / biomedical | 400–500 abstracts | Medium — domain vocabulary exists, structure does not |

Using two domains with different ambiguity levels tests whether the system's behavior is domain-agnostic.

### Baselines

| ID | Name | Description |
|---|---|---|
| B0 | OpenIE | Pure Subject-Verb-Object extraction, no schema. Establishes lower bound. |
| B1 | Zero-Shot GIV | Single LLM call with Pydantic validation. Schema proposed once, never refined. |
| **Ours** | **HITL + GIV** | Conversational discovery on 10% sample → frozen schema → batch extraction. |

### Discovery / Validation Split

All schema discovery happens on a **10% Discovery Subset** (50 posts / 40–50 abstracts), selected via semantic clustering to maximize content diversity. The remaining **90% Validation Corpus** is used exclusively for batch extraction and generalization testing. The schema is frozen before any contact with the validation corpus.

---

## Block A — Intrinsic Schema Quality

*These metrics require no external reference. They measure whether the schema itself is internally coherent and non-redundant.*

---

### A1 — Schema Utilization Rate (SUR)

**Definition.**

$$\text{SUR} = \frac{|\{c \in \mathcal{C} : \text{pop}(c) > 0\}|}{|\mathcal{C}|}$$

where $\mathcal{C}$ is the set of classes in the frozen schema and $\text{pop}(c)$ is the number of instances of class $c$ extracted during batch extraction on the Validation Corpus.

**Rationale.** A schema with many unused classes signals that the LLM over-generalized during zero-shot discovery. A conversationally refined schema should be more focused: fewer classes, but all populated. This directly operationalizes the hypothesis that HITL produces less noise.

**Expected outcome.** SUR(HITL) > SUR(Zero-Shot GIV) >> SUR(OpenIE ≈ 1.0 trivially, since OpenIE has no schema).

**Reporting.** Report SUR per class type (entity classes vs. relation types separately). Report the distribution, not just the mean — a bimodal distribution (some classes at 100%, others at 0%) is itself a meaningful finding.

---

### A2 — Relation Type Entropy (RTE)

**Definition.**

$$\text{RTE} = -\sum_{r \in \mathcal{R}} p(r) \log_2 p(r)$$

where $\mathcal{R}$ is the set of distinct relation types in the extracted graph and $p(r)$ is the proportion of edges labeled $r$.

**Rationale.** OpenIE produces hundreds of surface-level relation phrases (`said that`, `is known for`, `has been linked to`), yielding high entropy. A schema-constrained graph concentrates edges on a small set of typed relations, producing low entropy. Low RTE is not intrinsically better — it depends on semantic coherence — but the *comparison* between systems on the same corpus is informative. Combine with A1: a schema with low SUR and low RTE has converged to a small, dense ontology; whether that's useful is tested in Block D.

**Expected outcome.** RTE(OpenIE) >> RTE(Zero-Shot) > RTE(HITL).

---

### A3 — Schema Consistency Rate (SCR)

**Definition.**

$$\text{SCR} = 1 - \frac{|\text{Pydantic validation errors during batch extraction}|}{|\text{total extracted triples}|}$$

**Rationale.** The GIV self-repair loop enforces schema compliance, but real-world text always produces edge cases. SCR measures how often the frozen schema is violated during large-scale extraction. A low SCR means the schema was designed on too narrow a sample and doesn't generalize to the vocabulary of the full corpus. A high SCR means the schema is robust.

**Note.** SCR is partially confounded by the repair loop — if the system always repairs, SCR approaches 1.0 trivially. Report both *pre-repair* and *post-repair* SCR separately to expose how much work the repair loop is doing.

---

### A4 — Orphan Node Rate (ONR)

**Definition.**

$$\text{ONR} = \frac{|\{v \in V : \deg(v) = 0\}|}{|V|}$$

**Rationale.** An orphan node is an entity that was extracted but never connected to any other entity via a relation. High ONR indicates that the extraction pipeline extracts entities without understanding their context — a classic OpenIE failure mode. A schema-guided system should produce fewer orphans because the schema defines what relations must exist before an entity is retained.

**Expected outcome.** ONR(OpenIE) >> ONR(Zero-Shot) > ONR(HITL).

---

## Block B — Convergence Analysis

*These metrics measure the conversational process itself, not just its output. They answer RQ3.*

---

### B1 — Schema Edit Distance per Turn (ΔS_t)

**Formal definition of edit distance between two schema versions S_t and S_{t-1}.**

$$\Delta S_t = w_{\text{add}} \cdot |C_{\text{added}}| + w_{\text{del}} \cdot |C_{\text{deleted}}| + w_{\text{merge}} \cdot |C_{\text{merged}}| + w_{\text{rename}} \cdot |C_{\text{renamed}}| + w_{\text{rel}} \cdot |R_{\Delta}|$$

where $C_{\text{added}}, C_{\text{deleted}}, C_{\text{merged}}, C_{\text{renamed}}$ are class-level operations and $R_{\Delta}$ is the set of changed relations. Weights are set to $w_{\text{merge}} = 2, w_{\text{del}} = 1, w_{\text{add}} = 1, w_{\text{rename}} = 0.5, w_{\text{rel}} = 1$ (merge penalized more because it destroys information).

**What to plot.** Plot $\Delta S_t$ as a function of turn $t$ for each session. The hypothesis is a monotonically decreasing curve converging toward zero — evidence that the conversation is doing real work and not oscillating randomly. An oscillating curve is itself a finding: it means the user and the LLM are not converging, which is a negative result worth reporting.

**Convergence point $T^*$.** Define $T^* = \min\{t : \Delta S_t < \varepsilon \text{ for 3 consecutive turns}\}$ where $\varepsilon$ is the minimum meaningful schema change (e.g., $\varepsilon = 1.0$ in the weighted scale above). Report $T^*$ per session and per domain. Compare: does PubMed converge faster than AITA? A faster $T^*$ on PubMed would support the hypothesis that domains with stronger prior structure are easier to discover conversationally.

---

### B2 — User Acceptance Rate (UAR)

**Definition.**

$$\text{UAR} = \frac{|\text{LLM proposals accepted without modification}|}{|\text{total LLM proposals}|}$$

**Rationale.** Each turn the LLM proposes schema modifications (new class, merge, relation). The user either accepts, rejects, or modifies the proposal. UAR measures alignment between LLM proposals and user intent. A high UAR in early turns means the LLM's initial proposals are good. A UAR that increases over the conversation means the LLM is learning the user's ontological preferences within the session. This is the behavioral proxy for "is the conversation useful?"

**Operationalization.** Log every LLM proposal and every user response. Categorize responses as: (a) accepted as-is, (b) modified and accepted, (c) rejected. Plot all three over turns.

---

## Block C — Generalization

*These metrics answer RQ2: does the schema transfer to unseen data?*

---

### C1 — Unmapped Instance Rate (UIR)

**Definition.**

$$\text{UIR} = \frac{|\text{entities in validation corpus that don't match any schema class}|}{|\text{total entities extracted from validation corpus}|}$$

**Operationalization.** During batch extraction on the 90% validation corpus, count every time the LLM proposes an entity of a type not present in the frozen schema. These are logged automatically by the Pydantic validator as type errors before repair.

**Why this is the most important metric.** UIR is the only metric that directly measures whether the schema was over-fitted to the 10% discovery sample. A UIR above 20% is a strong signal of overfitting. Report UIR separately for HITL and Zero-Shot GIV — if HITL UIR is *lower*, it means the conversational refinement produced a more general schema, which is the central claim of the project.

**Do not use an arbitrary threshold.** Report the raw UIR value and let the comparison between systems speak. The threshold question ("is 5% good?") is unanswerable without ground truth — but "HITL UIR < Zero-Shot UIR" is a falsifiable hypothesis.

---

### C2 — Schema Drift Rate (SDR)

**Definition.**

During batch extraction, the LLM occasionally proposes modifications to the frozen schema when it encounters entities or relations that don't fit. SDR counts these proposals.

$$\text{SDR} = \frac{|\text{schema modification proposals during batch extraction}|}{|\text{documents processed}|}$$

**Rationale.** A well-generalized schema should produce almost no modification proposals during batch extraction — the LLM should be able to fit everything into the existing structure. A high SDR means the discovery phase explored too narrow a region of the corpus. SDR is complementary to UIR: UIR measures failures at the entity level, SDR measures them at the schema level.

---

## Block D — Downstream Task Evaluation

*This is the only block that requires an external evaluator, but it avoids ground-truth ontologies by grounding evaluation in the source text itself.*

---

### D1 — GraphRAG Question Answering (QA)

**Protocol.**

1. For each dataset, generate **30 factual questions** from the source documents using a dedicated LLM prompt that explicitly prohibits questions about schema structure. Questions must be answerable from the text alone. Use a different model from the one used for extraction (e.g., use Claude for question generation if GPT-4o was used for extraction) to avoid systematic alignment.

2. Answer each question using four retrieval systems:
   - **Graph-HITL**: GraphRAG over the HITL knowledge graph
   - **Graph-ZeroShot**: GraphRAG over the Zero-Shot graph
   - **Graph-OpenIE**: GraphRAG over the OpenIE graph
   - **Plain-RAG**: standard vector similarity retrieval over raw text (no graph)

3. Evaluate each answer using **LLM-as-judge with source passage as evidence** — following the FactCheck pipeline, not against the graph. The prompt is: *"Given this passage from the original document, does this answer correctly address the question? Answer YES/NO with a brief justification."* The source passage is retrieved via standard RAG, independent of the graph.

**Why this avoids the circularity problem.** The judge evaluates answers against the source text, not against the graph. This means a graph that hallucinates or distorts information will produce wrong answers even if those answers are internally consistent with the graph.

**Reporting.** Report accuracy (% of YES judgments) per system per dataset. Report also the delta: QA(HITL) - QA(Plain-RAG). If the delta is positive, the knowledge graph is adding value over raw retrieval.

---

## Block E — Multi-Session Variability (if feasible, strongly recommended)

*This block addresses the single-user confound identified in the design review.*

---

### E1 — Inter-Session Schema Agreement (ISA)

**Protocol.** Run at least 2 independent HITL sessions on the same 10% discovery subset with different users (e.g., two members of the project team, or two classmates familiar with the domain). Each session produces a schema $S_A$ and $S_B$.

**Definition.**

$$\text{ISA} = \text{BERTScore}(\text{class\_names}(S_A), \text{class\_names}(S_B))$$

complemented by Jaccard similarity on the set of relation types:

$$J(R_A, R_B) = \frac{|R_A \cap R_B|}{|R_A \cup R_B|}$$

**Rationale.** ISA has two possible outcomes, both scientifically interesting:
- **High ISA** (similar schemas from different users): the domain has a discoverable canonical ontology, and the system reliably finds it.
- **Low ISA** (divergent schemas): the ontology is genuinely subjective. This is itself a contribution — it quantifies the ontological ambiguity of the domain. Compare ISA(AITA) vs ISA(PubMed): the hypothesis is that PubMed should yield higher agreement because the scientific domain has stronger prior structure.

---

## Summary Table

| Block | Metric | Requires GT? | Answers | Primary comparison |
|---|---|---|---|---|
| A | A1 — SUR | No | RQ1 | HITL vs Zero-Shot |
| A | A2 — RTE | No | RQ1 | HITL vs Zero-Shot vs OpenIE |
| A | A3 — SCR | No | RQ1 | HITL vs Zero-Shot |
| A | A4 — ONR | No | RQ1 | All three systems |
| B | B1 — ΔS_t | No | RQ3 | Convergence curve |
| B | B2 — UAR | No | RQ3 | Per-turn alignment |
| C | C1 — UIR | No | RQ2 | HITL vs Zero-Shot |
| C | C2 — SDR | No | RQ2 | HITL vs Zero-Shot |
| D | D1 — QA | Source text only | RQ1 | All systems + Plain-RAG |
| E | E1 — ISA | No | RQ2+RQ3 | AITA vs PubMed |

---

## Implementation Notes

**Logging requirements.** Every schema version at every turn must be persisted (JSON). Every Pydantic error must be logged with the offending triple. Every LLM proposal during batch extraction must be captured. Without structured logging, Blocks B and C cannot be computed retroactively.

**Execution order.** Run discovery sessions first, freeze schemas, then run batch extraction. Never expose the validation corpus to the user during discovery — this is a fundamental methodological constraint.

**Statistical reporting.** For all metrics, report mean and standard deviation across documents (not just aggregate totals). For Block D, report a paired comparison (same 30 questions across all systems) and compute a Wilcoxon signed-rank test to establish statistical significance, following CLARE's methodology.

**Negative results are results.** If UIR(HITL) ≈ UIR(Zero-Shot), that is a finding: the conversation doesn't improve generalization. If ΔS_t does not decrease monotonically, that means the convergence criterion is not met. The evaluation plan is designed to be falsifiable — all hypotheses can fail, and that failure is scientifically meaningful.