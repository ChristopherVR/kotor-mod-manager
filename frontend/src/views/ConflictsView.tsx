import { useCallback, useEffect, useMemo, useState } from "react";
import { GitMerge, CheckCircle2, AlertTriangle } from "lucide-react";
import { api, type Conflict, type ConflictParticipant, type Profile } from "@/lib/api";
import { ConflictCard, type ConflictGroup } from "@/components/ConflictCard";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { useT } from "@/lib/i18n";

interface ConflictsViewProps {
  refreshTick: number;
  profiles: Profile[];
  activeProfile: string;
  setActiveProfile: (id: string) => void;
  addLog: (message: string, tag?: string) => void;
  onResolved: () => void;
  onCountChange?: (n: number) => void;
}

export function ConflictsView({
  refreshTick,
  profiles,
  activeProfile,
  setActiveProfile,
  addLog,
  onResolved,
  onCountChange,
}: ConflictsViewProps) {
  const t = useT();
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    if (!activeProfile) { setConflicts([]); setLoading(false); onCountChange?.(0); return; }
    setLoading(true);
    try {
      const r = await api.conflicts(activeProfile);
      const list = r.conflicts ?? [];
      setConflicts(list);
      onCountChange?.(list.length);
      setLoadError(false);
    } catch {
      // Don't blank the list on a transient error - that looks like "all
      // conflicts resolved" when really the check just failed. Keep what we have
      // and flag the error instead.
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [activeProfile, onCountChange]);

  useEffect(() => { load(); }, [load, refreshTick]);

  // After a resolve, the disable endpoint already returns the recomputed list -
  // use it directly when present so the remaining conflicts never flicker away.
  const handleResolved = useCallback((updated?: Conflict[]) => {
    if (updated) {
      setConflicts(updated);
      setLoadError(false);
      onCountChange?.(updated.length);
    } else {
      load();
    }
    onResolved();
  }, [load, onResolved, onCountChange]);

  // Group conflicts that share the exact same set of participants so that
  // "Mod A vs Mod B on 5 files" shows as one card instead of five.
  const groups = useMemo<ConflictGroup[]>(() => {
    const map = new Map<string, ConflictGroup>();
    for (const c of conflicts) {
      const gkey = [...c.participants.map((p: ConflictParticipant) => p.mod_id)].sort().join("\0");
      if (!map.has(gkey)) {
        map.set(gkey, {
          gkey,
          participants: c.participants,
          items: [],
          severity: c.severity,
          winner_mod_id: c.winner_mod_id,
        });
      }
      const g = map.get(gkey)!;
      g.items.push(c);
      // Escalate to the worst severity in the group.
      const rank: Record<string, number> = { error: 2, warning: 1, info: 0 };
      if ((rank[c.severity] ?? 0) > (rank[g.severity] ?? 0)) g.severity = c.severity;
    }
    return [...map.values()];
  }, [conflicts]);

  const switchProfile = (id: string) => {
    setActiveProfile(id);
    api.setActiveProfile(id).catch(() => {});
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">{t("conflicts.title")}</h1>
          <p className="text-xs text-muted-foreground">
            {groups.length === 0
              ? t("conflicts.noneShort")
              : groups.length === 1
                ? t("conflicts.summaryOne")
                : t("conflicts.summaryMany", { count: groups.length })}
          </p>
        </div>
        <Select
          value={activeProfile}
          onChange={(e) => switchProfile(e.target.value)}
          className="ml-auto max-w-[16rem]"
          disabled={profiles.length === 0}
        >
          {profiles.length === 0 && <option value="">{t("conflicts.noProfiles")}</option>}
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <EmptyState icon={GitMerge} title={t("conflicts.checking")} />
        ) : groups.length === 0 ? (
          loadError ? (
            <EmptyState icon={AlertTriangle} title={t("conflicts.checkFailedTitle")} subtitle={t("conflicts.checkFailedSubtitle")} />
          ) : (
            <EmptyState icon={CheckCircle2} title={t("conflicts.noneTitle")} subtitle={t("conflicts.noneSubtitle")} />
          )
        ) : (
          <div className="mx-auto max-w-3xl space-y-3">
            {loadError && (
              <div className="flex items-center gap-2 rounded-md border border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.1)] px-3 py-2 text-xs text-[hsl(var(--warning))]">
                <AlertTriangle className="size-4 shrink-0" />
                {t("conflicts.checkStale")}
              </div>
            )}
            {groups.map((g) => (
              <ConflictCard
                key={g.gkey}
                group={g}
                profile={activeProfile}
                addLog={addLog}
                onResolved={handleResolved}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
