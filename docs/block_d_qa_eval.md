# Block D — Downstream QA Evaluation

## Cosa misura

Block D risponde alla domanda centrale del progetto: **il grafo estratto con HITL aiuta davvero a rispondere a domande fattuali, rispetto al semplice recupero di testo grezzo?**

La metrica è:
```
Accuratezza = % di risposte giudicate corrette (YES) o parziali (PARTIAL)
Δ = Accuratezza(Graph-HITL) − Accuratezza(Plain-RAG)
```

Se Δ > 0, il grafo aggiunge valore. Se Δ ≤ 0, è un risultato negativo ma scientificamente valido.

---

## Sistemi a confronto

| Sistema | Come recupera il contesto |
|---|---|
| **Graph-HITL** | GraphRAG sul grafo estratto con schema HITL raffinato |
| **Graph-ZeroShot** *(opzionale)* | GraphRAG sul grafo estratto con schema v0 (non raffinato) |
| **Plain-RAG** | Word-overlap sul corpus di testo grezzo (baseline) |

### Come funziona GraphRAG

1. Estrae i termini chiave dalla domanda (rimuove stopword)
2. Per ogni termine, cerca nodi nel grafo Neo4j con `toLower(name) CONTAINS term`
3. Recupera il vicinato a 1-hop di ogni nodo trovato → triple tipizzate
4. Formatta il contesto: `narrator (Person) --[performs_action]--> refusing (Action)`
5. Passa domanda + contesto all'LLM → risposta in 1-3 frasi

### Come funziona Plain-RAG

1. Indicizza tutti i documenti del corpus con un punteggio di overlap lessicale
2. Per ogni domanda, recupera i 3 documenti più rilevanti (Jaccard sui token)
3. Passa domanda + estratti all'LLM → risposta in 1-3 frasi

### Come funziona il giudice

Usa `judge_qa_answer()` (LLM-as-judge) che riceve:
- La domanda
- La risposta generata dal sistema
- Il source passage (primi 1000 char del documento originale)

E restituisce: `YES` / `PARTIAL` / `NO` con motivazione.

L'accuratezza finale è: `(YES + 0.5 × PARTIAL) / totale`.

---

## Due test set

| Set | Come è costruito | Perché |
|---|---|---|
| **top30** | 30 documenti con più entità estratte nel grafo | Favorisce GraphRAG: massimizza le chance che il grafo abbia informazioni |
| **rand30** | 30 documenti campionati casualmente | Stima non-biased della performance reale |

Il confronto tra i due rivela se il grafo è utile solo dove è "denso" o anche in modo generalizzato.

---

## Prerequisiti

Prima di eseguire il Block D:

1. **Sessione HITL completata** — schema raffinato, frozen, e batch extraction terminata
   ```bash
   # Verifica che i log esistano:
   ls logs/eval/<session_id>/extraction_results.jsonl
   ```

2. **Neo4j attivo** con i nodi della sessione caricati
   ```bash
   curl http://localhost:8000/health
   # atteso: {"api": "ok", "neo4j": true}
   ```

3. **Dati processati** disponibili in `data/processed/`
   ```bash
   ls data/processed/
   # aita.jsonl  wikipedia_history.jsonl
   ```

---

## Come eseguire

Lo script gira **fuori Docker**, nel virtualenv del progetto (oppure dentro il container backend).

### Caso base — solo HITL vs Plain-RAG

```bash
cd /home/sam/Documents/uni/kdpe/sam_kdpe_project/code

../.venv/bin/python3 evaluation/qa_eval.py \
    --session  <hitl_session_id> \
    --domain   aita
```

### Con baseline Zero-Shot

Per confrontare anche con il grafo non raffinato, serve una seconda sessione in cui lo schema è stato frozen a v0 senza HITL (o con pochi turni):

```bash
../.venv/bin/python3 evaluation/qa_eval.py \
    --session          <hitl_session_id> \
    --domain           aita \
    --zeroshot-session <zeroshot_session_id>
```

### Con più domande per documento

Default: 1 domanda per documento (30 domande totali per test set). Per aumentare:

```bash
../.venv/bin/python3 evaluation/qa_eval.py \
    --session           <hitl_session_id> \
    --domain            wikipedia_history \
    --questions-per-doc 2
```

### Su Wikipedia History

```bash
../.venv/bin/python3 evaluation/qa_eval.py \
    --session  <hitl_session_id> \
    --domain   wikipedia_history
```

---

## Output

Lo script scrive due file in `logs/eval/<session_id>/`:

### `qa_results.jsonl`
Una riga per ogni (documento, domanda, sistema):

```json
{
  "ts": "2026-05-27T10:00:00+00:00",
  "session_id": "f7a964a0",
  "split": "top30",
  "doc_id": "aita_88",
  "question": "What did the narrator ask the neighbor to do?",
  "answers": {
    "hitl":      "The narrator asked the neighbor not to use the dustbin.",
    "plain_rag": "The narrator made a request regarding the dustbin."
  },
  "verdicts": {
    "hitl":      {"verdict": "YES",     "reason": "Matches source text exactly."},
    "plain_rag": {"verdict": "PARTIAL", "reason": "Vague but directionally correct."}
  }
}
```

### `qa_summary.json`
Metriche aggregate per split e sistema:

```json
{
  "session_id": "f7a964a0",
  "domain": "aita",
  "results": {
    "top30": {
      "hitl":      {"accuracy": 0.70, "yes": 18, "partial": 4, "no": 8,  "total": 30},
      "plain_rag": {"accuracy": 0.55, "yes": 12, "partial": 6, "no": 12, "total": 30},
      "delta_hitl_vs_rag": 0.15
    },
    "rand30": {
      "hitl":      {"accuracy": 0.53, "yes": 13, "partial": 4, "no": 13, "total": 30},
      "plain_rag": {"accuracy": 0.50, "yes": 12, "partial": 3, "no": 15, "total": 30},
      "delta_hitl_vs_rag": 0.03
    }
  }
}
```

Viene stampata anche una tabella riassuntiva a schermo al termine.

---

## Interpretazione dei risultati

| Scenario | Significato |
|---|---|
| Δ(top30) > 0, Δ(rand30) > 0 | Il grafo aiuta in modo generale ✓ |
| Δ(top30) > 0, Δ(rand30) ≈ 0 | Il grafo aiuta solo dove è denso — problema di copertura |
| Δ(top30) ≈ 0, Δ(rand30) ≈ 0 | Il grafo non aggiunge valore rispetto al testo grezzo |
| Graph-HITL > Graph-ZeroShot | Il raffinamento HITL migliora la downstream utility ✓ |

---

## File coinvolti

```
code/
├── evaluation/
│   └── qa_eval.py              ← script principale
├── llm_engine/
│   ├── graphrag.py             ← GraphRAG answer generation
│   └── plain_rag.py            ← Plain-RAG answer generation
└── logs/eval/<session_id>/
    ├── extraction_results.jsonl  ← input (da batch extraction)
    ├── qa_results.jsonl          ← output per-record
    └── qa_summary.json           ← output aggregato
```
