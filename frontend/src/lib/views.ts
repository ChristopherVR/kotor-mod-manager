import { Boxes, Library, GitMerge, ScrollText, Settings, type LucideIcon } from "lucide-react";

export type ViewId = "builds" | "library" | "conflicts" | "activity" | "settings";

export interface NavMeta {
  id: ViewId;
  labelKey: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavMeta[] = [
  { id: "builds", labelKey: "nav.builds", icon: Boxes },
  { id: "library", labelKey: "nav.library", icon: Library },
  { id: "conflicts", labelKey: "nav.conflicts", icon: GitMerge },
  { id: "activity", labelKey: "nav.activity", icon: ScrollText },
  { id: "settings", labelKey: "nav.settings", icon: Settings },
];
