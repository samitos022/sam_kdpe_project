import { Badge } from "../ui/Badge";
import type { Schema } from "../../types";
import { EntityClassCard } from "./EntityClassCard";
import { RelationTypeCard } from "./RelationTypeCard";

// ─── SchemaPanel ─────────────────────────────────────────────────────────────

interface SchemaPanelProps {
  schema: Schema;
}

export function SchemaPanel({ schema }: SchemaPanelProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          Schema v{schema.version}
        </h2>
        <div className="flex gap-2">
          <Badge className="bg-violet-50 text-violet-700 border-violet-200">
            {schema.entity_classes.length} classes
          </Badge>
          <Badge className="bg-teal-50 text-teal-700 border-teal-200">
            {schema.relation_types.length} relations
          </Badge>
          {schema.frozen && (
            <Badge className="bg-amber-50 text-amber-700 border-amber-200">frozen</Badge>
          )}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-400">
          Entity classes
        </p>
        <div className="grid grid-cols-1 gap-2">
          {schema.entity_classes.map((cls) => (
            <EntityClassCard key={cls.name} cls={cls} />
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-400">
          Relation types
        </p>
        <div className="grid grid-cols-1 gap-2">
          {schema.relation_types.map((rel) => (
            <RelationTypeCard key={rel.name} rel={rel} />
          ))}
        </div>
      </div>
    </div>
  );
}