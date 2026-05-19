// ─── TBox ────────────────────────────────────────────────────────────────────

export interface EntityClass {
  name: string;
  description: string;
  examples: string[];
}

export interface RelationType {
  name: string;
  domain: string;
  range: string;
  description: string;
}

export interface Schema {
  version: number;
  domain: string;
  entity_classes: EntityClass[];
  relation_types: RelationType[];
  created_at: string;
  frozen: boolean;
}

// ─── HITL ────────────────────────────────────────────────────────────────────

export type EditType =
  | "add_class"
  | "remove_class"
  | "merge_classes"
  | "rename_class"
  | "add_relation"
  | "remove_relation"
  | "rename_relation"
  | "update_description";

export interface SchemaEdit {
  edit_type: EditType;
  target: string;
  value: string | null;
  reason: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  message: string;
}

// ─── Session ─────────────────────────────────────────────────────────────────

export interface ExtractionMetrics {
  total_entities: number;
  total_relations: number;
  total_unmapped: number;
  total_repairs: number;
  schema_drift_count: number;
}

export interface ExtractionStatus {
  status: "not_started" | "running" | "done" | "failed";
  processed: number;
  total: number;
  errors: Array<{ doc_id: string; error: string }>;
  metrics: ExtractionMetrics;
  uir: number;
  sdr: number;
  progress_pct: number;
}

export interface Session {
  session_id: string;
  domain: string;
  schema: Schema;
  schema_version: number;
  delta_history: number[];
  converged: boolean;
  frozen: boolean;
  n_discovery_docs: number;
  n_validation_docs: number;
  extract_status: ExtractionStatus;
  n_turns: number;
}

// ─── Chat responses ───────────────────────────────────────────────────────────

export interface ChatResponse {
  schema: Schema;
  schema_version: number;
  explanation: string;
  edits_applied: SchemaEdit[];
  delta_s: number;
  questions: string[];
  converged: boolean;
  summary: Record<string, unknown>;
}

export interface CreateSessionResponse {
  session_id: string;
  domain: string;
  schema: Schema;
  n_discovery_docs: number;
  n_validation_docs: number;
  message: string;
}

// ─── Graph ───────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  labels: string[];
  name: string;
  confidence?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  predicate: string;
  confidence?: number;
}

export interface GraphStats {
  n_nodes: number;
  n_edges: number;
  class_counts: Record<string, number>;
  relation_counts: Record<string, number>;
  orphan_count: number;
  orphan_rate: number;
  relation_entropy: number;
}

export interface SchemaUtilization {
  session_id: string;
  schema_version: number;
  sur: number;
  n_schema_classes: number;
  n_populated_classes: number;
  populated_classes: Record<string, number>;
  unpopulated_classes: string[];
  relation_sur: number;
  n_schema_relations: number;
  n_populated_relations: number;
  unpopulated_relations: string[];
  relation_entropy: number;
  orphan_rate: number;
  orphan_count: number;
  total_nodes: number;
  total_edges: number;
}

// ─── UI state ────────────────────────────────────────────────────────────────

export type AppView = "home" | "chat" | "extraction" | "graph";

export interface AppState {
  sessionId: string | null;
  view: AppView;
}