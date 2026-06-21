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
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-sidebar-accent text-accent-foreground"
          : "text-sidebar-foreground hover:bg-accent/50 hover:text-accent-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="flex-1 truncate text-left">{label}</span>
      {trailing}
    </button>
  );
}
