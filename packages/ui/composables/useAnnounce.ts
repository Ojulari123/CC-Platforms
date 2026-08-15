// A live region has to be in the document *before* the text appears in it — screen
// readers routinely miss one that is inserted with its message already inside.
// ProductShell mounts an empty one; anything rendered outside the shell gets this
// fallback, under a different id so the two never collide.
export const LIVE_REGION_ID = "cc-live-region";

const FALLBACK_ID = `${LIVE_REGION_ID}-fallback`;

function liveRegion(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  let el = document.getElementById(LIVE_REGION_ID) ?? document.getElementById(FALLBACK_ID);
  if (!el) {
    el = document.createElement("div");
    el.id = FALLBACK_ID;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.className = "sr-only";
    document.body.appendChild(el);
  }
  return el;
}

// Say something to a screen reader without showing it on screen. Cleared first so the
// same message twice still reads twice, and written a tick later so a freshly created
// region is settled before it changes.
export function announce(message: string): void {
  const el = liveRegion();
  if (!el) return;
  el.textContent = "";
  setTimeout(() => {
    el.textContent = message;
  }, 60);
}

export function useAnnounce() {
  return announce;
}
