import { useEffect, useState } from "react";
import {
  X, ExternalLink, Trash2, FileText, ImageOff, Loader2,
} from "lucide-react";
import {
  api, type LibraryMod, type ModInfo, type DeployedFile, type BakedFile,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

interface ModDetailProps {
  mod: LibraryMod;
  profile: string;
  onClose: () => void;
  onToggle: (next: boolean) => void;
  onUninstalled: () => void;
  addLog: (message: string, tag?: string) => void;
}

function fmtSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function ModDetail({ mod, profile, onClose, onToggle, onUninstalled, addLog }: ModDetailProps) {
  const t = useT();
  const [info, setInfo] = useState<ModInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState(true);
  const [deployed, setDeployed] = useState<DeployedFile[]>([]);
  const [baked, setBaked] = useState<BakedFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(true);
  const [uninstalling, setUninstalling] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    setInfoLoading(true);
    api.modInfo(mod.source_ref, mod.source_slug, mod.game)
      .then((r) => { if (alive) setInfo(r); })
      .catch(() => { if (alive) setInfo(null); })
      .finally(() => { if (alive) setInfoLoading(false); });

    setFilesLoading(true);
    api.libraryDetail(mod.id, profile)
      .then((r) => { if (alive) { setDeployed(r.deployed_files ?? []); setBaked(r.baked_files ?? []); } })
      .catch(() => { if (alive) { setDeployed([]); setBaked([]); } })
      .finally(() => { if (alive) setFilesLoading(false); });

    return () => { alive = false; };
  }, [mod.id, mod.source_ref, mod.source_slug, mod.game, profile]);

  const uninstall = async () => {
    if (!window.confirm(t("modDetail.uninstallConfirm", { name: mod.name }))) return;
    setUninstalling(true);
    try {
      await api.libraryUninstall(profile, mod.id);
      addLog(`Uninstalled ${mod.name}.`, "success");
      onUninstalled();
      onClose();
    } catch (e: any) {
      addLog(`Failed to uninstall ${mod.name}: ${e?.message}`, "error");
      setUninstalling(false);
    }
  };

  const description = info?.description?.trim();
  const images = info?.images ?? [];
  const baked_mode = mod.deploy_kind === "baked" || (deployed.length === 0 && baked.length > 0);

  const links: { label: string; url?: string }[] = [
    { label: t("modDetail.viewOnDeadlyStream"), url: info?.ds_url },
    { label: t("modDetail.viewOnNexus"), url: info?.nexus_url },
  ];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 animate-fade-in" onClick={onClose} />
      <aside className="relative z-10 flex h-full w-full max-w-lg animate-fade-in flex-col border-l bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-start gap-3 border-b p-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-tight" title={mod.name}>{mod.name}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Badge variant={mod.game === "KOTOR1" ? "info" : "secondary"}>{mod.game}</Badge>
              {mod.install_method && <Badge variant="muted">{mod.install_method}</Badge>}
              <Badge variant={mod.enabled ? "success" : "muted"}>{mod.enabled ? t("library.enabled") : t("library.disabled")}</Badge>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Switch checked={mod.enabled} disabled={!mod.toggleable} onCheckedChange={onToggle} />
            <button onClick={onClose} className="rounded-sm text-muted-foreground transition-colors hover:text-foreground">
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 space-y-5 overflow-auto p-4">
          {/* Description */}
          <section>
            {infoLoading ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> {t("modDetail.loadingDetails")}
              </p>
            ) : description ? (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{description}</p>
            ) : (
              <p className="text-sm italic text-muted-foreground">{t("modDetail.noDescription")}</p>
            )}
          </section>

          {/* Screenshots */}
          {!infoLoading && images.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("modDetail.screenshots")}</h3>
              <div className="flex flex-wrap gap-2">
                {images.slice(0, 8).map((src, i) => (
                  <a key={i} href={src} onClick={(e) => { e.preventDefault(); api.openUrl(src).catch(() => {}); }}
                     className="group relative block size-24 overflow-hidden rounded-md border bg-muted"
                     title={t("modDetail.openScreenshot")}>
                    <img src={src} alt="" loading="lazy"
                         className="size-full object-cover transition-transform group-hover:scale-105"
                         onError={(e) => {
                           e.currentTarget.style.display = "none";
                           e.currentTarget.parentElement?.classList.add("flex", "items-center", "justify-center");
                         }} />
                    <ImageOff className="pointer-events-none absolute inset-0 m-auto hidden size-5 text-muted-foreground group-[.flex]:block" />
                  </a>
                ))}
              </div>
            </section>
          )}

          {/* Links */}
          {!infoLoading && links.some((l) => l.url) && (
            <section className="flex flex-wrap gap-2">
              {links.filter((l) => l.url).map((l) => (
                <Button key={l.label} variant="outline" size="sm"
                        onClick={() => api.openUrl(l.url!).catch(() => {})}>
                  <ExternalLink /> {l.label}
                </Button>
              ))}
            </section>
          )}

          {/* Assets / files */}
          <section className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {baked_mode ? t("modDetail.modifiedFiles") : t("modDetail.installedFiles")}
            </h3>
            {filesLoading ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> {t("modDetail.loadingFiles")}
              </p>
            ) : baked_mode ? (
              baked.length === 0 ? (
                <p className="text-sm italic text-muted-foreground">{t("modDetail.noFiles")}</p>
              ) : (
                <ul className="max-h-64 space-y-0.5 overflow-auto rounded-md border bg-background/40 p-2">
                  {baked.map((f) => (
                    <li key={f.rel_path} className="flex items-center gap-2 px-1 py-0.5 text-xs">
                      <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate font-mono" title={f.rel_path}>{f.rel_path}</span>
                      {f.created && <Badge variant="muted" className="text-[10px]">{t("modDetail.fileNew")}</Badge>}
                    </li>
                  ))}
                </ul>
              )
            ) : deployed.length === 0 ? (
              <p className="text-sm italic text-muted-foreground">{t("modDetail.noFiles")}</p>
            ) : (
              <ul className="max-h-64 space-y-0.5 overflow-auto rounded-md border bg-background/40 p-2">
                {deployed.map((f) => (
                  <li key={f.rel_path} className="flex items-center gap-2 px-1 py-0.5 text-xs">
                    <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate font-mono" title={f.rel_path}>{f.rel_path}</span>
                    {f.overwrote && <Badge variant="warning" className="text-[10px]">{t("modDetail.fileOverwrote")}</Badge>}
                    <span className="shrink-0 text-muted-foreground">{fmtSize(f.size)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 border-t p-4">
          <Button variant="destructive" size="sm" disabled={uninstalling} onClick={uninstall}
                  className={cn(uninstalling && "opacity-70")}>
            <Trash2 /> {uninstalling ? t("modDetail.uninstalling") : t("modDetail.uninstall")}
          </Button>
        </div>
      </aside>
    </div>
  );
}
