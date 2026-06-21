import { useCallback, useEffect, useState } from "react";
import { GitMerge, CheckCircle2 } from "lucide-react";
import { api, type Conflict, type GameKey } from "@/lib/api";
import { ConflictCard } from "@/components/ConflictCard";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";

interface ConflictsViewProps {
  refreshTick: number;
}

const FILTERS: { id: GameKey; label: string }[] = [
  { id: "KOTOR1", label: "KOTOR 1" },
  { id: "KOTOR2", label: "KOTOR 2" },
];

export function ConflictsView({ refreshTick }: ConflictsViewProps) {
  const [game, setGame] = useState<GameKey>("KOTOR1");
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.conflicts(game);
      setConflicts(r.conflicts ?? []);
    } catch {
      setConflicts([]);
    } finally {
      setLoading(false);
    }
  }, [game]);

  useEffect(() => { load(); }, [load, refreshTick]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">Conflicts</h1>
          <p className="text-xs text-muted-foreground">
            {conflicts.length} contested {conflicts.length === 1 ? "resource" : "resources"}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1 rounded-md bg-muted p-0.5">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setGame(f.id)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                game === f.id
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <EmptyState icon={GitMerge} title="Checking for conflicts…" />
        ) : conflicts.length === 0 ? (
          <EmptyState icon={CheckCircle2} title="No conflicts detected." subtitle="All installed mods coexist cleanly." />
        ) : (
          <div className="mx-auto max-w-3xl space-y-3">
            {conflicts.map((c) => (
              <ConflictCard key={c.id} conflict={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
