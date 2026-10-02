import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

export interface ConfirmRequest {
  id: string;
  title: string;
  body: string;
  options: string[];
}

interface ConfirmDialogProps {
  request: ConfirmRequest | null;
  onAnswer: (id: string, choice: string) => void;
}

// A question from the installer. Closing the window counts as the last option
// (skip), so nothing is ever changed without a click on the first button.
export function ConfirmDialog({ request, onAnswer }: ConfirmDialogProps) {
  const t = useT();
  const label = (o: string) => (o === "continue" || o === "skip" ? t(`confirm.${o}`) : o);
  const decline = request ? request.options[request.options.length - 1] : "";

  return (
    <Dialog
      open={!!request}
      onClose={() => request && onAnswer(request.id, decline)}
      title={request?.title}
      className="max-w-lg"
    >
      <p className="whitespace-pre-line text-sm text-muted-foreground">{request?.body}</p>
      <div className="mt-5 flex justify-end gap-2">
        {request?.options.map((o, i) => (
          <Button
            key={o}
            variant={i === 0 ? "default" : "outline"}
            onClick={() => onAnswer(request.id, o)}
          >
            {label(o)}
          </Button>
        ))}
      </div>
    </Dialog>
  );
}
