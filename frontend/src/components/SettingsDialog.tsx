import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
import { api, type Settings } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMPTY: Settings = { kotor1_path: "", kotor2_path: "", download_dir: "" };

export function SettingsDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: (s: Settings) => void;
}) {
  const [s, setS] = useState<Settings>(EMPTY);

  useEffect(() => {
    if (open) api.getSettings().then(setS).catch(() => {});
  }, [open]);

  const browse = async (key: keyof Settings) => {
    const dir = await pickDirectory();
    if (dir) setS((prev) => ({ ...prev, [key]: dir }));
  };

  const save = async () => {
    await api.setSettings(s);
    onSaved?.(s);
    onClose();
  };

  const row = (key: keyof Settings, label: string) => (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input value={s[key]} onChange={(e) => setS({ ...s, [key]: e.target.value })} />
        <Button variant="outline" size="icon" onClick={() => browse(key)} title="Browse">
          <FolderOpen />
        </Button>
      </div>
    </div>
  );

  return (
    <Dialog open={open} onClose={onClose} title="Settings" className="max-w-lg">
      <div className="space-y-3">
        {row("kotor1_path", "KOTOR 1 Installation Path")}
        {row("kotor2_path", "KOTOR 2 Installation Path")}
        {row("download_dir", "Download Folder")}
        <Button className="w-full" onClick={save}>Save & Close</Button>
      </div>
    </Dialog>
  );
}
