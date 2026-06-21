import { Boxes, Library, GitMerge, ScrollText, Settings, type LucideIcon } from "lucide-react";

export type ViewId = "builds" | "library" | "conflicts" | "activity" | "settings";

export interface NavMeta {
  id: ViewId;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavMeta[] = [
  { id: "builds", label: "Mod Builds", icon: Boxes },
  { id: "library", label: "Library", icon: Library },
  { id: "conflicts", label: "Conflicts", icon: GitMerge },
  { id: "activity", label: "Activity", icon: ScrollText },
  { id: "settings", label: "Settings", icon: Settings },
];
