import { useState } from "react";
import { Lightbulb } from "lucide-react";
import { api, type Conflict, type ConflictParticipant } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

export interface ConflictGroup {
  gkey: string;
  participants: ConflictParticipant[];
  items: Conflict[];
  severity: Conflict["severity"];
  winner_mod_id: string | null;
}

const SEVERITY_DOT: Record<Conflict["severity"], string> = {
  info: "bg-[hsl(var(--info))]",
  warning: "bg-[hsl(var(--warning))]",
  error: "bg-destructive",
};

const SEVERITY_BADGE: Record<Conflict["severity"], "info" | "warning" | "destructive"> = {
  info: "info",
  warning: "warning",
  error: "destructive",
};

interface ConflictCardProps {
  group: ConflictGroup;
  profile: string;
  addLog: (message: string, tag?: string) => void;
  onResolved: (conflicts?: Conflict[]) => void;
}

function joinNames(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return `"${names[0]}"`;
  if (names.length === 2) return `"${names[0]}" and "${names[1]}"`;
  return names.slice(0, -1).map(n => `"${n}"`).join(", ") + `, and "${names[names.length - 1]}"`;
}

export function ConflictCard({ group, profile, addLog, onResolved }: ConflictCardProps) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  const { participants, items, severity, winner_mod_id } = group;
  const isDeclared = items[0]?.type === "declared";
  const winner = participants.find(p => p.mod_id === winner_mod_id);
  const losers = winner_mod_id
    ? participants.filter(p => p.mod_id !== winner_mod_id && p.enabled)
    : [];

  // File names from non-declared conflicts (file-level conflicts only).
  const files = items.filter(c => c.type !== "declared").map(c => c.resource);

  // Description and recommendation come from the first representative conflict.
  const description = items[0]?.description ?? "";
  const recommendation = items[0]?.recommendation ?? "";

  // Title: mod names as the primary identifier, not the filename.
  const modNames = participants.map(p => p.mod_name);
  const title = isDeclared
    ? `Incompatible: ${joinNames(modNames)}`
    : joinNames(modNames);

  // File list display: show up to 3 inline, then "and N more".
  const MAX_FILES = 3;
  const fileDisplay = files.length === 0 ? null
    : files.length === 1 ? `File: ${files[0]}`
    : files.length <= MAX_FILES
      ? `${files.length} files: ${files.join(", ")}`
      : `${files.length} files: ${files.slice(0, MAX_FILES).join(", ")} and ${files.length - MAX_FILES} more`;

  const disableMods = async (modIds: string[]) => {
    if (busy || !profile || modIds.length === 0) return;
    setBusy(true);
    try {
      let latest: Conflict[] | undefined;
      for (const id of modIds) {
        const r = await api.libraryDisable(profile, id);
        if (r.conflicts) latest = r.conflicts;
      }
      const names = modIds
        .map(id => participants.find(p => p.mod_id === id)?.mod_name ?? id)
        .join(", ");
      addLog(t("conflicts.resolvedLog", { mods: names }), "success");
      onResolved(latest);
    } catch (e: any) {
      addLog(t("conflicts.resolveFailed", { error: e?.message ?? "error" }), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border bg-card/40 p-4">
      {/* Header: mod names as the title */}
      <div className="flex items-start gap-2">
        <span className={cn("mt-1 size-2 shrink-0 rounded-full", SEVERITY_DOT[severity])} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground" title={title}>
            {title}
          </p>
          {fileDisplay && (
            <p className="mt-0.5 truncate text-xs text-muted-foreground" title={files.join(", ")}>
              {fileDisplay}
            </p>
          )}
        </div>
        <Badge variant={SEVERITY_BADGE[severity]} className="shrink-0">{severity}</Badge>
      </div>

      {/* Plain-English explanation from the backend */}
      {description && (
        <p className="mt-2.5 text-sm leading-relaxed text-foreground">{description}</p>
      )}

      {/* Recommendation */}
      {recommendation && (
        <div className="mt-2.5 flex items-start gap-2 rounded-md border border-[hsl(var(--info)/0.3)] bg-[hsl(var(--info)/0.08)] p-2.5">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-[hsl(var(--info))]" />
          <p className="text-sm text-muted-foreground">{recommendation}</p>
        </div>
      )}

      {/* Resolution: winner vs losers */}
      {winner && losers.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          <Button size="sm" disabled={busy} onClick={() => disableMods(losers.map(p => p.mod_id))}>
            {t("conflicts.keepWinner", { mod: winner.mod_name })}
          </Button>
          {losers.map(p => (
            <Button key={p.mod_id} size="sm" variant="outline" disabled={busy}
              onClick={() => disableMods([p.mod_id])}>
              {t("conflicts.disableMod", { mod: p.mod_name })}
            </Button>
          ))}
        </div>
      )}

      {/* Resolution: declared incompatibility (no winner, just disable one) */}
      {!winner_mod_id && participants.some(p => p.enabled) && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          {participants.filter(p => p.enabled).map(p => (
            <Button key={p.mod_id} size="sm" variant="outline" disabled={busy}
              onClick={() => disableMods([p.mod_id])}>
              {t("conflicts.disableMod", { mod: p.mod_name })}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
