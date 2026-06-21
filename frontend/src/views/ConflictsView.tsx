import { useCallback, useEffect, useState } from "react";
import { GitMerge, CheckCircle2 } from "lucide-react";
import { api, type Conflict, type Profile } from "@/lib/api";
import { ConflictCard } from "@/components/ConflictCard";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";

interface ConflictsViewProps {
  refreshTick: number;
  profiles: Profile[];
  activeProfile: string;
  setActiveProfile: (id: string) => void;
}

export function ConflictsView({ refreshTick, profiles, activeProfile, setActiveProfile }: ConflictsViewProps) {
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!activeProfile) { setConflicts([]); setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api.conflicts(activeProfile);
      setConflicts(r.conflicts ?? []);
    } catch {
      setConflicts([]);
    } finally {
      setLoading(false);
    }
  }, [activeProfile]);

  useEffect(() => { load(); }, [load, refreshTick]);

  const switchProfile = (id: string) => {
    setActiveProfile(id);
    api.setActiveProfile(id).catch(() => {});
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">Conflicts</h1>
          <p className="text-xs text-muted-foreground">
            {conflicts.length} contested {conflicts.length === 1 ? "resource" : "resources"}
          </p>
        </div>
        <Select
          value={activeProfile}
          onChange={(e) => switchProfile(e.target.value)}
          className="ml-auto max-w-[16rem]"
          disabled={profiles.length === 0}
        >
          {profiles.length === 0 && <option value="">No game installs</option>}
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>
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
