import { useCallback, useEffect, useMemo, useState } from "react";
import { Library as LibraryIcon } from "lucide-react";
import { api, type LibraryMod, type Profile } from "@/lib/api";
import { LibraryRow } from "@/components/LibraryRow";
import { ModDetail } from "@/components/ModDetail";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useT } from "@/lib/i18n";

interface LibraryViewProps {
  onGoToBuilds: () => void;
  onGoToConflicts: () => void;
  addLog: (message: string, tag?: string) => void;
  refreshTick: number;
  profiles: Profile[];
  activeProfile: string;
  setActiveProfile: (id: string) => void;
}

export function LibraryView({
  onGoToBuilds, onGoToConflicts, addLog, refreshTick,
  profiles, activeProfile, setActiveProfile,
}: LibraryViewProps) {
  const t = useT();
  const [mods, setMods] = useState<LibraryMod[]>([]);
  const [query, setQuery] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [openMod, setOpenMod] = useState<LibraryMod | null>(null);

  const load = useCallback(async () => {
    if (!activeProfile) { setMods([]); setLoading(false); return; }
    setLoading(true);
    setErrored(false);
    try {
      const r = await api.library(activeProfile);
      setMods(r.mods ?? []);
    } catch {
      setErrored(true);
      setMods([]);
    } finally {
      setLoading(false);
    }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load, refreshTick]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return mods
      .filter((m) => (enabledOnly ? m.enabled : true))
      .filter((m) => (q ? m.name.toLowerCase().includes(q) : true))
      .sort((a, b) => a.load_order - b.load_order);
  }, [mods, query, enabledOnly]);

  const total = mods.length;
  const enabledCount = mods.filter((m) => m.enabled).length;

  const switchProfile = (id: string) => {
    setActiveProfile(id);
    api.setActiveProfile(id).catch(() => {});
  };

  const toggle = async (mod: LibraryMod, next: boolean) => {
    // Optimistic update, revert on error.
    setMods((prev) => prev.map((m) => (m.id === mod.id ? { ...m, enabled: next } : m)));
    setOpenMod((cur) => (cur && cur.id === mod.id ? { ...cur, enabled: next } : cur));
    try {
      if (next) await api.libraryEnable(activeProfile, mod.id);
      else await api.libraryDisable(activeProfile, mod.id);
    } catch (e: any) {
      setMods((prev) => prev.map((m) => (m.id === mod.id ? { ...m, enabled: !next } : m)));
      setOpenMod((cur) => (cur && cur.id === mod.id ? { ...cur, enabled: !next } : cur));
      addLog(`Failed to ${next ? "enable" : "disable"} ${mod.name}: ${e?.message}`, "error");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="space-y-3 border-b bg-card/30 px-5 py-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-base font-semibold">{t("library.title")}</h1>
            <p className="text-xs text-muted-foreground">
              {t("library.enabledSummary", { enabled: enabledCount, total })}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{t("library.enabledOnly")}</span>
            <Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={activeProfile}
            onChange={(e) => switchProfile(e.target.value)}
            className="max-w-[16rem]"
            disabled={profiles.length === 0}
          >
            {profiles.length === 0 && <option value="">{t("library.noProfiles")}</option>}
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("library.search")}
            className="max-w-xs"
          />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <EmptyState icon={LibraryIcon} title={t("library.loading")} />
        ) : errored || total === 0 ? (
          <EmptyState
            icon={LibraryIcon}
            title={t("library.emptyTitle")}
            subtitle={t("library.emptySubtitle")}
            action={{ label: t("library.goToBuilds"), onClick: onGoToBuilds }}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={LibraryIcon}
            title={t("library.noMatchTitle")}
            subtitle={t("library.noMatchSubtitle")}
          />
        ) : (
          <div className="space-y-0.5">
            {filtered.map((m) => (
              <LibraryRow
                key={`${m.game}:${m.id}`}
                mod={m}
                onToggle={(next) => toggle(m, next)}
                onConflictClick={onGoToConflicts}
                onOpen={() => setOpenMod(m)}
              />
            ))}
          </div>
        )}
      </div>

      {!loading && total > 0 && (
        <footer className="border-t bg-card/40 px-5 py-2">
          <Button variant="ghost" size="sm" onClick={onGoToBuilds}>{t("library.installMore")}</Button>
        </footer>
      )}

      {openMod && (
        <ModDetail
          mod={openMod}
          profile={activeProfile}
          onClose={() => setOpenMod(null)}
          onToggle={(next) => toggle(openMod, next)}
          onUninstalled={load}
          addLog={addLog}
        />
      )}
    </div>
  );
}
