import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import { FolderOpen, Library as LibraryIcon, Power, ScrollText, Trash2 } from "lucide-react";
import { api, type LibraryMod, type Profile } from "@/lib/api";
import { LibraryRow } from "@/components/LibraryRow";
import { ModDetail } from "@/components/ModDetail";
import { ContextMenu, type ContextMenuItem } from "@/components/ui/context-menu";
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

// Friendly labels for raw install-method enum names.
const METHOD_LABELS: Record<string, string> = {
  TSLPATCHER: "TSLPatcher",
  HOLOPATCHER: "HoloPatcher",
  DIRECT_COPY: "Direct copy",
  OVERRIDE_COPY: "Override copy",
  TLK_REPLACE: "Dialog (TLK)",
  MULTI_VARIANT: "Multi-variant",
  MULTIPLE: "Multiple",
  GAME_PATCHER: "Game patcher",
  MANUAL: "Manual",
};

const methodLabel = (m: string) => METHOD_LABELS[m] ?? m;

/** Normalize a mod name for duplicate detection. */
const dupeKey = (m: LibraryMod) => m.name.trim().toLowerCase();

export function LibraryView({
  onGoToBuilds, onGoToConflicts, addLog, refreshTick,
  profiles, activeProfile, setActiveProfile,
}: LibraryViewProps) {
  const t = useT();
  const [mods, setMods] = useState<LibraryMod[]>([]);
  const [query, setQuery] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [dupesOnly, setDupesOnly] = useState(false);
  const [method, setMethod] = useState("all");
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [openMod, setOpenMod] = useState<LibraryMod | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; mod: LibraryMod } | null>(null);

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

  // Distinct methods/categories present, for the filter dropdowns.
  const methods = useMemo(
    () => Array.from(new Set(mods.map((m) => m.install_method).filter(Boolean))).sort(),
    [mods],
  );
  const categories = useMemo(
    () => Array.from(new Set(mods.map((m) => m.category).filter(Boolean))).sort(),
    [mods],
  );

  // Names that occur more than once → duplicate set.
  const dupeKeys = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of mods) counts.set(dupeKey(m), (counts.get(dupeKey(m)) ?? 0) + 1);
    return new Set([...counts].filter(([, n]) => n > 1).map(([k]) => k));
  }, [mods]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return mods
      .filter((m) => (enabledOnly ? m.enabled : true))
      .filter((m) => (method === "all" ? true : m.install_method === method))
      .filter((m) => (category === "all" ? true : m.category === category))
      .filter((m) => (dupesOnly ? dupeKeys.has(dupeKey(m)) : true))
      .filter((m) => (q ? m.name.toLowerCase().includes(q) : true))
      .sort((a, b) => a.load_order - b.load_order);
  }, [mods, query, enabledOnly, method, category, dupesOnly, dupeKeys]);

  const total = mods.length;
  const enabledCount = mods.filter((m) => m.enabled).length;
  const dupeCount = dupeKeys.size;

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

  const openFolder = async (mod: LibraryMod) => {
    try {
      await api.libraryOpenFolder(activeProfile, mod.id);
    } catch (e: any) {
      addLog(t("library.openFolderFailed", { name: mod.name }), "warning");
    }
  };

  // Delete (uninstall) a mod entirely. Baked TSLPatcher/HoloPatcher mods can't be
  // cleanly removed without a backup, so the backend asks for confirmation
  // (409 baked_no_backup) before we force it.
  const deleteMod = async (mod: LibraryMod, force = false) => {
    if (!force && !window.confirm(t("library.deleteConfirm", { name: mod.name }))) return;
    try {
      await api.libraryUninstall(activeProfile, mod.id, force);
      addLog(t("library.deleted", { name: mod.name }), "success");
      if (openMod?.id === mod.id) setOpenMod(null);
      load();
    } catch (e: any) {
      if (!force && (e?.status === 409 || e?.data?.error === "baked_no_backup")) {
        const msg = e?.data?.message || t("library.deleteBakedMessage", { name: mod.name });
        if (window.confirm(t("library.deleteForceConfirm", { message: msg }))) {
          deleteMod(mod, true);
        }
        return;
      }
      addLog(t("library.deleteFailed", { name: mod.name, error: e?.message ?? "error" }), "error");
    }
  };

  const openContextMenu = (e: MouseEvent, mod: LibraryMod) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, mod });
  };

  const menuItems = (mod: LibraryMod): ContextMenuItem[] => {
    const items: ContextMenuItem[] = [
      { label: t("modDetail.viewDetails"), icon: ScrollText, onSelect: () => setOpenMod(mod) },
      {
        label: t("library.openFolder"), icon: FolderOpen,
        onSelect: () => openFolder(mod), disabled: !mod.source_exists,
      },
      {
        label: mod.enabled ? t("library.disable") : t("library.enable"), icon: Power,
        onSelect: () => toggle(mod, !mod.enabled), disabled: !mod.toggleable,
      },
      {
        label: t("library.delete"), icon: Trash2,
        onSelect: () => deleteMod(mod), danger: true,
      },
    ];
    return items;
  };

  return (
    <div className="flex h-full flex-col">
      <header className="space-y-3 border-b bg-card/30 px-5 py-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-base font-semibold">{t("library.title")}</h1>
            <p className="text-xs text-muted-foreground">
              {t("library.enabledSummary", { enabled: enabledCount, total })}
              {dupeCount > 0 && ` · ${t("library.duplicateSummary", { count: dupeCount })}`}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{t("library.enabledOnly")}</span>
            <Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeProfile}
            onChange={(e) => switchProfile(e.target.value)}
            className="max-w-[14rem]"
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
            className="max-w-[16rem] flex-1"
          />
          <Select value={method} onChange={(e) => setMethod(e.target.value)} className="w-auto">
            <option value="all">{t("library.allMethods")}</option>
            {methods.map((m) => (
              <option key={m} value={m}>{methodLabel(m)}</option>
            ))}
          </Select>
          {categories.length > 0 && (
            <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-auto">
              <option value="all">{t("library.allCategories")}</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          )}
          {dupeCount > 0 && (
            <Button
              variant={dupesOnly ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setDupesOnly((v) => !v)}
            >
              {t("library.duplicatesOnly")}
            </Button>
          )}
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
                duplicate={dupeKeys.has(dupeKey(m))}
                onToggle={(next) => toggle(m, next)}
                onConflictClick={onGoToConflicts}
                onOpen={() => setOpenMod(m)}
                onContextMenu={(e) => openContextMenu(e, m)}
                onDelete={() => deleteMod(m)}
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

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={menuItems(menu.mod)}
          onClose={() => setMenu(null)}
        />
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
