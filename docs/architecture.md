# System Architecture

## Tech Stack
*   **Frontend:** React + Vite + TailwindCSS.
*   **Backend:** FastAPI (Python).
*   **LLM Engine:** Custom Python module using `LiteLLM` (for multi-provider support) and `Pydantic` (for JSON output validation).
*   **Graph Database:** Neo4j.

## High-Level Component Diagram

```text
[ React Frontend ] 
  │   │   │
  │   │   └─> Chat UI (User negotiations)
  │   │   └─> GraphView (react-force-graph preview)
  │   │   └─> SchemaEditor (Approve/Reject changes)
  │   ▼
[ FastAPI Backend ]
  │   │   │
  │   │   ├─> /chat (Handles conversation state)
  │   │   ├─> /graph (CRUD API for Neo4j operations)
  │   │   └─> /extraction (Triggers batch jobs)
  │   ▼
[ LLM Engine (Python + LiteLLM) ] <------> [ Raw/Processed Data ]
  │   │
  │   ├─> Prompt Builder
  │   ├─> LiteLLM Calls
  │   └─> Pydantic Parsers
  │
  ▼
[ Neo4j Graph Database ]
      └─> Cypher queries executed by the Backend to persist nodes/edges.