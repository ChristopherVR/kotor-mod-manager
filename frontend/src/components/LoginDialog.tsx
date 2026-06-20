import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export function LoginDialog({
  open,
  onClose,
  onLoggedIn,
}: {
  open: boolean;
  onClose: () => void;
  onLoggedIn: (username: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [save, setSave] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) api.credentials().then((c) => c.username && setUsername(c.username)).catch(() => {});
  }, [open]);

  const submit = async () => {
    setError("");
    setBusy(true);
    try {
      const r = await api.login(username.trim(), password, save);
      onLoggedIn(r.username);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="DeadlyStream Login">
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="u">Username</Label>
          <Input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="p">Password</Label>
          <Input
            id="p"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <div className="flex items-center gap-2 pt-1">
          <Switch id="save" checked={save} onCheckedChange={setSave} />
          <Label htmlFor="save" className="cursor-pointer">Save credentials (Windows Credential Manager)</Label>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button className="w-full" onClick={submit} disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Login"}
        </Button>
      </div>
    </Dialog>
  );
}
