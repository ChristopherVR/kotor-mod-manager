import { useEffect, useState } from "react";
import { FolderOpen } from "lucide-react";
import { api, type Settings } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useLanguage, LOCALES, type Locale } from "@/lib/i18n";

const EMPTY: Settings = { kotor1_path: "", kotor2_path: "", download_dir: "", language: "en", custom_patcher_path: "", nexus_api_key: "" };

interface GeneralSectionProps {
  addLog: (message: string, tag?: string) => void;
}

export function GeneralSection({ addLog }: GeneralSectionProps) {
  const { t, locale, setLocale } = useLanguage();
  const [s, setS] = useState<Settings>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then(setS).catch(() => {});
  }, []);

  const browse = async () => {
    const dir = await pickDirectory();
    if (dir) { setSaved(false); setS((prev) => ({ ...prev, download_dir: dir })); }
  };

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      // Persist current language alongside other settings.
      await api.setSettings({ ...s, language: locale });
      setSaved(true);
      addLog("Settings saved.", "success");
    } catch (e: any) {
      addLog(`Failed to save settings: ${e?.message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Card>
        <CardHeader><CardTitle>{t("settings.general.language")}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label>{t("settings.general.language")}</Label>
            <Select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="max-w-[16rem]"
            >
              {LOCALES.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t("settings.general.languageHint")}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("settings.general.downloads")}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label>{t("settings.general.downloadFolder")}</Label>
            <div className="flex gap-2">
              <Input
                value={s.download_dir}
                onChange={(e) => { setSaved(false); setS({ ...s, download_dir: e.target.value }); }}
              />
              <Button variant="outline" size="icon" onClick={browse} title={t("common.browse")}>
                <FolderOpen />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("settings.general.downloadFolderHint")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving}>
              {saving ? t("common.saving") : t("common.save")}
            </Button>
            {saved && <span className="text-xs text-[hsl(var(--success))]">{t("common.saved")}</span>}
          </div>
        </CardContent>
      </Card>
    </>
  );
}
