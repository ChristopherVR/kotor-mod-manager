import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [activeProfile, onCountChange]);

  useEffect(() => { load(); }, [load, refreshTick]);

  const handleResolved = useCallback((updated?: Conflict[]) => {
    if (updated) {
      setConflicts(updated);
      setLoadError(false);
    } else {
      load();
    }
    onResolved();
  }, [load, onResolved]);

  // Group conflicts that share the exact same set of participants.
  const allGroups = useMemo<ConflictGroup[]>(() => {
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
          same_build: c.same_build,
        });
      }
      const g = map.get(gkey)!;
      g.items.push(c);
      // Carry same_build if any item in the group has it.
      if (c.same_build) g.same_build = true;
      // Escalate to the worst severity in the group.
      const rank: Record<string, number> = { error: 2, warning: 1, info: 0 };
      if ((rank[c.severity] ?? 0) > (rank[g.severity] ?? 0)) g.severity = c.severity;
    }
    return [...map.values()];
  }, [conflicts]);

  // Split into sections: declared incompatibilities vs file-level load-order notes.
  const declaredGroups = useMemo(
    () => allGroups.filter(g => g.items[0]?.type === "declared"),
    [allGroups],
  );
  // File-level groups needing attention. Curated-build overlaps come back as
  // "info" because the build's install order already decided them; they are
  // hidden by default but counted, so the list is quiet without being a lie
  // about what was found.
  const fileGroups = useMemo(
    () => allGroups.filter(g => g.items[0]?.type !== "declared" && g.severity !== "info"),
    [allGroups],
  );
  const infoGroups = useMemo(
    () => allGroups.filter(g => g.items[0]?.type !== "declared" && g.severity === "info"),
    [allGroups],
  );
  const [showInfo, setShowInfo] = useState(false);
  const [busy, setBusy] = useState(false);

  const bulk = useCallback(async (
    action: "dismiss" | "undismiss" | "disable_losers",
    ids?: string[],
  ) => {
    if (!activeProfile) return;
    setBusy(true);
    try {
      const r = await api.resolveConflicts(activeProfile, {
        action,
        ...(ids ? { conflict_ids: ids } : { all_of_severity: "info" }),
      });
      if (action === "disable_losers") {
        addLog(`Disabled ${r.disabled.length} shadowed mod(s).`, "success");
        r.skipped.forEach(s => addLog(`Skipped: ${s.reason}`, "muted"));
      } else {
        addLog(
          action === "dismiss"
            ? `Hid ${r.requested} conflict(s) you have reviewed.`
            : `Restored previously hidden conflicts.`,
          "success",
        );
      }
      await load();
      onResolved();
    } catch {
      addLog("Could not apply that to the selected conflicts.", "error");
    } finally {
      setBusy(false);
    }
  }, [activeProfile, addLog, load, onResolved]);

  // Sync the tab badge count with the number of actionable conflict groups.
  const prevCount = useRef<number | null>(null);
  useEffect(() => {
    const n = declaredGroups.length + fileGroups.length;
    if (n !== prevCount.current) {
      prevCount.current = n;
      onCountChange?.(n);
    }
  }, [declaredGroups.length, fileGroups.length, onCountChange]);

  const switchProfile = (id: string) => {
    setActiveProfile(id);
    api.setActiveProfile(id).catch(() => {});
  };

  // Actionable count drives the sidebar badge and the subtitle; the rendered
  // count also includes the informational overlaps so their summary bar still
  // appears when nothing needs attention.
  const actionableCount = declaredGroups.length + fileGroups.length;
  const visibleCount = actionableCount + infoGroups.length;

  // Subtitle that distinguishes real incompatibilities from load-order notes.
  const subtitle = useMemo(() => {
    if (actionableCount === 0) return t("conflicts.noneShort");
    const parts: string[] = [];
    if (declaredGroups.length === 1) parts.push(t("conflicts.summaryDeclared", { count: 1 }));
    else if (declaredGroups.length > 1) parts.push(t("conflicts.summaryDeclaredPlural", { count: declaredGroups.length }));
    if (fileGroups.length === 1) parts.push(t("conflicts.summaryNotes", { count: 1 }));
    else if (fileGroups.length > 1) parts.push(t("conflicts.summaryNotesPlural", { count: fileGroups.length }));
    return parts.join(", ");
  }, [t, actionableCount, declaredGroups.length, fileGroups.length]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">{t("conflicts.title")}</h1>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
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
        ) : visibleCount === 0 ? (
          loadError ? (
            <EmptyState icon={AlertTriangle} title={t("conflicts.checkFailedTitle")} subtitle={t("conflicts.checkFailedSubtitle")} />
          ) : (
            <EmptyState icon={CheckCircle2} title={t("conflicts.noneTitle")} subtitle={t("conflicts.noneSubtitle")} />
          )
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            {loadError && (
              <div className="flex items-center gap-2 rounded-md border border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.1)] px-3 py-2 text-xs text-[hsl(var(--warning))]">
                <AlertTriangle className="size-4 shrink-0" />
                {t("conflicts.checkStale")}
              </div>
            )}

            {/* Declared incompatibilities - most prominent, shown first. */}
            {declaredGroups.length > 0 && (
              <section className="space-y-3">
                <div>
                  <h2 className="text-sm font-semibold text-foreground">{t("conflicts.sectionDeclared")}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">{t("conflicts.sectionDeclaredHint")}</p>
                </div>
                {declaredGroups.map((g) => (
                  <ConflictCard
                    key={g.gkey}
                    group={g}
                    profile={activeProfile}
                    addLog={addLog}
                    onResolved={handleResolved}
                  />
                ))}
              </section>
            )}

            {/* Curated-build overlaps: counted, hidden by default, clearable. */}
            {infoGroups.length > 0 && (
              <section className="rounded-md border bg-card/40 px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {infoGroups.length}
                    </span>{" "}
                    file overlap{infoGroups.length === 1 ? "" : "s"} between mods in
                    your builds. The install order already decides these, so no
                    action is needed.
                  </p>
                  <div className="ml-auto flex gap-2">
                    <button
                      type="button"
                      onClick={() => setShowInfo(v => !v)}
                      className="rounded border px-2 py-1 text-xs hover:bg-accent"
                    >
                      {showInfo ? "Hide details" : "Show details"}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => bulk("dismiss")}
                      className="rounded border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
                    >
                      Mark all reviewed
                    </button>
                  </div>
                </div>
                {showInfo && (
                  <div className="mt-2 space-y-1">
                    {infoGroups.slice(0, 100).map(g => (
                      <ConflictCard
                        key={g.gkey}
                        group={g}
                        profile={activeProfile}
                        addLog={addLog}
                        onResolved={handleResolved}
                      />
                    ))}
                    {infoGroups.length > 100 && (
                      <p className="px-1 pt-1 text-xs text-muted-foreground">
                        Showing the first 100 of {infoGroups.length}.
                      </p>
                    )}
                  </div>
                )}
              </section>
            )}

            {/* File-level load-order notes - shown collapsed, minimal weight. */}
            {fileGroups.length > 0 && (
              <section className="space-y-1.5">
                <div>
                  <h2 className="text-sm font-semibold text-foreground">{t("conflicts.sectionNotes")}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">{t("conflicts.sectionNotesHint")}</p>
                </div>
                <div className="mt-2 space-y-1">
                  {fileGroups.map((g) => (
                    <ConflictCard
                      key={g.gkey}
                      group={g}
                      profile={activeProfile}
                      addLog={addLog}
                      onResolved={handleResolved}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
