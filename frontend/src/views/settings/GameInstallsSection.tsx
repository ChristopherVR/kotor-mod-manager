import { useState } from "react";
import {
  FolderOpen, Plus, Pencil, Trash2, Check, X, CheckCircle2, Star,
} from "lucide-react";
import { api, type GameKey, type Profile } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface GameInstallsSectionProps {
  profiles: Profile[];
  activeProfile: string;
  setActiveProfile: (id: string) => void;
  refreshProfiles: () => Promise<void> | void;
  addLog: (message: string, tag?: string) => void;
}

const GAME_LABEL: Record<GameKey, string> = { KOTOR1: "KOTOR 1", KOTOR2: "KOTOR 2" };

export function GameInstallsSection({
  profiles, activeProfile, setActiveProfile, refreshProfiles, addLog,
}: GameInstallsSectionProps) {
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Add form state.
  const [newName, setNewName] = useState("");
  const [newGame, setNewGame] = useState<GameKey>("KOTOR1");
  const [newPath, setNewPath] = useState("");

  // Edit form state.
  const [editName, setEditName] = useState("");
  const [editPath, setEditPath] = useState("");

  const resetAdd = () => { setAdding(false); setNewName(""); setNewGame("KOTOR1"); setNewPath(""); };

  const makeActive = async (id: string) => {
    if (id === activeProfile) return;
    setActiveProfile(id);
    try {
      await api.setActiveProfile(id);
      addLog("Active game install changed.", "muted");
    } catch (e: any) {
      addLog(`Failed to set active install: ${e?.message}`, "error");
    }
  };

  const create = async () => {
    if (!newName.trim() || !newPath.trim()) return;
    setBusy(true);
    try {
      await api.createProfile({ name: newName.trim(), game: newGame, path: newPath.trim() });
      addLog(`Added game install "${newName.trim()}".`, "success");
      resetAdd();
      await refreshProfiles();
    } catch (e: any) {
      addLog(`Failed to add install: ${e?.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (p: Profile) => {
    setEditId(p.id);
    setEditName(p.name);
    setEditPath(p.path);
  };

  const saveEdit = async (id: string) => {
    setBusy(true);
    try {
      await api.updateProfile(id, { name: editName.trim(), path: editPath.trim() });
      addLog("Game install updated.", "success");
      setEditId(null);
      await refreshProfiles();
    } catch (e: any) {
      addLog(`Failed to update install: ${e?.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Profile) => {
    if (!window.confirm(`Delete game install "${p.name}"? This does not modify the game files.`)) return;
    setBusy(true);
    try {
      await api.deleteProfile(p.id);
      addLog(`Deleted game install "${p.name}".`, "muted");
      await refreshProfiles();
    } catch (e: any) {
      addLog(`Failed to delete install: ${e?.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Game installs</CardTitle>
        {!adding && (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus /> Add install
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        {profiles.length === 0 && !adding && (
          <p className="text-sm text-muted-foreground">No game installs configured yet.</p>
        )}

        {profiles.map((p) => {
          const isActive = p.id === activeProfile;
          const isEditing = editId === p.id;
          return (
            <div
              key={p.id}
              className={cn(
                "rounded-md border p-3 transition-colors",
                isActive ? "border-primary/50 bg-primary/5" : "bg-card/40"
              )}
            >
              {isEditing ? (
                <div className="space-y-2">
                  <div className="space-y-1.5">
                    <Label>Name</Label>
                    <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Path</Label>
                    <div className="flex gap-2">
                      <Input value={editPath} onChange={(e) => setEditPath(e.target.value)} />
                      <Button variant="outline" size="icon" title="Browse"
                              onClick={async () => { const d = await pickDirectory(); if (d) setEditPath(d); }}>
                        <FolderOpen />
                      </Button>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={busy || !editName.trim() || !editPath.trim()}
                            onClick={() => saveEdit(p.id)}>
                      <Check /> Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setEditId(null)}>
                      <X /> Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-foreground">{p.name}</p>
                      <Badge variant={p.game === "KOTOR1" ? "info" : "secondary"}>
                        {GAME_LABEL[p.game]}
                      </Badge>
                      {p.is_default && (
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title="Default install">
                          <Star className="size-3" /> default
                        </span>
                      )}
                    </div>
                    <p className="truncate font-mono text-xs text-muted-foreground" title={p.path}>
                      {p.path || "(no path set)"}
                    </p>
                  </div>
                  {isActive ? (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-[hsl(var(--success))]">
                      <CheckCircle2 className="size-3.5" /> Active
                    </span>
                  ) : (
                    <Button variant="ghost" size="sm" onClick={() => makeActive(p.id)}>
                      Set active
                    </Button>
                  )}
                  <Button variant="ghost" size="icon" className="size-8" title="Edit"
                          onClick={() => startEdit(p)}>
                    <Pencil />
                  </Button>
                  <Button variant="ghost" size="icon" className="size-8" title="Delete"
                          disabled={p.is_default || busy} onClick={() => remove(p)}>
                    <Trash2 />
                  </Button>
                </div>
              )}
            </div>
          );
        })}

        {adding && (
          <div className="rounded-md border bg-card/40 p-3">
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1 space-y-1.5">
                  <Label>Name</Label>
                  <Input value={newName} placeholder="e.g. KOTOR 1 (Steam)"
                         onChange={(e) => setNewName(e.target.value)} />
                </div>
                <div className="w-40 space-y-1.5">
                  <Label>Game</Label>
                  <Select value={newGame} onChange={(e) => setNewGame(e.target.value as GameKey)}>
                    <option value="KOTOR1">KOTOR 1</option>
                    <option value="KOTOR2">KOTOR 2</option>
                  </Select>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Path</Label>
                <div className="flex gap-2">
                  <Input value={newPath} placeholder="Game installation folder"
                         onChange={(e) => setNewPath(e.target.value)} />
                  <Button variant="outline" size="icon" title="Browse"
                          onClick={async () => { const d = await pickDirectory(); if (d) setNewPath(d); }}>
                    <FolderOpen />
                  </Button>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy || !newName.trim() || !newPath.trim()} onClick={create}>
                  <Check /> Add
                </Button>
                <Button variant="ghost" size="sm" onClick={resetAdd}>
                  <X /> Cancel
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
