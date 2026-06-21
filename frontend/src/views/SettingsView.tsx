import { useState } from "react";
import {
  SlidersHorizontal, Gamepad2, User, Zap, RefreshCw, type LucideIcon,
} from "lucide-react";
import type { AppStatus, Profile } from "@/lib/api";
import { cn } from "@/lib/utils";
import { GeneralSection } from "@/views/settings/GeneralSection";
import { GameInstallsSection } from "@/views/settings/GameInstallsSection";
import { AccountSection } from "@/views/settings/AccountSection";
import { PatcherSection } from "@/views/settings/PatcherSection";
import { UpdatesSection } from "@/views/settings/UpdatesSection";
import { useT } from "@/lib/i18n";

type SectionId = "general" | "installs" | "account" | "patcher" | "updates";

const SECTIONS: { id: SectionId; labelKey: string; icon: LucideIcon }[] = [
  { id: "general", labelKey: "settings.section.general", icon: SlidersHorizontal },
  { id: "installs", labelKey: "settings.section.installs", icon: Gamepad2 },
  { id: "account", labelKey: "settings.section.account", icon: User },
  { id: "patcher", labelKey: "settings.section.patcher", icon: Zap },
  { id: "updates", labelKey: "settings.section.updates", icon: RefreshCw },
];

interface SettingsViewProps {
  status: AppStatus | null;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
  addLog: (message: string, tag?: string) => void;
  profiles: Profile[];
  activeProfile: string;
  setActiveProfile: (id: string) => void;
  refreshProfiles: () => Promise<void> | void;
}

export function SettingsView({
  status, username, onSignIn, onSignOut, addLog,
  profiles, activeProfile, setActiveProfile, refreshProfiles,
}: SettingsViewProps) {
  const t = useT();
  const [section, setSection] = useState<SectionId>("general");

  return (
    <div className="flex h-full flex-col">
      <header className="border-b bg-card/30 px-5 py-3">
        <h1 className="text-base font-semibold">{t("settings.title")}</h1>
        <p className="text-xs text-muted-foreground">{t("settings.subtitle")}</p>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Secondary sidebar */}
        <nav className="w-52 shrink-0 space-y-1 overflow-y-auto border-r bg-card/20 p-3">
          {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setSection(id)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                section === id
                  ? "bg-sidebar-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
              )}
            >
              <Icon className="size-4 shrink-0" />
              <span className="flex-1 truncate text-left">{t(labelKey)}</span>
            </button>
          ))}
        </nav>

        {/* Content */}
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className="mx-auto max-w-2xl space-y-4">
            {section === "general" && <GeneralSection addLog={addLog} />}
            {section === "installs" && (
              <GameInstallsSection
                profiles={profiles}
                activeProfile={activeProfile}
                setActiveProfile={setActiveProfile}
                refreshProfiles={refreshProfiles}
                addLog={addLog}
              />
            )}
            {section === "account" && (
              <AccountSection
                status={status}
                username={username}
                onSignIn={onSignIn}
                onSignOut={onSignOut}
                addLog={addLog}
              />
            )}
            {section === "patcher" && <PatcherSection status={status} addLog={addLog} />}
            {section === "updates" && <UpdatesSection status={status} addLog={addLog} />}
          </div>
        </div>
      </div>
    </div>
  );
}
