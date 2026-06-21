import { LogIn, LogOut } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";

interface AccountMenuProps {
  loggedIn: boolean;
  username: string;
  onSignIn: () => void;
  onSignOut: () => void;
}

export function AccountMenu({ loggedIn, username, onSignIn, onSignOut }: AccountMenuProps) {
  if (!loggedIn) {
    return (
      <Button variant="outline" size="sm" className="w-full" onClick={onSignIn}>
        <LogIn /> Sign in
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2.5">
      <Avatar name={username} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{username || "Account"}</p>
        <p className="truncate text-xs text-muted-foreground">Signed in</p>
      </div>
      <Tooltip content="Sign out" side="top">
        <Button variant="ghost" size="icon" className="size-8" onClick={onSignOut}>
          <LogOut />
        </Button>
      </Tooltip>
    </div>
  );
}
