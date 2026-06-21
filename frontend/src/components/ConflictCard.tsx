import { useState } from "react";
import { Lightbulb } from "lucide-react";
import { api, type Conflict } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

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

const TYPE_VARIANT: Record<Conflict["type"], "info" | "warning" | "muted" | "secondary" | "destructive"> = {
  override: "secondary",
  "2da": "info",
  dialog: "warning",
  module: "muted",
  declared: "destructive",
};

interface ConflictCardProps {
  conflict: Conflict;
  profile: string;
  addLog: (message: string, tag?: string) => void;
  onResolved: () => void;
}

export function ConflictCard({ conflict, profile, addLog, onResolved }: ConflictCardProps) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  const winner = conflict.participants.find((p) => p.mod_id === conflict.winner_mod_id);
  // Enabled participants that lose to the winner.
  const losers = conflict.winner_mod_id
    ? conflict.participants.filter((p) => p.mod_id !== conflict.winner_mod_id && p.enabled)
    : [];

  const disableMods = async (modIds: string[]) => {
    if (busy || !profile || modIds.length === 0) return;
    setBusy(true);
    try {
      for (const id of modIds) {
        await api.libraryDisable(profile, id);
      }
      const names = modIds
        .map((id) => conflict.participants.find((p) => p.mod_id === id)?.mod_name ?? id)
        .join(", ");
      addLog(t("conflicts.resolvedLog", { mods: names }), "success");
      onResolved();
    } catch (e: any) {
      addLog(t("conflicts.resolveFailed", { error: e?.message ?? "error" }), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border bg-card/40 p-4">
      <div className="flex items-center gap-2">
        <span className={cn("size-2 shrink-0 rounded-full", SEVERITY_DOT[conflict.severity])} />
        <code className="flex-1 truncate font-mono text-sm text-foreground" title={conflict.resource}>
          {conflict.resource}
        </code>
        <Badge variant={SEVERITY_BADGE[conflict.severity]}>{conflict.severity}</Badge>
        <Badge variant={TYPE_VARIANT[conflict.type]}>{conflict.type}</Badge>
      </div>

      {conflict.description && (
        <p className="mt-2.5 text-sm leading-relaxed text-foreground">{conflict.description}</p>
      )}

      {conflict.recommendation && (
        <div className="mt-2.5 flex items-start gap-2 rounded-md border border-[hsl(var(--info)/0.3)] bg-[hsl(var(--info)/0.08)] p-2.5">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-[hsl(var(--info))]" />
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{t("conflicts.recommendation")}</span>
            {conflict.recommendation}
          </p>
        </div>
      )}

      <ul className="mt-3 space-y-1.5 pl-4">
        {conflict.participants.map((p) => {
          const isWinner = conflict.winner_mod_id === p.mod_id;
          return (
            <li key={p.mod_id} className="flex items-center gap-2 text-sm">
              <span
                className={cn(
                  "flex-1 truncate",
                  isWinner ? "font-medium text-foreground" : "text-muted-foreground",
                  !p.enabled && "line-through opacity-60"
                )}
                title={p.mod_name}
              >
                {p.mod_name}
              </span>
              {isWinner && <Badge variant="success">{t("conflicts.wins")}</Badge>}
              {!p.enabled && <Badge variant="muted">{t("conflicts.disabled")}</Badge>}
            </li>
          );
        })}
      </ul>

      {/* Resolution actions */}
      {conflict.winner_mod_id && losers.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          <Button
            size="sm"
            disabled={busy}
            onClick={() => disableMods(losers.map((p) => p.mod_id))}
          >
            {t("conflicts.keepWinner", { mod: winner?.mod_name ?? "" })}
          </Button>
          {losers.map((p) => (
            <Button
              key={p.mod_id}
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => disableMods([p.mod_id])}
            >
              {t("conflicts.disableMod", { mod: p.mod_name })}
            </Button>
          ))}
        </div>
      )}

      {!conflict.winner_mod_id && conflict.type === "declared" && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          {conflict.participants
            .filter((p) => p.enabled)
            .map((p) => (
              <Button
                key={p.mod_id}
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => disableMods([p.mod_id])}
              >
                {t("conflicts.disableMod", { mod: p.mod_name })}
              </Button>
            ))}
        </div>
      )}
    </div>
  );
}
