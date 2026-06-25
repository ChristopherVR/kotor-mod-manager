import type { ModStatus } from "./api";

type BadgeVariant =
  | "default" | "secondary" | "muted" | "success" | "warning" | "info" | "destructive" | "outline";

export const STATUS_META: Record<ModStatus, { label: string; variant: BadgeVariant; dot: string }> = {
  PENDING:         { label: "Pending",     variant: "muted",       dot: "bg-muted-foreground" },
  DOWNLOADING:     { label: "Downloading", variant: "info",        dot: "bg-[hsl(var(--info))]" },
  EXTRACTING:      { label: "Extracting",  variant: "info",        dot: "bg-[hsl(var(--info))]" },
  READY:           { label: "Ready",       variant: "warning",     dot: "bg-[hsl(var(--warning))]" },
  INSTALLING:      { label: "Installing",  variant: "warning",     dot: "bg-[hsl(var(--warning))]" },
  WAITING_PATCHER: { label: "Patcher",     variant: "warning",     dot: "bg-[hsl(var(--warning))]" },
  DONE:            { label: "Done",        variant: "success",     dot: "bg-[hsl(var(--success))]" },
  SKIPPED:         { label: "Skipped",     variant: "muted",       dot: "bg-muted-foreground" },
  MANUAL:          { label: "Manual step", variant: "warning",     dot: "bg-[hsl(var(--warning))]" },
  ERROR:           { label: "Error",       variant: "destructive", dot: "bg-destructive" },
};

export const ACTIVE_STATUSES: ModStatus[] = ["DOWNLOADING", "EXTRACTING", "INSTALLING", "WAITING_PATCHER"];
