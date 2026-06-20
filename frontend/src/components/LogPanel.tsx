import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface LogLine {
  id: number;
  message: string;
  tag: string;
}

const TAG_COLOR: Record<string, string> = {
  success: "text-[hsl(var(--success))]",
  error: "text-destructive",
  warning: "text-[hsl(var(--warning))]",
  info: "text-[hsl(var(--info))]",
  muted: "text-muted-foreground",
};

export function LogPanel({ lines }: { lines: LogLine[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  return (
    <div className="h-full overflow-auto rounded-md bg-[hsl(222_47%_5%)] p-3 font-mono text-xs leading-relaxed">
      {lines.length === 0 && (
        <div className="text-muted-foreground/60">Activity log will appear here…</div>
      )}
      {lines.map((l) => (
        <div key={l.id} className={cn("whitespace-pre-wrap", TAG_COLOR[l.tag] ?? "text-foreground/90")}>
          {l.message}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
