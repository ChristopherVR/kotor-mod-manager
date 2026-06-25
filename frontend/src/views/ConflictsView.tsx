import { useCallback, useEffect, useState } from "react";
import { GitMerge, CheckCircle2, AlertTriangle } from "lucide-react";
import { api, type Conflict, type Profile } from "@/lib/api";
import { ConflictCard } from "@/components/ConflictCard";
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
}

export function ConflictsView({
  refreshTick,
  profiles,
  activeProfile,
  setActiveProfile,
  addLog,
  onResolved,
}: ConflictsViewProps) {
  const t = useT();
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    if (!activeProfile) { setConflicts([]); setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api.conflicts(activeProfile);
      setConflicts(r.conflicts ?? []);
      setLoadError(false);
    } catch {
      // Don't blank the list on a transient error - that looks like "all
      // conflicts resolved" when really the check just failed. Keep what we have
      // and flag the error instead.
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load, refreshTick]);

  // After a resolve, the disable endpoint already returns the recomputed list -
  // use it directly when present so the remaining conflicts never flicker away.
  const handleResolved = useCallback((updated?: Conflict[]) => {
    if (updated) { setConflicts(updated); setLoadError(false); }
    else load();
    onResolved();
  }, [load, onResolved]);

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
            {conflicts.length === 1
              ? t("conflicts.summaryOne", { count: conflicts.length })
              : t("conflicts.summaryMany", { count: conflicts.length })}
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
        ) : conflicts.length === 0 ? (
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
            {conflicts.map((c) => (
              <ConflictCard
                key={c.id}
                conflict={c}
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
