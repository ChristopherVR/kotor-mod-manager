import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, LogIn, LogOut } from "lucide-react";
import { api, type NexusOAuthState, type NexusValidation } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

/**
 * Sign in to Nexus Mods (OAuth). The button opens the Nexus approval page in the
 * browser, then this waits for the app's local callback to complete the sign-in.
 * Shared by Settings and the first-run setup.
 */
export function NexusSignIn({
  addLog,
  onValidated,
}: {
  addLog: (message: string, tag?: string) => void;
  onValidated?: (v: NexusValidation) => void;
}) {
  const t = useT();
  const [oauth, setOauth] = useState<NexusOAuthState | null>(null);
  const [validation, setValidation] = useState<NexusValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // Callers pass these inline; refs keep the effects below from re-running.
  const onValidatedRef = useRef(onValidated);
  onValidatedRef.current = onValidated;
  const addLogRef = useRef(addLog);
  addLogRef.current = addLog;

  const check = useCallback(async () => {
    const v = await api.nexusValidate();
    setValidation(v);
    onValidatedRef.current?.(v);
    return v;
  }, []);

  const refresh = useCallback(() => api.nexusOAuth().then((o) => { setOauth(o); return o; }), []);

  useEffect(() => {
    refresh().then((o) => { if (o.signed_in) check().catch(() => {}); }).catch(() => {});
  }, [refresh, check]);

  // While the Nexus page is open in the browser, watch for the sign-in to finish.
  const waiting = oauth?.flow?.status === "waiting";
  useEffect(() => {
    if (!waiting) return;
    const id = window.setInterval(async () => {
      try {
        const o = await refresh();
        if (o.flow?.status === "done") {
          const v = await check();
          addLogRef.current(v.ok ? `Signed in to Nexus Mods as ${v.name}.` : "Nexus sign-in could not be verified.",
            v.ok ? "success" : "error");
        } else if (o.flow?.status === "error") {
          setFailed(true);
          addLogRef.current(`Nexus sign-in did not finish (${o.flow.error ?? "error"}).`, "error");
        }
      } catch { /* backend busy; try again next tick */ }
    }, 1500);
    return () => window.clearInterval(id);
  }, [waiting, refresh, check]);

  const signIn = async () => {
    setFailed(false);
    setBusy(true);
    try {
      const { url } = await api.nexusOAuthStart();
      await refresh();
      await api.openUrl(url);
    } catch (e: any) {
      setFailed(true);
      addLog(`Could not start Nexus sign-in: ${e?.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    await api.nexusOAuthCancel().catch(() => {});
    await refresh().catch(() => {});
  };

  const signOut = async () => {
    setBusy(true);
    try {
      await api.nexusSignOut();
      await refresh();
      setValidation(null);
      onValidatedRef.current?.({ ok: false });
      addLog("Signed out of Nexus Mods.", "info");
    } finally {
      setBusy(false);
    }
  };

  const available = !!oauth?.available;
  const signedIn = available && !!oauth?.signed_in;

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{t("settings.nexus.hint")}</p>

      {signedIn ? (
        <div className="flex items-center gap-3">
          <p className="flex min-w-0 flex-1 items-center gap-1.5 text-sm font-medium text-foreground">
            <CheckCircle2 className="size-4 shrink-0 text-[hsl(var(--success))]" />
            {t("settings.nexus.signedInAs", { name: validation?.name || oauth!.name })}
            {(validation?.is_premium ?? oauth!.is_premium) ? " · Premium" : ""}
          </p>
          <Button variant="outline" size="sm" onClick={signOut} disabled={busy}>
            <LogOut /> {t("settings.nexus.signOut")}
          </Button>
        </div>
      ) : waiting ? (
        <div className="flex items-center gap-3">
          <p className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 shrink-0 animate-spin" /> {t("settings.nexus.waiting")}
          </p>
          <Button variant="outline" size="sm" onClick={cancel}>{t("settings.nexus.cancel")}</Button>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Button onClick={signIn} disabled={busy || !available}>
            <LogIn /> {t("settings.nexus.signIn")}
          </Button>
          {failed && (
            <p className="flex items-center gap-1.5 text-xs text-[hsl(var(--warning))]">
              <AlertTriangle className="size-3.5" /> {t("settings.nexus.signInFailed")}
            </p>
          )}
        </div>
      )}

      {signedIn && validation?.ok && validation.limits?.daily_remaining !== undefined && (
        <p className="text-xs text-muted-foreground">
          {t("settings.nexus.allowance", {
            daily: validation.limits.daily_remaining,
            hourly: validation.limits.hourly_remaining ?? "?",
          })}
        </p>
      )}
    </div>
  );
}
