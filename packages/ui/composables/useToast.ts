import type { Tone, ToastMessage } from "../types/ui";

// One toast at a time, shared across the screen. A second call while the first is up
// retargets the same node rather than stacking a queue nobody reads.
export function useToast() {
  const toast = useState<ToastMessage | null>("ui.toast", () => null);

  function show(message: string, tone: Tone = "muted") {
    toast.value = { message, tone };
  }

  function clear() {
    toast.value = null;
  }

  return { toast, show, clear };
}
