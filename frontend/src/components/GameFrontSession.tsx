import { useState } from "react";
import { api } from "@/lib/api";
import { closeGameFront, isTauri, openGameFront } from "@/lib/tauri";
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
        // Without the backend the window can still open on the sign-in page.
        const request = await api.gamefrontRequest().then(r => r.request, () => null);
        await openGameFront(request);
        setMessage("GameFront is open. Choose Stay logged in when signing in. You can reopen this window at any time.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not open GameFront.");
    } finally { setBusy(false); }
  };
  const close = async () => {
    try {
      await closeGameFront();
      setMessage("The GameFront window was closed. You can open it again at any time.");
    } catch {
      setMessage("Could not close the GameFront window. Restarting the app closes it.");
    }
  };
  return <Card>
    <CardHeader><CardTitle>GameFront</CardTitle></CardHeader>
    <CardContent className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Sign in once in the GameFront window and choose Stay logged in. Your browser session
        is saved on this device and reused for mod downloads. GameFront may occasionally
        ask you to verify again. To sign out, use Logout in that window. If the window
        stays blank or will not close, use Close GameFront window, then try your regular browser.
      </p>
      <div className="flex flex-wrap gap-2">
        {isTauri() && <Button disabled={busy} onClick={() => open(false)}>Open saved GameFront session</Button>}
        <Button variant="outline" disabled={busy} onClick={() => open(true)}>Use my regular browser</Button>
        {isTauri() && <Button variant="ghost" onClick={close}>Close GameFront window</Button>}
      </div>
      {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    </CardContent>
  </Card>;
}
