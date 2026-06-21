import type { Conflict } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const SEVERITY_DOT: Record<Conflict["severity"], string> = {
  info: "bg-[hsl(var(--info))]",
  warning: "bg-[hsl(var(--warning))]",
  error: "bg-destructive",
};

const TYPE_VARIANT: Record<Conflict["type"], "info" | "warning" | "muted" | "secondary" | "destructive"> = {
  override: "secondary",
  "2da": "info",
  dialog: "warning",
  module: "muted",
  declared: "destructive",
};

export function ConflictCard({ conflict }: { conflict: Conflict }) {
  return (
    <div className="rounded-lg border bg-card/40 p-4">
      <div className="flex items-center gap-2">
        <span className={cn("size-2 shrink-0 rounded-full", SEVERITY_DOT[conflict.severity])} />
        <code className="flex-1 truncate font-mono text-sm text-foreground" title={conflict.resource}>
          {conflict.resource}
        </code>
        <Badge variant={TYPE_VARIANT[conflict.type]}>{conflict.type}</Badge>
      </div>
      <ul className="mt-3 space-y-1.5 pl-4">
        {conflict.participants.map((p) => {
          const winner = conflict.winner_mod_id === p.mod_id;
          return (
            <li key={p.mod_id} className="flex items-center gap-2 text-sm">
              <span
                className={cn(
                  "flex-1 truncate",
                  winner ? "font-medium text-foreground" : "text-muted-foreground",
                  !p.enabled && "line-through opacity-60"
                )}
                title={p.mod_name}
              >
                {p.mod_name}
              </span>
              {winner && <Badge variant="success">wins</Badge>}
              {!p.enabled && <Badge variant="muted">disabled</Badge>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
