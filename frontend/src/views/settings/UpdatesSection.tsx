import { useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { api, type AppStatus, type UpdateInfo } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface UpdatesSectionProps {
  status: AppStatus | null;
  addLog: (message: string, tag?: string) => void;
}

export function UpdatesSection({ status, addLog }: UpdatesSectionProps) {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    api.updateCheck().then(setUpdate).catch(() => {});
  }, []);

  const checkUpdates = async () => {
    setChecking(true);
    try {
      const info = await api.updateCheck();
      setUpdate(info);
      if (info.available) addLog(`Update available: v${info.latest_version}`, "info");
      else if (!info.error) addLog("You're on the latest version.", "muted");
    } catch (e: any) {
      addLog(`Update check failed: ${e?.message}`, "error");
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Updates</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">
            KOTOR Mod Installer{" "}
            <span className="font-mono text-foreground">
              v{update?.current_version ?? status?.version ?? "?"}
            </span>
          </p>
          <Button variant="outline" size="sm" className="ml-auto"
                  onClick={checkUpdates} disabled={checking}>
            <RefreshCw className={checking ? "animate-spin" : ""} />
            {checking ? "Checking…" : "Check for updates"}
          </Button>
        </div>
        {update?.available ? (
          <div className="rounded-md border border-[hsl(var(--info)/0.4)] bg-[hsl(var(--info)/0.1)] p-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[hsl(var(--info))]">
                Version {update.latest_version} is available
              </span>
              <Button size="sm" className="ml-auto"
                      onClick={() => api.updateOpen(update.url ?? undefined).catch(() => {})}>
                <Download /> Get update
              </Button>
            </div>
            {update.notes && (
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap font-sans text-xs text-muted-foreground">
                {update.notes}
              </pre>
            )}
          </div>
        ) : update && !update.error ? (
          <p className="text-xs text-[hsl(var(--success))]">You're on the latest version.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
