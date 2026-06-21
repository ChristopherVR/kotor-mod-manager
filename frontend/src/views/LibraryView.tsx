import { useCallback, useEffect, useMemo, useState } from "react";
import { Library as LibraryIcon } from "lucide-react";
import { api, type GameKey, type LibraryMod } from "@/lib/api";
import { LibraryRow } from "@/components/LibraryRow";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";

type GameFilter = "ALL" | GameKey;

interface LibraryViewProps {
  onGoToBuilds: () => void;
  onGoToConflicts: () => void;
  addLog: (message: string, tag?: string) => void;
  refreshTick: number;
}

const FILTERS: { id: GameFilter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "KOTOR1", label: "KOTOR 1" },
  { id: "KOTOR2", label: "KOTOR 2" },
];

export function LibraryView({ onGoToBuilds, onGoToConflicts, addLog, refreshTick }: LibraryViewProps) {
  const [filter, setFilter] = useState<GameFilter>("KOTOR1");
  const [mods, setMods] = useState<LibraryMod[]>([]);
  const [query, setQuery] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErrored(false);
    const games: GameKey[] = filter === "ALL" ? ["KOTOR1", "KOTOR2"] : [filter];
    try {
      const results = await Promise.all(games.map((g) => api.library(g).catch(() => ({ mods: [] }))));
      setMods(results.flatMap((r) => r.mods ?? []));
    } catch {
      setErrored(true);
      setMods([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

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

  const toggle = async (mod: LibraryMod, next: boolean) => {
    // Optimistic update, revert on error.
    setMods((prev) => prev.map((m) => (m.id === mod.id ? { ...m, enabled: next } : m)));
    try {
      if (next) await api.libraryEnable(mod.game, mod.id);
      else await api.libraryDisable(mod.game, mod.id);
    } catch (e: any) {
      setMods((prev) => prev.map((m) => (m.id === mod.id ? { ...m, enabled: !next } : m)));
      addLog(`Failed to ${next ? "enable" : "disable"} ${mod.name}: ${e?.message}`, "error");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="space-y-3 border-b bg-card/30 px-5 py-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-base font-semibold">Library</h1>
            <p className="text-xs text-muted-foreground">{enabledCount}/{total} enabled</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Enabled only</span>
            <Switch checked={enabledOnly} onCheckedChange={setEnabledOnly} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                  filter === f.id
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search mods…"
            className="max-w-xs"
          />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <EmptyState icon={LibraryIcon} title="Loading library…" />
        ) : errored || total === 0 ? (
          <EmptyState
            icon={LibraryIcon}
            title="No installed mods"
            subtitle="Install a build to populate your library."
            action={{ label: "Go to Mod Builds", onClick: onGoToBuilds }}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={LibraryIcon}
            title="No mods match your filters"
            subtitle="Try a different game filter or search term."
          />
        ) : (
          <div className="space-y-0.5">
            {filtered.map((m) => (
              <LibraryRow
                key={`${m.game}:${m.id}`}
                mod={m}
                onToggle={(next) => toggle(m, next)}
                onConflictClick={onGoToConflicts}
              />
            ))}
          </div>
        )}
      </div>

      {!loading && total > 0 && (
        <footer className="border-t bg-card/40 px-5 py-2">
          <Button variant="ghost" size="sm" onClick={onGoToBuilds}>Install more mods</Button>
        </footer>
      )}
    </div>
  );
}
