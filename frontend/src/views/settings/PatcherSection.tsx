import { Zap, AlertTriangle } from "lucide-react";
import type { AppStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PatcherSectionProps {
  status: AppStatus | null;
}

export function PatcherSection({ status }: PatcherSectionProps) {
  const ready = !!status?.shim_available;
  return (
    <Card>
      <CardHeader><CardTitle>Patcher engine</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          TSLPatcher mods are applied automatically by a bundled HoloPatcher engine,
          so you don't click through each mod's installer.
        </p>
        {ready ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--success)/0.15)] px-2.5 py-0.5 text-xs font-medium text-[hsl(var(--success))]">
            <Zap className="size-3.5" /> Ready
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--warning)/0.15)] px-2.5 py-0.5 text-xs font-medium text-[hsl(var(--warning))]">
            <AlertTriangle className="size-3.5" /> Not available
          </span>
        )}
        {status?.shim_path && (
          <p className="truncate font-mono text-xs text-muted-foreground" title={status.shim_path}>
            {status.shim_path}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
