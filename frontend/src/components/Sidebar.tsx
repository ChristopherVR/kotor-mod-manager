import { Zap } from "lucide-react";
import type { AppStatus } from "@/lib/api";
import { NAV_ITEMS, type ViewId } from "@/lib/views";
import { NavItem } from "@/components/NavItem";
import { AccountMenu } from "@/components/AccountMenu";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useT } from "@/lib/i18n";

interface SidebarProps {
  active: ViewId;
  onNavigate: (v: ViewId) => void;
  status: AppStatus | null;
  username: string;
  running: boolean;
  overallPct: number;
  conflictCount: number;
  onSignIn: () => void;
  onSignOut: () => void;
}

export function Sidebar({
  active, onNavigate, status, username, running, overallPct, conflictCount, onSignIn, onSignOut,
}: SidebarProps) {
  const t = useT();
  const navItems = NAV_ITEMS.filter((n) => n.id !== "settings");
  const settingsItem = NAV_ITEMS.find((n) => n.id === "settings")!;

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <Zap className="size-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{t("brand.title")}</p>
          {status && <p className="text-xs text-muted-foreground">v{status.version}</p>}
        </div>
      </div>

      {/* Nav (incl. Settings, all above the account footer) */}
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3">
        {navItems.map((item) => {
          let trailing: React.ReactNode = null;
          if (item.id === "conflicts" && conflictCount > 0) {
            trailing = <Badge variant="warning" className="px-1.5 py-0 text-[10px]">{conflictCount}</Badge>;
          } else if (item.id === "builds" && running) {
            trailing = (
              <span className="font-mono text-[11px] text-muted-foreground">{Math.round(overallPct)}%</span>
            );
          }
          return (
            <NavItem
              key={item.id}
              icon={item.icon}
              label={t(item.labelKey)}
              active={active === item.id}
              onClick={() => onNavigate(item.id)}
              trailing={trailing}
            />
          );
        })}
        <NavItem
          icon={settingsItem.icon}
          label={t(settingsItem.labelKey)}
          active={active === "settings"}
          onClick={() => onNavigate("settings")}
        />
      </nav>

      {/* Account footer - pinned at the very bottom, below all nav items */}
      <Separator className="bg-sidebar-border" />
      <div className="p-3">
        <AccountMenu
          loggedIn={!!status?.logged_in}
          username={username}
          onSignIn={onSignIn}
          onSignOut={onSignOut}
        />
      </div>
    </aside>
  );
}
