import { CheckCircle2, LogIn, LogOut } from "lucide-react";
import type { AppStatus } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";

interface AccountSectionProps {
  status: AppStatus | null;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
}

export function AccountSection({ status, username, onSignIn, onSignOut }: AccountSectionProps) {
  return (
    <Card>
      <CardHeader><CardTitle>DeadlyStream</CardTitle></CardHeader>
      <CardContent>
        {status?.logged_in ? (
          <div className="flex items-center gap-3">
            <Avatar name={username} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                {username || "Signed in"}
                <CheckCircle2 className="size-4 text-[hsl(var(--success))]" />
              </p>
              <p className="text-xs text-muted-foreground">
                Signed in to DeadlyStream. Premium downloads are available.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={onSignOut}>
              <LogOut /> Sign out
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">Not signed in</p>
              <p className="text-xs text-muted-foreground">
                Sign in to DeadlyStream to download mods that require an account.
              </p>
            </div>
            <Button variant="default" size="sm" onClick={onSignIn}>
              <LogIn /> Sign in
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
