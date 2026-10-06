import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItemProps {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
}

export function NavItem({ icon: Icon, label, active, onClick, trailing }: NavItemProps) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 rounded-sm border-l-2 px-3 py-2.5 text-sm font-medium transition-colors",
        active
          ? "border-primary bg-sidebar-accent text-primary"
          : "border-transparent text-sidebar-foreground hover:bg-accent/50 hover:text-accent-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="flex-1 truncate text-left">{label}</span>
      {trailing}
    </button>
  );
}
