import { CheckCircle2, LogIn, LogOut } from "lucide-react";
import type { AppStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { useT } from "@/lib/i18n";

interface AccountSectionProps {
  status: AppStatus | null;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
}

export function AccountSection({ status, username, onSignIn, onSignOut }: AccountSectionProps) {
  const t = useT();
  return (
    <Card>
      <CardHeader><CardTitle>{t("settings.account.title")}</CardTitle></CardHeader>
      <CardContent>
        {status?.logged_in ? (
          <div className="flex items-center gap-3">
            <Avatar name={username} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                {username || t("settings.account.signedInName")}
                <CheckCircle2 className="size-4 text-[hsl(var(--success))]" />
              </p>
              <p className="text-xs text-muted-foreground">
                {t("settings.account.signedInHint")}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={onSignOut}>
              <LogOut /> {t("common.signOut")}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">{t("settings.account.notSignedIn")}</p>
              <p className="text-xs text-muted-foreground">
                {t("settings.account.notSignedInHint")}
              </p>
            </div>
            <Button variant="default" size="sm" onClick={onSignIn}>
              <LogIn /> {t("common.signIn")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
