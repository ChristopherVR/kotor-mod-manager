import { useEffect, useState } from "react";
import { FolderOpen, CheckCircle2, LogIn, LogOut, Zap, AlertTriangle } from "lucide-react";
import { api, type AppStatus, type Settings } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMPTY: Settings = { kotor1_path: "", kotor2_path: "", download_dir: "" };

interface SettingsViewProps {
  status: AppStatus | null;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
  addLog: (message: string, tag?: string) => void;
}

export function SettingsView({ status, username, onSignIn, onSignOut, addLog }: SettingsViewProps) {
  const [s, setS] = useState<Settings>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then(setS).catch(() => {});
  }, []);

  const browse = async (key: keyof Settings) => {
    const dir = await pickDirectory();
    if (dir) setS((prev) => ({ ...prev, [key]: dir }));
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

  const row = (key: keyof Settings, label: string) => (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input value={s[key]} onChange={(e) => { setSaved(false); setS({ ...s, [key]: e.target.value }); }} />
        <Button variant="outline" size="icon" onClick={() => browse(key)} title="Browse">
          <FolderOpen />
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <header className="border-b bg-card/30 px-5 py-3">
        <h1 className="text-base font-semibold">Settings</h1>
        <p className="text-xs text-muted-foreground">Game paths, downloads, and account</p>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="mx-auto max-w-2xl space-y-4">
          <Card>
            <CardHeader><CardTitle>Game paths</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {row("kotor1_path", "KOTOR 1 Installation Path")}
              {row("kotor2_path", "KOTOR 2 Installation Path")}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Downloads</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {row("download_dir", "Download Folder")}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Account</CardTitle></CardHeader>
            <CardContent>
              {status?.logged_in ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1.5 text-sm text-[hsl(var(--success))]">
                    <CheckCircle2 className="size-4" /> {username || "Signed in"}
                  </span>
                  <Button variant="outline" size="sm" className="ml-auto" onClick={onSignOut}>
                    <LogOut /> Sign out
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground">Not signed in to DeadlyStream.</span>
                  <Button variant="default" size="sm" className="ml-auto" onClick={onSignIn}>
                    <LogIn /> Sign in
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Headless patcher</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {status?.shim_available ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--success)/0.15)] px-2.5 py-0.5 text-xs font-medium text-[hsl(var(--success))]">
                  <Zap className="size-3.5" /> Headless patcher ready
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--warning)/0.15)] px-2.5 py-0.5 text-xs font-medium text-[hsl(var(--warning))]">
                  <AlertTriangle className="size-3.5" /> No HoloPatcher shim
                </span>
              )}
              {status?.shim_path && (
                <p className="truncate font-mono text-xs text-muted-foreground" title={status.shim_path}>
                  {status.shim_path}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>About</CardTitle></CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                KOTOR Mod Installer{status ? ` v${status.version}` : ""}
              </p>
            </CardContent>
          </Card>

          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save settings"}</Button>
            {saved && <span className="text-xs text-[hsl(var(--success))]">Saved</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
