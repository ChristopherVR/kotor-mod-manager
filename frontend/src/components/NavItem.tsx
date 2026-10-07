import { cn } from "@/lib/utils";

interface NavItemProps {
  label: string;
  active?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
}

export function NavItem({ label, active, onClick, trailing }: NavItemProps) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        active
          ? "bg-sidebar-accent font-medium text-foreground"
          : "text-sidebar-foreground hover:bg-accent/50 hover:text-foreground"
      )}
    >
      <span className="flex-1 truncate text-left">{label}</span>
      {trailing}
    </button>
  );
}
