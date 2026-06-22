import { useEffect, useState } from "react";
import { X, ExternalLink, Loader2 } from "lucide-react";
import { api, type BuildMod, type ModInfo } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Screenshots } from "@/components/Screenshots";
import { useT } from "@/lib/i18n";

interface BuildModDetailProps {
  mod: BuildMod;
  onClose: () => void;
}

// Lightweight detail drawer for a build mod (no installed-file data - that's
// only available once a mod is in the library).
export function BuildModDetail({ mod, onClose }: BuildModDetailProps) {
  const t = useT();
  const [info, setInfo] = useState<ModInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    setInfoLoading(true);
    api.modInfo(mod.file_id, mod.slug, mod.game)
      .then((r) => { if (alive) setInfo(r); })
      .catch(() => { if (alive) setInfo(null); })
      .finally(() => { if (alive) setInfoLoading(false); });
    return () => { alive = false; };
  }, [mod.file_id, mod.slug, mod.game]);

  const title = info?.title?.trim() || mod.name;
  const description = info?.description?.trim();
  const images = info?.images ?? [];
  const note = mod.note?.trim();
  const summary = mod.directive_summary?.trim();
  const instructions = mod.instructions?.trim();

  const links: { label: string; url?: string }[] = [
    { label: t("modDetail.viewOnDeadlyStream"), url: info?.ds_url || mod.url },
    { label: t("modDetail.viewOnNexus"), url: info?.nexus_url },
  ];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 animate-fade-in" onClick={onClose} />
      <aside className="relative z-10 flex h-full w-full max-w-lg animate-fade-in flex-col border-l bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-start gap-3 border-b p-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold leading-tight" title={title}>{title}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Badge variant={mod.game === "KOTOR1" ? "info" : "secondary"}>{mod.game}</Badge>
              {mod.install_method_hint && <Badge variant="muted">{mod.install_method_hint}</Badge>}
              {info?.author && <span className="text-xs text-muted-foreground">{info.author}</span>}
            </div>
          </div>
          <button onClick={onClose} className="shrink-0 rounded-sm text-muted-foreground transition-colors hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 space-y-5 overflow-auto p-4">
          {/* What the installer will do automatically for this mod */}
          {summary && (
            <section className="rounded-md border border-[hsl(var(--info)/0.4)] bg-[hsl(var(--info)/0.08)] p-3">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--info))]">
                {t("modDetail.autoHandling")}
              </h3>
              <p className="text-sm leading-relaxed text-foreground">
                {t("modDetail.autoHandlingPrefix")} {summary}.
              </p>
            </section>
          )}

          {/* Install instructions straight from the build guide */}
          {instructions && (
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("modDetail.guideInstructions")}
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{instructions}</p>
            </section>
          )}

          {/* Build note */}
          {note && (
            <section className="rounded-md border border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.08)] p-3">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--warning))]">
                {t("modDetail.buildNote")}
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{note}</p>
            </section>
          )}

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
          {!infoLoading && images.length > 0 && <Screenshots images={images} />}

          {/* Links */}
          {links.some((l) => l.url) && (
            <section className="flex flex-wrap gap-2">
              {links.filter((l) => l.url).map((l) => (
                <Button key={l.label} variant="outline" size="sm"
                        onClick={() => api.openUrl(l.url!).catch(() => {})}>
                  <ExternalLink /> {l.label}
                </Button>
              ))}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
