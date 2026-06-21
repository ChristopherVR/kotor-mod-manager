import { useEffect, useState } from "react";
import { CheckCircle2, LogIn, LogOut, ExternalLink, AlertTriangle, Eye, EyeOff } from "lucide-react";
import { api, type AppStatus, type Settings, type NexusValidation } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar } from "@/components/ui/avatar";
import { useT } from "@/lib/i18n";

interface AccountSectionProps {
  status: AppStatus | null;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
  addLog: (message: string, tag?: string) => void;
}

export function AccountSection({ status, username, onSignIn, onSignOut, addLog }: AccountSectionProps) {
  const t = useT();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [nexusKey, setNexusKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [validation, setValidation] = useState<NexusValidation | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setNexusKey(s.nexus_api_key || "");
      if (s.nexus_api_key) api.nexusValidate().then(setValidation).catch(() => {});
    }).catch(() => {});
  }, []);

  const saveNexus = async () => {
    if (!settings) return;
    setBusy(true);
    setValidation(null);
    try {
      await api.setSettings({ ...settings, nexus_api_key: nexusKey.trim() });
      setSettings({ ...settings, nexus_api_key: nexusKey.trim() });
      const v = await api.nexusValidate();
      setValidation(v);
      addLog(v.ok ? `Nexus key valid (${v.name}).` : `Nexus key invalid.`, v.ok ? "success" : "error");
    } catch (e: any) {
      addLog(`Failed to save Nexus key: ${e?.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* DeadlyStream account */}
      <Card>
        <CardHeader><CardTitle>{t("settings.account.title")}</CardTitle></CardHeader>
        <CardContent>
          {status?.logged_in ? (
            <div className="flex items-center gap-3">
              <Avatar name={username} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                  {username || t("settings.account.signedInName")}
                  <CheckCircle2 className="size-4 text-[hsl(var(--success))]" />
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("settings.account.signedInHint")}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={onSignOut}>
                <LogOut /> {t("common.signOut")}
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{t("settings.account.notSignedIn")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("settings.account.notSignedInHint")}
                </p>
              </div>
              <Button variant="default" size="sm" onClick={onSignIn}>
                <LogIn /> {t("common.signIn")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Nexus Mods API key */}
      <Card>
        <CardHeader><CardTitle>{t("settings.nexus.title")}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {t("settings.nexus.hint")}{" "}
            <button
              className="inline-flex items-center gap-0.5 text-[hsl(var(--info))] hover:underline"
              onClick={() => api.openUrl("https://www.nexusmods.com/users/myaccount?tab=api").catch(() => {})}
            >
              {t("settings.nexus.getKey")} <ExternalLink className="size-3" />
            </button>
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="nexuskey">{t("settings.nexus.label")}</Label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  id="nexuskey"
                  type={showKey ? "text" : "password"}
                  value={nexusKey}
                  placeholder={t("settings.nexus.placeholder")}
                  onChange={(e) => { setValidation(null); setNexusKey(e.target.value); }}
                  className="pr-9"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-2.5 text-muted-foreground hover:text-foreground"
                  aria-label={showKey ? t("settings.nexus.hideKey") : t("settings.nexus.showKey")}
                  title={showKey ? t("settings.nexus.hideKey") : t("settings.nexus.showKey")}
                >
                  {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
              <Button onClick={saveNexus} disabled={busy}>
                {busy ? t("settings.nexus.saving") : t("common.save")}
              </Button>
            </div>
          </div>
          {validation && (
            validation.ok ? (
              <p className="flex items-center gap-1.5 text-xs text-[hsl(var(--success))]">
                <CheckCircle2 className="size-3.5" />
                {t("settings.nexus.valid", { name: validation.name ?? "" })}
                {validation.is_premium ? " · Premium" : ""}
              </p>
            ) : (
              <p className="flex items-center gap-1.5 text-xs text-[hsl(var(--warning))]">
                <AlertTriangle className="size-3.5" /> {t("settings.nexus.invalid")}
              </p>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}
