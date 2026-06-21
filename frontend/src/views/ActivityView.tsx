import { LogPanel, type LogLine } from "@/components/LogPanel";
import { Button } from "@/components/ui/button";

interface ActivityViewProps {
  logs: LogLine[];
  onClear: () => void;
}

export function ActivityView({ logs, onClear }: ActivityViewProps) {
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">Activity</h1>
          <p className="text-xs text-muted-foreground">{logs.length} log entries</p>
        </div>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>Clear</Button>
      </header>
      <div className="min-h-0 flex-1 p-4">
        <LogPanel lines={logs} />
      </div>
    </div>
  );
}
