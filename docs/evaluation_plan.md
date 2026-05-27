# Evaluation Plan — Step-by-Step Implementation Guide

Questo documento è un piano operativo sequenziale: ogni fase spiega cosa misura la metrica, come funziona internamente nel codice, e come verificare che produca risultati sensati.

**Ordine obbligatorio:** ogni fase dipende dalla precedente.

```
Phase 0 → Setup del sistema
Phase 1 → Block B: Convergenza (durante il chat HITL)
Phase 2 → Block A+C: Metriche da log (dopo l'estrazione)
Phase 3 → Block A: Metriche da Neo4j (dopo l'estrazione)
Phase 4 → Block D: QA downstream
Phase 5 → Block E: Variabilità multi-sessione (opzionale)
```

---

## Phase 0 — Setup

### 0.1 Avvia il sistema

```bash
cd code
docker compose up -d
```

Controlla che tutti e tre i servizi siano up:

```bash
docker compose ps
# neo4j, backend, frontend devono essere "running"
```

Verifica l'health dell'API:

```bash
curl http://localhost:8000/health
# atteso: {"api": "ok", "neo4j": true}
```

### 0.2 Prepara i dati

Posiziona i file JSONL in `code/data/processed/`:
- `aita.jsonl` — ogni riga è un post Reddit con campi `title`, `text`
- `wikipedia_history.jsonl` — ogni riga è un articolo Wikipedia con campi `title`, `summary`

Verifica che il backend li legga:

```bash
curl http://localhost:8000/
# "domains": ["aita", "wikipedia_history"] deve essere nella risposta
```

### 0.3 Crea una sessione di test

```bash
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"domain": "aita", "discovery_fraction": 0.1}'
```

Risposta attesa (salva il `session_id`):

```json
{
  "session_id": "a1b2c3d4",
  "schema": { "version": 0, "entity_classes": [...], "relation_types": [...] },
  "n_discovery_docs": 50,
  "n_validation_docs": 450
}
```

> **Cosa succede internamente:** `discover_schema()` in `llm_engine/core.py` chiama l'LLM con `DISCOVERY_SYSTEM` + i testi dei 50 documenti discovery. Il risultato è la Schema v0, salvata in `logs/schemas/{sid}_schema_v0.json`.

---

## Phase 1 — Block B: Convergenza HITL

> **Obiettivo:** verificare che la conversazione faccia *convergere* lo schema, cioè che le modifiche per turno diminuiscano fino a stabilizzarsi.

### B1 — Schema Edit Distance (ΔS_t)

**Cosa misura:** quanto cambia lo schema a ogni turno di chat. Un valore alto = molte modifiche, basso = lo schema si sta stabilizzando.

**Formula:**
```
ΔS_t = Σ (peso_i × numero_edit_tipo_i)

Pesi:
  add/remove class o relation = 1.0
  rename                       = 0.5
  merge                        = 2.0   ← distrugge info, pesa doppio
  update_description           = 0.2   ← quasi gratis
```

**Come testarlo — step by step:**

**Step 1.** Manda il primo messaggio di raffinamento:

```bash
curl -X POST http://localhost:8000/sessions/a1b2c3d4/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "aggiungi una classe TimeStamp per indicare quando avvengono gli eventi"}'
```

Nella risposta, guarda `delta_s`:

```json
{
  "schema_version": 1,
  "delta_s": 1.0,
  "edits_applied": [
    {"edit_type": "add_class", "target": "TimeStamp", ...}
  ]
}
```

`delta_s = 1.0` perché è stata aggiunta 1 classe (peso 1.0).

**Step 2.** Manda altri messaggi e osserva la serie ΔS_t:

```bash
# Turno 2: rename
curl -X POST http://localhost:8000/sessions/a1b2c3d4/chat \
  -d '{"message": "rinomina TimeStamp in TemporalReference"}'
# delta_s atteso: 0.5 (rename pesa 0.5)

# Turno 3: piccola modifica descrizione
curl -X POST http://localhost:8000/sessions/a1b2c3d4/chat \
  -d '{"message": "aggiorna la descrizione di TemporalReference per renderla più precisa"}'
# delta_s atteso: 0.2 (update_description)
```

**Step 3.** Recupera la serie storica:

```bash
curl http://localhost:8000/sessions/a1b2c3d4/history
```

```json
{
  "delta_history": [1.0, 0.5, 0.2],
  "converged": false,
  "convergence_turn": null
}
```

**Convergenza T\*:** viene dichiarata quando `delta_s < 1.0` per 3 turni consecutivi. Nel log file:

```
logs/schemas/a1b2c3d4_session.json → campo "converged" e "convergence_turn"
```

**Cosa aspettarsi:** una curva decrescente. Se vedi oscillazioni (1.0 → 3.0 → 0.5 → 2.0) significa che l'utente e l'LLM non si capiscono — è comunque un risultato scientificamente valido.

---

### B2 — User Acceptance Rate (UAR)

**Cosa misura:** quante proposte dell'LLM l'utente accetta senza modifiche. Un UAR alto = l'LLM capisce subito cosa vuole l'utente.

**Formula:**
```
UAR = proposte accettate as-is / totale proposte con etichetta
```

**Come funziona nel codice:** ogni `ConversationTurn` ha un campo `user_acceptance` che viene impostato sul turno successivo interpretando la risposta dell'utente:
- `"accepted"` — l'utente ha detto "ok", "sì", "perfetto", ecc.
- `"modified"` — l'utente ha accettato ma chiesto una modifica
- `"rejected"` — l'utente ha detto "no", "non va", ecc.

> **Attenzione:** `user_acceptance` viene popolato dall'LLM che interpreta il messaggio successivo. Se il messaggio è ambiguo, potrebbe non essere impostato. Per questo il calcolo in `metrics.py` usa solo i turni *con etichetta*.

**Come testarlo:**

Dopo aver completato la sessione HITL e freeze, leggi il file di sessione:

```bash
cat logs/schemas/a1b2c3d4_session.json | python3 -c "
import json, sys
from evaluation.metrics import compute_convergence_metrics
data = json.load(sys.stdin)
print(json.dumps(compute_convergence_metrics(data), indent=2))
"
```

Output atteso:

```json
{
  "n_turns": 5,
  "delta_series": [1.0, 0.5, 0.2, 0.2, 0.0],
  "delta_mean": 0.38,
  "delta_final": 0.0,
  "converged": true,
  "convergence_turn": 5,
  "n_proposals_with_acceptance_label": 4,
  "uar": 0.75,
  "n_accepted": 3,
  "n_modified": 1,
  "n_rejected": 0
}
```

---

### Fine Phase 1: Freeze

Quando sei soddisfatto dello schema:

```bash
curl -X POST http://localhost:8000/sessions/a1b2c3d4/freeze
```

Da questo momento lo schema è bloccato. Il file `logs/schemas/a1b2c3d4_schema_vN.json` con `"frozen": true` viene scritto.

---

## Phase 2 — Block A3 / C1 / C2: Metriche dai Log di Estrazione

> **Prerequisito:** schema frozen. Avvia l'estrazione batch:

```bash
curl -X POST http://localhost:8000/sessions/a1b2c3d4/extract
```

Poi monitora il progresso:

```bash
curl http://localhost:8000/sessions/a1b2c3d4/extract/status
```

Mentre gira, ogni documento estratto viene appeso a:
```
logs/eval/a1b2c3d4/extraction_results.jsonl
```

Ogni riga è un `ExtractionResult` completo (entità, relazioni, errori, unmapped, flag di drift).

---

### A3 — Schema Consistency Rate (SCR)

**Cosa misura:** quante volte il frozen schema viene violato durante l'estrazione. Misura la *robustezza* dello schema su dati nuovi.

**Formula:**
```
SCR = 1 - (errori di validazione Pydantic / totale triple estratte)
```

Il GIV repair loop tenta di correggere gli errori. Per questo si riportano **due valori**:
- `scr_pre_repair` — prima che il loop intervenga (quanti errori produce il tiro iniziale dell'LLM)
- `scr_post_repair` — dopo tutti i tentativi di riparazione (quanti sopravvivono)

**Errori tipici che abbassano SCR:**
- `class_name` non presente nello schema → l'LLM ha "inventato" una classe
- `predicate` non presente → l'LLM ha usato una relazione non definita
- `subject_id` o `object_id` che non esiste nelle entities estratte

**Come leggere il risultato:**

Dopo che l'estrazione è completa, guarda `session_summary.json`:

```bash
cat logs/eval/a1b2c3d4/session_summary.json
```

```json
{
  "scr_pre_repair":  0.87,
  "scr_post_repair": 0.96,
  "pre_repair_errors": 52,
  "post_repair_errors": 16,
  "mean_repair_iterations": 0.4,
  "std_repair_iterations": 0.6
}
```

**Interpretazione:**
- `scr_pre = 0.87` → l'LLM sbaglia nel 13% delle triple al primo tentativo
- `scr_post = 0.96` → il repair loop ne salva la metà, rimane 4% di errori irrecuperabili
- `mean_repair_iterations = 0.4` → in media quasi nessun documento richiede riparazione; la distribuzione è asimmetrica (la maggior parte ha 0, pochi ne hanno 2-3)

**Confronto atteso con le baseline:**
```
SCR(HITL) > SCR(Zero-Shot) — lo schema raffinato viola meno il corpus
```

---

### C1 — Unmapped Instance Rate (UIR)

**Cosa misura:** quante entità estratte dai documenti di *validazione* non rientrano in nessuna classe dello schema. È la metrica più importante per la generalizzazione.

**Formula:**
```
UIR = entità senza classe schema / totale entità estratte
```

**Come funziona nel codice:** durante l'estrazione, quando l'LLM incontra qualcosa che non sa dove mettere, lo inserisce in `ExtractionResult.unmapped_entities` come stringa (il surface form dell'entità). Questi vengono contati da `EvaluationLogger.finalize()`.

**Come leggerlo:**

```bash
cat logs/eval/a1b2c3d4/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'UIR: {d[\"uir\"]:.1%}')
print(f'Unmapped: {d[\"total_unmapped\"]} su {d[\"total_entities\"]} entità')
"
```

**Interpretazione:**
- `UIR < 5%` → lo schema generalizza bene
- `UIR 5-20%` → lo schema manca alcune categorie importanti nel corpus di validazione
- `UIR > 20%` → **overfitting** sul discovery set: lo schema è troppo specifico per quei 50 documenti

**Confronto atteso:**
```
UIR(HITL) < UIR(Zero-Shot GIV) — il raffinamento produce uno schema più generale
```

Se questo non si verifica, è un risultato negativo ma comunque valido scientificamente.

---

### C2 — Schema Drift Rate (SDR)

**Cosa misura:** quante volte l'LLM, durante l'estrazione batch, *propone di modificare* lo schema frozen perché non riesce a fittare quello che trova. Misura il disallineamento schema↔corpus a livello documento.

**Formula:**
```
SDR = documenti con proposta di modifica / totale documenti processati
```

**Come funziona nel codice:** nel prompt di estrazione (`EXTRACTION_SYSTEM`), l'LLM viene istruito a settare `schema_modification_proposed = true` se incontra contenuto che non riesce a rappresentare con lo schema attuale. Questo viene loggato in `ExtractionResult.schema_modification_proposed`.

**Come leggerlo:**

```bash
cat logs/eval/a1b2c3d4/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'SDR: {d[\"sdr\"]:.1%}')
print(f'Drift in {d[\"schema_drift_count\"]} su {d[\"total_documents\"]} documenti')
"
```

**Interpretazione:** SDR e UIR sono complementari:
- UIR misura fallimenti a livello *entità* (questa specifica entità non ha una classe)
- SDR misura fallimenti a livello *schema* (questo documento intero non si adatta)

Un SDR alto con UIR basso significa che ci sono documenti "fuori schema" ma le entità che riesce ad estrarre vanno bene.

---

### A1 — Schema Utilization Rate (SUR) dai log

**Cosa misura:** quante classi dello schema frozen hanno almeno un'istanza estratta. Uno schema con molte classi mai popolate è stato over-generato durante la discovery.

**Formula:**
```
SUR = |classi con almeno 1 istanza| / |classi totali nello schema|
```

**Come leggerlo dai log:**

```bash
cat logs/eval/a1b2c3d4/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'SUR: {d[\"sur\"]:.1%}  ({d[\"n_populated_classes\"]}/{d[\"n_schema_classes\"]} classi popolate)')
print('Classi popolate:', d['populated_classes'])
print('Classi vuote:   ', d['unpopulated_classes'])
"
```

> Nota: SUR viene calcolato anche da Neo4j (`/graph/schema_utilization`). I due risultati devono coincidere — se divergono c'è un bug nel write su Neo4j.

---

### Endpoint tutto-in-uno

Quando l'estrazione è finita, recupera tutte le metriche B1/B2/A1/A3/C1/C2 con una sola chiamata:

```bash
curl http://localhost:8000/sessions/a1b2c3d4/eval | python3 -m json.tool
```

---

## Phase 3 — Block A: Metriche da Neo4j

> **Prerequisito:** Neo4j deve essere up (`docker compose ps`).

Queste metriche richiedono la struttura del grafo (gradi dei nodi, distribuzione degli archi) e non possono essere calcolate solo dai log.

---

### A2 — Relation Type Entropy (RTE)

**Cosa misura:** quanto è *distribuita* l'informazione sulle relazioni. OpenIE produce centinaia di tipi di relazione diversi → entropia alta. Uno schema vincolato concentra gli archi su pochi tipi → entropia bassa.

**Formula:**
```
RTE = -Σ p(r) × log₂(p(r))    per ogni tipo di relazione r

p(r) = archi di tipo r / totale archi
```

**Esempio intuitivo:**
- Se il 100% degli archi è `treats` → RTE = 0 (nessuna diversità)
- Se 8 tipi di relazione sono equamente distribuiti (12.5% ciascuno) → RTE = 3.0 bits
- OpenIE con 500 tipi di relazione → RTE >> 5 bits

**Come leggerlo:**

```bash
curl "http://localhost:8000/graph/stats?session_id=a1b2c3d4"
```

```json
{
  "n_nodes": 3200,
  "n_edges": 5400,
  "relation_counts": {
    "TREATS": 890,
    "CAUSED_BY": 430,
    "INVOLVES_ACTOR": 210,
    ...
  },
  "relation_entropy": 2.31
}
```

**Interpretazione:** non esiste un valore "buono" in assoluto. Il confronto tra sistemi è ciò che conta:
```
RTE(OpenIE) >> RTE(Zero-Shot) > RTE(HITL)
```
Se RTE(HITL) è molto basso (< 1.0), significa che quasi tutti gli archi sono dello stesso tipo → lo schema è troppo rigido.

---

### A4 — Orphan Node Rate (ONR)

**Cosa misura:** quanti nodi nel grafo non hanno nessun arco. Un nodo orfano è un'entità estratta ma mai messa in relazione con nessun'altra — informazione inutile nel grafo.

**Formula:**
```
ONR = nodi con grado 0 / totale nodi
```

**Causa tipica degli orfani:** l'LLM ha estratto un'entità (es. il nome di una persona) ma non ha trovato nessuna relazione che la coinvolga nei vincoli schema. Con OpenIE è comune perché il soggetto può essere estrto anche senza predicato tipizzato.

**Come leggerlo:**

```bash
curl "http://localhost:8000/graph/stats?session_id=a1b2c3d4"
# campo "orphan_rate" e "orphan_count"
```

**Interpretazione:**
```
ONR(OpenIE) >> ONR(Zero-Shot) > ONR(HITL)
```

ONR alto + SUR basso = lo schema estrae entità isolate senza riuscire a connetterle.

---

### A1 — SUR da Neo4j (cross-check)

```bash
curl "http://localhost:8000/graph/schema_utilization?session_id=a1b2c3d4"
```

Confronta `sur` e `relation_sur` con quelli calcolati dai log in Phase 2. Devono essere identici o quasi (piccole differenze possibili per via del MERGE idempotente su Neo4j).

---

## Phase 4 — Block D: QA Downstream

> **Obiettivo:** misurare se il grafo HITL risponde meglio a domande fattuali rispetto ai baseline.

Block D è implementato come script standalone in `evaluation/qa_eval.py`. Vedi `docs/block_d_qa_eval.md` per la documentazione completa.

### Comando base

```bash
cd /home/sam/Documents/uni/kdpe/sam_kdpe_project/code

../.venv/bin/python3 evaluation/qa_eval.py \
    --session  <hitl_session_id> \
    --domain   aita
```

### Con baseline Zero-Shot (ablation)

```bash
../.venv/bin/python3 evaluation/qa_eval.py \
    --session          <hitl_session_id> \
    --domain           aita \
    --zeroshot-session <zeroshot_session_id>
```

### Output

Lo script scrive in `logs/eval/<session_id>/`:

| File | Contenuto |
|---|---|
| `qa_results.jsonl` | Una riga per ogni (doc, domanda, sistema): domanda, risposte, verdetti |
| `qa_summary.json` | Metriche aggregate: accuracy, YES/PARTIAL/NO, Δ HITL vs Plain-RAG |

### Interpretazione

```
Δ = Accuracy(Graph-HITL) − Accuracy(Plain-RAG)

Δ > 0  → il grafo aggiunge valore rispetto al testo grezzo (risultato positivo)
Δ ≤ 0  → il grafo non aiuta (risultato negativo, ma scientificamente valido)
```

### Prerequisiti

1. Neo4j attivo con i nodi della sessione caricati (`curl http://localhost:8000/health`)
2. `logs/eval/<session_id>/extraction_results.jsonl` deve esistere
3. `data/processed/<domain>.jsonl` deve essere presente

---

## Phase 5 — Block E: Variabilità Multi-Sessione (opzionale)

> **Prerequisito:** almeno 2 sessioni indipendenti sullo stesso discovery set, condotte da persone diverse.

### ISA — Inter-Session Schema Agreement

**Cosa misura:** quanto sono simili due schemi prodotti da utenti diversi sugli stessi dati. Alta ISA = il dominio ha una struttura "oggettiva" che l'LLM trova; bassa ISA = la struttura è soggettiva.

**Come calcolarlo:**

```python
# Jaccard similarity sui nomi delle relazioni
schema_A_relations = {"treats", "caused_by", "involves_actor"}
schema_B_relations = {"treats", "causes", "has_symptom", "involves_actor"}

intersection = schema_A_relations & schema_B_relations  # {"treats", "involves_actor"}
union        = schema_A_relations | schema_B_relations  # tutti e 4

jaccard = len(intersection) / len(union)  # 2/4 = 0.5
```

Per le classi (nomi semantici, non identici), usa BERTScore o embeddings per similarità fuzzy.

**Confronto atteso:**
```
ISA(Wikipedia) > ISA(AITA)
```
Wikipedia History ha vocabolario storico/fattuale standardizzato → diversi utenti convergeranno su schemi simili.
AITA è dominio ambiguo → schemi molto diversi tra utenti diversi.

---

## Tabella Riepilogativa

| Metrica | Phase | Fonte dati | Endpoint / File | Implementata |
|---|---|---|---|---|
| B1 — ΔS_t | 1 | `_session.json` | `GET /sessions/{id}/history` | ✅ |
| B2 — UAR | 1 | `_session.json` | `GET /sessions/{id}/eval` | ✅ |
| A3 — SCR | 2 | `extraction_results.jsonl` | `GET /sessions/{id}/eval` | ✅ |
| C1 — UIR | 2 | `extraction_results.jsonl` | `GET /sessions/{id}/eval` | ✅ |
| C2 — SDR | 2 | `extraction_results.jsonl` | `GET /sessions/{id}/eval` | ✅ |
| A1 — SUR | 2+3 | log + Neo4j | `GET /sessions/{id}/eval` + `/graph/schema_utilization` | ✅ |
| A2 — RTE | 3 | Neo4j | `GET /graph/stats` | ✅ |
| A4 — ONR | 3 | Neo4j | `GET /graph/stats` | ✅ |
| D1 — QA | 4 | LLM judge | `evaluation/qa_eval.py` | ✅ |
---

## Osservare le Metriche dai Log

Dopo aver eseguito il sistema, tutti gli artefatti necessari si trovano in `code/logs/`.

### Struttura dei file prodotti

```
code/logs/
├── run.log                          ← log testuale rotante (debug completo)
├── events.jsonl                     ← eventi strutturati JSON, uno per riga
├── schemas/
│   ├── {sid}_schema_v0.json        ← schema versione 0 (discovery)
│   ├── {sid}_schema_vN.json        ← ogni versione successiva al HITL
│   └── {sid}_session.json          ← storico completo sessione (B1, B2)
└── eval/{sid}/
    ├── extraction_results.jsonl     ← un ExtractionResult per documento (A3, C1, C2)
    ├── session_summary.json         ← metriche aggregate (A1, A3, C1, C2)
    ├── qa_results.jsonl             ← Block D: una riga per (doc, domanda, sistema)
    └── qa_summary.json              ← Block D: accuracy aggregata + Δ HITL vs Plain-RAG
```

---

### B1 — ΔS_t: serie di convergenza

**Da API (live):**
```bash
curl http://localhost:8000/sessions/{sid}/history | python3 -m json.tool
# campo "delta_history": [1.0, 0.5, 0.2, ...]
# campo "converged": true/false
# campo "convergence_turn": N
```

**Da file (post-hoc, senza server):**
```bash
cat logs/schemas/{sid}_session.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
turns = [t for t in d['turns'] if t['role'] == 'assistant']
for t in turns:
    print(f'  turn {t[\"turn_id\"]:2d}  delta_s={t.get(\"delta_s\", \"?\")}')
print('converged:', d['converged'], '  convergence_turn:', d.get('convergence_turn'))
"
```

**Da events.jsonl (jq):**
```bash
jq 'select(.event == "refinement_turn") | {turn_id, delta_s, converged}' \
   logs/events.jsonl
```

---

### B2 — UAR: User Acceptance Rate

```bash
cat logs/schemas/{sid}_session.json | python3 -c "
import json, sys
from evaluation.metrics import compute_convergence_metrics
d = json.load(sys.stdin)
print(json.dumps(compute_convergence_metrics(d), indent=2))
"
# Output: n_accepted, n_modified, n_rejected, uar
```

**Da events.jsonl** — distribuzione delle acceptance labels:
```bash
jq 'select(.event == "refinement_turn") | .acceptance' logs/events.jsonl | sort | uniq -c
```

---

### A3 — SCR: Schema Consistency Rate

```bash
cat logs/eval/{sid}/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'SCR pre-repair:  {d[\"scr_pre_repair\"]:.1%}')
print(f'SCR post-repair: {d[\"scr_post_repair\"]:.1%}')
print(f'Errori pre:      {d[\"pre_repair_errors\"]}')
print(f'Errori post:     {d[\"post_repair_errors\"]}')
print(f'Repair medio:    {d[\"mean_repair_iterations\"]:.2f} ± {d[\"std_repair_iterations\"]:.2f}')
"
```

**Documenti che hanno richiesto repair (da events.jsonl):**
```bash
jq 'select(.event == "doc_extracted" and .repair_iterations > 0) |
    {doc_id, repair_iterations, pre_repair_errors, post_repair_errors}' \
   logs/events.jsonl
```

---

### C1 — UIR: Unmapped Instance Rate

```bash
cat logs/eval/{sid}/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'UIR: {d[\"uir\"]:.1%}  ({d[\"total_unmapped\"]} su {d[\"total_entities\"]} entità)')
"
```

---

### C2 — SDR: Schema Drift Rate

```bash
cat logs/eval/{sid}/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'SDR: {d[\"sdr\"]:.1%}  (drift in {d[\"schema_drift_count\"]} su {d[\"total_documents\"]} doc)')
"
```

**Documenti che hanno proposto modifiche allo schema:**
```bash
jq 'select(.event == "doc_extracted" and .schema_drift == true) | .doc_id' \
   logs/events.jsonl
```

---

### A1 — SUR: Schema Utilization Rate

**Da file (log-based):**
```bash
cat logs/eval/{sid}/session_summary.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'SUR classi:    {d[\"sur\"]:.1%}  ({d[\"n_populated_classes\"]}/{d[\"n_schema_classes\"]})')
print(f'SUR relazioni: {d[\"relation_sur\"]:.1%}  ({d[\"n_populated_relations\"]}/{d[\"n_schema_relations\"]})')
print('Classi vuote:', d['unpopulated_classes'])
print('Relazioni non usate:', d['unused_relations'])
"
```

**Da Neo4j (cross-check obbligatorio):**
```bash
curl "http://localhost:8000/graph/schema_utilization?session_id={sid}" | python3 -m json.tool
# I valori sur e relation_sur devono corrispondere a quelli da log (±1%)
```

---

### A2 — RTE e A4 — ONR (solo Neo4j)

```bash
curl "http://localhost:8000/graph/stats?session_id={sid}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'RTE (entropia relazioni): {d[\"relation_entropy\"]:.3f} bits')
print(f'ONR (nodi orfani):        {d[\"orphan_rate\"]:.1%}  ({d[\"orphan_count\"]} nodi)')
print(f'Distribuzione relazioni:  {d[\"relation_counts\"]}')
"
```

---

### Report tutto-in-uno

**Tutte le metriche da log in una sola chiamata:**
```bash
curl http://localhost:8000/sessions/{sid}/eval | python3 -m json.tool
```

**Tutte le metriche da log senza server (post-hoc):**
```bash
python3 -c "
import sys
sys.path.insert(0, 'code')
from evaluation.metrics import load_all_metrics
from pathlib import Path

report = load_all_metrics(
    session_id='{sid}',
    eval_dir=Path('code/logs/eval'),
    schemas_dir=Path('code/logs/schemas'),
)
import json; print(json.dumps(report, indent=2))
"
```

---

### Analisi LLM calls e costi

Ogni chiamata all'LLM è registrata in `events.jsonl`. Per analizzare latency e token usage:

```bash
# Latency media per fase
jq -r 'select(.event == "llm_call") | [.flow, .latency_s] | @tsv' logs/events.jsonl \
  | awk '{sum[$1]+=$2; count[$1]++} END {for(f in sum) print f, sum[f]/count[f]}'

# Token totali usati
jq 'select(.event == "llm_call") | {flow, prompt_tokens, completion_tokens}' \
   logs/events.jsonl | python3 -c "
import json, sys, collections
data = [json.loads(l) for l in sys.stdin if l.strip()]
by_flow = collections.defaultdict(lambda: {'p': 0, 'c': 0, 'n': 0})
for d in data:
    f = d.get('flow', 'unknown')
    by_flow[f]['p'] += d.get('prompt_tokens') or 0
    by_flow[f]['c'] += d.get('completion_tokens') or 0
    by_flow[f]['n'] += 1
for f, v in sorted(by_flow.items()):
    print(f'{f:20s}  calls={v[\"n\"]:3d}  prompt={v[\"p\"]:6d}  completion={v[\"c\"]:5d}')
"
```

---

### Confronto tra sessioni

Per confrontare HITL vs Zero-Shot, lancia due sessioni separate e raccogli i `session_summary.json` di entrambe:

```python
import json
from pathlib import Path

def load_summary(sid):
    return json.loads(Path(f"code/logs/eval/{sid}/session_summary.json").read_text())

hitl     = load_summary("SID_HITL")
zeroshot = load_summary("SID_ZEROSHOT")

metrics = ["scr_post_repair", "uir", "sdr", "sur"]
print(f"{'Metrica':20s}  {'HITL':8s}  {'Zero-Shot':10s}  {'Δ':8s}")
for m in metrics:
    h, z = hitl[m], zeroshot[m]
    print(f"{m:20s}  {h:.4f}    {z:.4f}      {h - z:+.4f}")
```

---

## Checklist di Validità

Prima di riportare i risultati, verifica:

- [ ] SUR dai log == SUR da Neo4j (±1% tolleranza)
- [ ] `delta_series` in `_session.json` ha la stessa lunghezza di `n_turns` nell'history
- [ ] `extraction_results.jsonl` ha esattamente `n_validation_docs` righe
- [ ] `scr_post_repair >= scr_pre_repair` sempre (il repair non peggiora mai)
- [ ] `uir >= 0` e `sdr >= 0` (non possono essere negativi)
- [ ] Per ogni sessione di baseline (Zero-Shot), i log sono nella stessa struttura `logs/eval/{sid}/`