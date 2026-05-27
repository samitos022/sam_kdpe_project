# Weekly Report — Evaluation Design
**Presentation script · English · ~12 min**

---

## [SLIDE 1] Title

*"Ground-Truth-Free Evaluation of Human-in-the-Loop Knowledge Graph Schema Discovery"*

---

## [SLIDE 2] The Core Problem

Let me start with what makes this project interesting — and what makes evaluating it hard.

Building a knowledge graph from scratch requires two things: a **schema** — the set of entity types and relation types you want to extract — and the **instances** themselves. The schema is the expensive part. Traditionally, domain experts spend weeks or months designing it by hand. What we're trying to do is replace that process with a conversation.

The user sits in front of a chat interface, the LLM proposes a schema from a small sample of documents, and the user refines it through natural language — "merge these two classes", "add a relation for causality", "the description of this concept is wrong". Once they're happy, we freeze the schema and run a batch extraction over the full corpus.

That's the system. The question for today is: **how do we know if it worked?**

---

## [SLIDE 3] System Architecture

Before we talk about evaluation, let me show you what we're actually evaluating.

The system has three layers. At the top, there's a chat interface — currently React — that the user talks to. In the middle, a FastAPI backend that manages sessions and orchestrates everything. At the bottom, an LLM engine that wraps LiteLLM, and Neo4j as the graph store.

```
┌─────────────────────────────────────────────┐
│              User (chat interface)           │
└───────────────────┬─────────────────────────┘
                    │ HTTP
┌───────────────────▼─────────────────────────┐
│           FastAPI backend                    │
│  /sessions  — HITL chat & extraction         │
│  /graph     — graph queries                  │
└────────┬──────────────────────┬─────────────┘
         │                      │
┌────────▼──────────┐  ┌────────▼──────────┐
│   LLM Engine      │  │     Neo4j          │
│   (LiteLLM)       │  │  (graph store)     │
│                   │  │                    │
│  1. discover_     │  │  written after     │
│     schema()      │  │  batch extraction  │
│  2. refine_       │  │                    │
│     schema()      │  └────────────────────┘
│  3. extract_      │
│     document()    │
└───────────────────┘
```

The system runs in three sequential phases.

**Phase 1 — Schema Discovery.** When the user starts a session, the backend loads the corpus and splits it: 10% goes into a *discovery set*, 90% is held out for later. The LLM reads the discovery documents and proposes an initial schema — entity classes, relation types, domain-range constraints. This is version 0: the zero-shot baseline.

**Phase 2 — HITL Refinement.** The user sees the proposed schema in the chat and starts refining it. "Merge these two classes." "Add a relation for causality." "The description of 'Author' is wrong." Each message goes to `refine_schema()`, which applies the edits as atomic operations and increments the schema version. The SchemaManager tracks every change — these diffs are what Block B measures. When the user is satisfied, they freeze the schema.

**Phase 3 — Batch Extraction with GIV.** The frozen schema is applied to the 90% validation set. For each document, `extract_document()` asks the LLM to populate the schema with instances — entities and relations. If the output violates the schema constraints, the GIV repair loop kicks in: it feeds the errors back to the LLM and asks for a correction, up to three times. Everything — entities, relations, repair attempts, unmapped mentions — is written to Neo4j and logged to JSONL for post-hoc metric computation.

That's the pipeline. The whole evaluation framework is built on top of the logs from Phase 2 and Phase 3.

---

## [SLIDE 4] Why Evaluation Is Hard Here

The usual answer to "did your KG extraction work?" is to compare against a gold standard — a manually annotated dataset. But we don't have that, and we can't have it, because the whole point of the system is to work on **arbitrary domains** chosen by the user.

So we need a **ground-truth-free evaluation framework**. Every metric we compute has to come from things we can observe without human annotation: the structure of the conversation, the structure of the extracted graph, and the internal consistency of the schema.

This is actually a well-recognized challenge in the literature, and the papers I'll mention in a moment all deal with it from different angles.

---

## [SLIDE 5] Related Work — Four Papers

Four papers shaped how I thought about this evaluation.

**First: LLMs4SchemaDiscovery.** This work looks specifically at using LLMs to induce schemas directly from text, without human supervision. Their key insight is that LLMs, when prompted correctly, can propose ontology structures that are coherent and domain-appropriate. What they don't address is what happens when the proposed schema is too generic or too specific for the actual data — which is exactly what our HITL loop is designed to fix. Our metrics pick up where their evaluation stops.

**Second: CLARE — Context-Aware Interactive KG Construction (2025).** CLARE is the closest work to our system architecturally. It frames KG construction as a dialogue, where the system proposes extractions and the user accepts, modifies, or rejects them. What's relevant for us is how they think about the quality of the interaction itself: not just the final graph, but how efficiently the system and user reach agreement. That's what motivates our Block B metrics — convergence and acceptance rate.

**Third: Prompt-guided LLM Agents for Ontology Learning (2025).** This paper uses prompted agents that iteratively refine an ontology over multiple rounds, similar to how our HITL loop works. Their evaluation focuses on structural properties of the final ontology — coverage, redundancy, internal consistency — which maps directly to our Block A schema quality metrics. They also highlight a failure mode we need to watch for: over-specification, where the schema is too specific to the seed documents and fails to generalize.

**Fourth: Benchmarking LLMs for Knowledge Graph Validation.** This is the most technically relevant paper for one of our specific mechanisms. It benchmarks LLMs on the task of catching schema violations — entities with wrong types, relations with violated domain-range constraints. This directly informs our GIV loop — the iterative self-repair mechanism where, if the LLM's extraction violates the schema, we feed the errors back and ask for a correction. Their benchmarking results give us a prior on how well this works and why we need to track both pre- and post-repair consistency.

---

## [SLIDE 6] Evaluation Architecture — The Blocks

Our evaluation is organized into four blocks, each measuring a different aspect of what "good" means for this system.

```
Block A — Schema Quality      (structural properties of the final schema)
Block B — HITL Convergence    (quality of the human-machine interaction)
Block C — Generalization      (does the schema transfer to unseen data?)
Block D — Downstream Utility  (does the graph actually help answer questions?)
```

The blocks are ordered by dependency: you need a frozen schema before you can measure generalization, and you need extracted instances before you can measure downstream utility.

---

## [SLIDE 7] Block B — Measuring the Conversation

Block B is about the HITL interaction itself, before we even look at the final graph.

**B1 — Schema Edit Distance (ΔS_t)**

At each turn of the conversation, the LLM proposes a set of atomic schema edits — add a class, rename a relation, merge two classes. We compute a weighted sum of those edits:

```
ΔS_t = Σ weight(edit_type)

  add / remove class or relation  →  weight 1.0
  rename                          →  weight 0.5   (cosmetic)
  merge                           →  weight 2.0   (destructive — penalised double)
  update description              →  weight 0.2   (almost free)
```

The idea is that merge gets a higher weight because it destroys information — you're collapsing two concepts into one, which is harder to undo.

We plot ΔS_t as a time series across turns. What we hope to see is a decreasing curve — large structural changes early in the session when the schema is still rough, then smaller refinements, then essentially zero when the user is just polishing descriptions. Convergence T* is declared when ΔS_t stays below 1.0 for three consecutive turns.

This gives us two things: a **convergence curve** to plot, and **convergence turn T*** — the number of turns it takes before the system and user reach a stable schema.

**B2 — User Acceptance Rate (UAR)**

At each turn, we also track whether the user accepted the LLM's proposal as-is, modified it, or rejected it. UAR is simply:

```
UAR = turns accepted as-is / total labelled turns
```

A high UAR means the LLM is understanding user intent well. A low UAR means the user is doing a lot of correction work. Note that the first turn is always a refinement — there's nothing to accept yet — so we only compute UAR on turns 2 and onward. And turns where the user sends an ambiguous message — one that doesn't clearly signal acceptance or rejection — are excluded from the denominator.

---

## [SLIDE 8] Block A — Schema Quality

Block A measures properties of the final frozen schema against the extracted data. All four metrics here are computable without a gold standard.

**A1 — Schema Utilization Rate (SUR)**

```
SUR = |classes with at least one extracted instance| / |total schema classes|
```

If you have a schema with 10 entity classes but only 6 of them ever appear in the extracted graph, that's SUR = 0.6. A low SUR means the schema was over-specified — the LLM invented classes during discovery that don't actually appear in the data. This is the signal that the HITL session should have caught and removed those classes.

<!-- We compute SUR twice — once from the extraction logs and once from Neo4j — and they must agree. If they don't, there's a bug in the graph write. -->

**A3 — Schema Consistency Rate (SCR)**

This is where the paper on benchmarking LLM validation is most relevant. SCR measures how often the LLM, during batch extraction, violates the frozen schema:

```
SCR = 1 - (validation errors / total extracted triples)
```

Because we run a repair loop — we feed errors back to the LLM and ask for a corrected output — we report two values: **SCR pre-repair** (errors on the first pass) and **SCR post-repair** (errors that survive all repair attempts).

The gap between the two tells you how effective the repair loop is. A typical pattern might be: pre-repair 0.87, post-repair 0.96 — meaning the LLM gets 13% of triples wrong initially, but the repair loop recovers most of them.

**A2 — Relation Type Entropy (RTE)**

This is a graph-structure metric computed from Neo4j:

```
RTE = -Σ p(r) × log₂(p(r))    for each relation type r
```

Low entropy means the graph's edges are concentrated on a few relation types — the schema is doing its job of constraining the extraction. OpenIE with no schema produces hundreds of relation types and extremely high entropy. A constrained schema should produce significantly lower entropy. But if entropy is too low — say, 90% of edges are the same type — the schema might be too rigid.

**A4 — Orphan Node Rate (ONR)**

```
ONR = nodes with degree 0 / total nodes
```

An orphan node is an entity that was extracted but never connected to anything. In a knowledge *graph*, an isolated node is essentially useless — you've extracted a name but learned nothing about how it relates to anything else. OpenIE tends to produce many orphans because it extracts entities freely without requiring them to participate in typed relations. A schema-constrained system should produce fewer.

---

## [SLIDE 9] Block C — Generalization

Block C is the critical test of whether the schema generalizes beyond the 10% of documents used during discovery.

**C1 — Unmapped Instance Rate (UIR)**

```
UIR = entities the LLM couldn't assign to any schema class / total extracted entities
```

During extraction, when the LLM encounters a mention it can't fit into any of the defined classes, it puts it in an "unmapped" bucket rather than inventing a new class. UIR measures how full that bucket gets.

Our interpretation thresholds:
- UIR < 5% → good generalization
- UIR 5–20% → the schema is missing some important categories in the validation set
- UIR > 20% → the schema overfit to the discovery documents

The expected direction is: UIR(HITL) < UIR(Zero-Shot). The human refinement should produce a schema that generalizes better.

**C2 — Schema Drift Rate (SDR)**

```
SDR = documents where the LLM proposed a schema change / total documents processed
```

During batch extraction, the LLM is frozen — it can't change the schema. But we instruct it to set a flag if it encounters content it genuinely can't represent. SDR counts how often this happens, at the document level.

UIR and SDR are complementary: UIR is entity-level (this specific mention has no class), SDR is document-level (this whole document is poorly covered by the schema). A document can have zero unmapped entities but still trigger a drift flag if the LLM feels the schema misses the point of the document.

---

## [SLIDE 10] Block D — Downstream Utility

Block D is the most practically meaningful test: does having a knowledge graph actually help answer questions better than just searching the raw text?

The pipeline has four steps. First, for each test document, we generate one factual question from its text using a dedicated LLM prompt. Second, we pass that question to each retrieval system and collect an answer. Third, we judge each answer with an LLM-as-judge that receives the question, the answer, and the first 1000 characters of the source document as evidence — it returns YES, PARTIAL, or NO with a brief justification. Finally, we aggregate: accuracy is computed as (YES + 0.5 × PARTIAL) / total, and the key figure is Δ = Accuracy(HITL) − Accuracy(Plain-RAG). If Δ > 0, the graph adds value.

One methodological choice worth noting: we run on **two test sets**, not one. The first is the top-30 documents by entity count — the documents where the graph is densest, so GraphRAG has the best possible chance. The second is a random sample of 30 documents from the remaining corpus — an unbiased estimate of real-world performance. Comparing the two reveals whether any graph advantage is genuine or only appears where the graph happens to be rich.

We have a first result on the AITA domain, session with 255 extracted documents:

```
              top-30                    rand-30
System        Accuracy   YES  NO        Accuracy   YES  PARTIAL  NO
──────────    ────────   ───  ──        ────────   ───  ───────  ──
Graph-HITL      10.0%     3   27          28.3%     7       3    20
Plain-RAG       70.0%    21    9          61.7%    18       1    11

Δ HITL vs Plain-RAG:  −60.0%            −33.3%
```

This is a clear negative result, and it's diagnostically interesting. Graph-HITL returns "Not enough information in the graph" in 100% of the 60 questions — the retrieval never fires. The reason is structural: in AITA, all entities named "narrator", "boyfriend", "sister" across 255 different stories get merged into a single Neo4j node. That node accumulates edges from every story it appears in. When GraphRAG searches for "narrator", it retrieves a mix of actions from 98 different posts — pure noise, not context.

This failure is domain-specific, not a flaw in the pipeline. AITA entities are anonymous social roles that repeat across every post. Wikipedia Historical Events entities — "Battle of Waterloo", "Napoleon Bonaparte", "Treaty of Ghent" — are named, specific, and unique to their article. There is no cross-document collision. The Wikipedia result, which we will run next, tests whether the graph is useful when this condition holds.

---

## [SLIDE 11] Baselines

For Block D we compare two systems.

**Plain-RAG** is the baseline. For each question, it tokenizes the question, removes stopwords, and computes a Jaccard-like overlap score between the question's tokens and every document in the corpus. It returns the three highest-scoring documents and passes their first 1200 characters to the LLM as context. No embeddings, no vector index, no semantic similarity — deliberately simple. The goal is to establish a retrieval baseline that cannot be accused of benefiting from the same LLM representations used to build the graph.

**Graph-HITL** is the system under evaluation. It extracts up to five search terms from the question, queries Neo4j for nodes whose name contains each term within the session's subgraph, retrieves their one-hop neighborhood as typed triples, and passes those triples to the LLM as structured context.

**Graph-ZeroShot** is an optional ablation. If a separate session was run using only the v0 schema — the one proposed by the LLM before any HITL refinement — we can compare it against Graph-HITL on the same questions. This isolates the contribution of the conversational loop: does the human-refined schema produce a graph that is more useful downstream than the zero-shot schema?

The expected ordering across all metrics — and the hypotheses we are actually testing:

```
SCR:    HITL ≥ Zero-Shot    (refined schema → fewer validation errors)
SUR:    HITL ≥ Zero-Shot    (refined schema → fewer unused classes)
UIR:    HITL ≤ Zero-Shot    (refined schema → fewer unmapped entities)
SDR:    HITL ≤ Zero-Shot    (refined schema → less drift during extraction)
QA(Δ): HITL ≥ Zero-Shot > 0 (on entity-specific domains)
```

All of these are falsifiable. If HITL does not outperform Zero-Shot on schema quality metrics, that means the conversational refinement did not add value — a negative result, but a scientifically valid and publishable one.

---

## [SLIDE 12] Two Domains, One Hypothesis

We run on two corpora: **Reddit AITA posts** and **Wikipedia Historical Events articles**. The choice is intentional — they have very different structural properties.

Wikipedia History is a structured factual domain with consistent vocabulary (battles, treaties, sieges, revolutions). Two different users working independently on the same data should discover similar schemas — participants, dates, outcomes, locations. AITA is unstructured social narrative — much more subjective, much more ambiguous. Two users working on AITA might produce very different schemas.

This is what Block E (inter-session agreement) tests. The hypothesis is:

```
ISA(Wikipedia) >> ISA(AITA)
```

If true, it tells us something fundamental about how much of schema structure is domain-inherent versus user-dependent.

---

## [SLIDE 13] What's Built, What's Next

The infrastructure is in place. The backend logs every extraction result, every HITL turn, every LLM call — into structured JSONL files that can be queried without running the server. All metrics for Blocks A, B, and C are computable automatically from these logs. **Block D is now also implemented** — `evaluation/qa_eval.py` runs the full QA evaluation pipeline as a standalone script, with both GraphRAG and Plain-RAG baselines and an LLM-as-judge.

What's been built this week:
- **Wikipedia Historical Events corpus** (500 articles, ≤2000 chars) as the second domain
- **Block D evaluation script** (`qa_eval.py`): question generation → GraphRAG vs Plain-RAG → LLM judge → accuracy table
- **Extraction prompt optimizations**: compact schema format (90% token reduction), `EXTRACTION_MAX_TOKENS=1000`, separate extraction model routing
- **GIV dangling-relation fix**: post-extraction semantic check removes relations with non-existent entity IDs

The timeline:
- **Current** — first Block D run on session `019a7bb6` (AITA, 255 docs)
- **Next week** — run Wikipedia History session + Block D; collect both domains' results
- **Week after** — comparison tables, convergence plots, write-up

That's the plan. Questions?

---

*[End of script — estimated delivery: 12–13 minutes at measured pace]*
