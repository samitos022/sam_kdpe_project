import { useState } from "react";
import { Button } from "../ui/Button";

export function FreezeButton({ onFreeze }: { onFreeze: () => void }) {
  const [confirming, setConfirming] = useState(false);
 
  if (confirming) {
    return (
      <div className="flex gap-1">
        <Button size="sm" variant="danger" onClick={() => { onFreeze(); setConfirming(false); }}>
          Confirm
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
          Cancel
        </Button>
      </div>
    );
  }
 
  return (
    <Button size="sm" variant="secondary" onClick={() => setConfirming(true)}>
      🔒 Freeze
    </Button>
  );
}
