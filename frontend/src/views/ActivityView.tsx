import { LogPanel, type LogLine } from "@/components/LogPanel";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

interface ActivityViewProps {
  logs: LogLine[];
  onClear: () => void;
}

export function ActivityView({ logs, onClear }: ActivityViewProps) {
  const t = useT();
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">{t("activity.title")}</h1>
          <p className="text-xs text-muted-foreground">{t("activity.entries", { count: logs.length })}</p>
        </div>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>{t("common.clear")}</Button>
      </header>
      <div className="min-h-0 flex-1 p-4">
        <LogPanel lines={logs} />
      </div>
    </div>
  );
}
