import { useState } from "react";
import { api } from "@/lib/api";
import { isTauri, openGameFront } from "@/lib/tauri";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function GameFrontSession() {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const open = async (external: boolean) => {
    setBusy(true);
    try {
      if (external) {
        const result = await api.gamefrontExternal();
        setMessage(`Save the mod archive in ${result.destination}.`);
      } else {
        const { request } = await api.gamefrontRequest();
        await openGameFront(request);
        setMessage("GameFront is open. Choose Stay logged in when signing in. You can reopen this window at any time.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open GameFront.");
    } finally { setBusy(false); }
  };
  return <Card>
    <CardHeader><CardTitle>GameFront</CardTitle></CardHeader>
    <CardContent className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Sign in once in the GameFront window and choose Stay logged in. Your browser session
        is saved on this device and reused for mod downloads. GameFront may occasionally
        ask you to verify again. To sign out, use Logout in that window.
      </p>
      <div className="flex flex-wrap gap-2">
        {isTauri() && <Button disabled={busy} onClick={() => open(false)}>Open saved GameFront session</Button>}
        <Button variant="outline" disabled={busy} onClick={() => open(true)}>Use my regular browser</Button>
      </div>
      {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    </CardContent>
  </Card>;
}
