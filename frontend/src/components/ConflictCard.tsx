import { useState } from "react";
import { ChevronDown, ChevronUp, Lightbulb } from "lucide-react";
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
  same_build?: boolean;
}

interface ConflictCardProps {
  group: ConflictGroup;
  profile: string;
  addLog: (message: string, tag?: string) => void;
  onResolved: (conflicts?: Conflict[]) => void;
}

function joinNames(names: string[]): string {
  const u = [...new Set(names)];
  if (u.length === 0) return "";
  if (u.length === 1) return `"${u[0]}"`;
  if (u.length === 2) return `"${u[0]}" and "${u[1]}"`;
  return u.slice(0, -1).map(n => `"${n}"`).join(", ") + `, and "${u[u.length - 1]}"`;
}

// Shared button style used inside conflict cards.
const BTN_BASE =
  "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-[11px] transition-colors";

export function ConflictCard({ group, profile, addLog, onResolved }: ConflictCardProps) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const { participants, items, severity, winner_mod_id } = group;
  const isDeclared = items[0]?.type === "declared";
  const sameBuild = group.same_build ?? items[0]?.same_build ?? false;
  const winner = participants.find(p => p.mod_id === winner_mod_id);
  const losers = winner_mod_id
    ? participants.filter(p => p.mod_id !== winner_mod_id && p.enabled)
    : [];

  const files = items.filter(c => c.type !== "declared").map(c => c.resource);
  const description = items[0]?.description ?? "";
  const recommendation = items[0]?.recommendation ?? "";
  const modNames = participants.map(p => p.mod_name);

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

  // ---- Load-order / file-sharing notes (info severity) ----
  // These are expected in curated builds. Show them collapsed with minimal
  // visual weight; no action buttons.
  if (!isDeclared && severity === "info") {
    return (
      <div className="rounded-lg border bg-card/20 p-3 transition-opacity">
        <div className="flex items-center gap-2">
          <span className="size-1.5 shrink-0 rounded-full bg-[hsl(var(--info))]" />
          <p className="min-w-0 flex-1 truncate text-sm text-muted-foreground" title={modNames.join(", ")}>
            {joinNames(modNames)}
          </p>
          {sameBuild && (
            <Badge variant="info" className="shrink-0 text-[10px]">{t("conflicts.sameBuild")}</Badge>
          )}
          <Badge variant="info" className="shrink-0 text-[10px]">{t("conflicts.noActionNeeded")}</Badge>
          <button
            onClick={() => setExpanded(v => !v)}
            className="shrink-0 text-muted-foreground/60 hover:text-muted-foreground"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
          </button>
        </div>
        {expanded && (
          <div className="mt-2.5 space-y-1.5 pl-3.5">
            {description && (
              <p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
            )}
            {files.length > 0 && (
              <p className="text-[11px] text-muted-foreground/60">
                {files.length === 1 ? files[0] : `${files.length} shared files`}
                {files.length > 1 && (
                  <span className="ml-1 text-muted-foreground/40">
                    ({files.slice(0, 3).join(", ")}{files.length > 3 ? `, +${files.length - 3} more` : ""})
                  </span>
                )}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  // ---- File-level warning (mods from different builds sharing files) ----
  // Still no disable buttons - load order handles it, but flag it more visibly.
  if (!isDeclared) {
    return (
      <div className={cn("rounded-lg border bg-card/40 p-4", "border-[hsl(var(--warning)/0.25)]")}>
        <div className="flex items-start gap-2">
          <span className="mt-1 size-2 shrink-0 rounded-full bg-[hsl(var(--warning))]" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium" title={modNames.join(", ")}>
              {joinNames(modNames)}
            </p>
            {files.length > 0 && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {files.length === 1 ? files[0] : `${files.length} shared files`}
              </p>
            )}
          </div>
          <Badge variant="warning" className="shrink-0">shared files</Badge>
        </div>
        {description && (
          <p className="mt-2.5 text-sm leading-relaxed text-foreground">{description}</p>
        )}
        {recommendation && (
          <div className="mt-2.5 flex items-start gap-2 rounded-md border border-[hsl(var(--info)/0.3)] bg-[hsl(var(--info)/0.08)] p-2.5">
            <Lightbulb className="mt-0.5 size-4 shrink-0 text-[hsl(var(--info))]" />
            <p className="text-sm text-muted-foreground">{recommendation}</p>
          </div>
        )}
        {/* Load order handles file conflicts - no disable buttons here.
            If the player truly wants to act, they can use the Library view. */}
      </div>
    );
  }

  // ---- Declared incompatibility ----
  // Show prominently but with curated-build context. Disable buttons are shown
  // but framed as "only if you're actually having problems".
  return (
    <div className="rounded-lg border border-destructive/25 bg-card/40 p-4">
      <div className="flex items-start gap-2">
        <span className="mt-1 size-2 shrink-0 rounded-full bg-destructive" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">
            {joinNames(modNames)}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">Declared incompatible</p>
        </div>
        {sameBuild ? (
          <Badge variant="warning" className="shrink-0">review needed</Badge>
        ) : (
          <Badge variant="destructive" className="shrink-0">incompatible</Badge>
        )}
      </div>

      {description && (
        <p className="mt-2.5 text-sm leading-relaxed text-foreground">{description}</p>
      )}

      {recommendation && (
        <div className="mt-2.5 flex items-start gap-2 rounded-md border border-[hsl(var(--warning)/0.3)] bg-[hsl(var(--warning)/0.08)] p-2.5">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-[hsl(var(--warning))]" />
          <p className="text-sm text-muted-foreground">{recommendation}</p>
        </div>
      )}

      {participants.some(p => p.enabled) && (
        <div className="mt-3 space-y-2 border-t pt-3">
          <p className="text-xs text-muted-foreground">{t("conflicts.ifIssuesDisable")}</p>
          <div className="flex flex-wrap gap-2">
            {participants.filter(p => p.enabled).map(p => (
              <Button key={p.mod_id} size="sm" variant="outline" disabled={busy}
                onClick={() => disableMods([p.mod_id])}>
                {t("conflicts.disableMod", { mod: p.mod_name })}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
