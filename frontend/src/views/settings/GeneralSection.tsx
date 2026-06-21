import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
import { api, type Settings } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMPTY: Settings = { kotor1_path: "", kotor2_path: "", download_dir: "" };

interface GeneralSectionProps {
  addLog: (message: string, tag?: string) => void;
}

export function GeneralSection({ addLog }: GeneralSectionProps) {
  const [s, setS] = useState<Settings>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then(setS).catch(() => {});
  }, []);

  const browse = async () => {
    const dir = await pickDirectory();
    if (dir) { setSaved(false); setS((prev) => ({ ...prev, download_dir: dir })); }
  };

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await api.setSettings(s);
      setSaved(true);
      addLog("Settings saved.", "success");
    } catch (e: any) {
      addLog(`Failed to save settings: ${e?.message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Downloads</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label>Download folder</Label>
          <div className="flex gap-2">
            <Input
              value={s.download_dir}
              onChange={(e) => { setSaved(false); setS({ ...s, download_dir: e.target.value }); }}
            />
            <Button variant="outline" size="icon" onClick={browse} title="Browse">
              <FolderOpen />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Where mod archives are downloaded before installation.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          {saved && <span className="text-xs text-[hsl(var(--success))]">Saved</span>}
        </div>
      </CardContent>
    </Card>
  );
}
