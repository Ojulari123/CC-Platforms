import { computed, getCurrentScope, onScopeDispose, ref } from "vue";
import type { ResolvedTheme, ThemeChoice } from "../utils/theme";
import { THEME_KEY, isThemeChoice, readThemeCookie, resolveTheme, themeCookieDomain, writeThemeCookie } from "../utils/theme";

/* The theme the person chose, which is not the theme they see: "system" is a choice, and
   the OS answers it. Both are exposed because the toggle has to show three states while
   everything else only cares about two.

   State is module-level rather than per-caller so the toggle in TopBar and anything else
   that asks agree, and so a second caller does not re-read storage. */

const choice = ref<ThemeChoice>("system");
const systemPrefersDark = ref(true);
let hydrated = false;
let detach: (() => void) | null = null;
let consumers = 0;

function query(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia("(prefers-color-scheme: dark)");
}

/* Where the cookie is written. Empty on one host, the parent domain (".example.com") when
   the products are deployed on subdomains — a host-only cookie is not shared between them,
   so the theme would stop following the person from Pulse to Identity. It comes from
   `runtimeConfig.public.themeCookieDomain`, and the same value reaches the pre-boot script
   as an attribute on <html>; `themeCookieDomain()` reads that attribute so the two agree
   even in contexts with no Nuxt runtime config (tests, the login screens). */
function domain(): string {
  try {
    const configured = useRuntimeConfig().public.themeCookieDomain;
    if (typeof configured === "string" && configured) return configured;
  } catch {
    // Called outside a Nuxt app. The rendered attribute is the fallback.
  }
  return themeCookieDomain();
}

function read(): ThemeChoice {
  try {
    const cookie = readThemeCookie(domain());
    if (cookie) return cookie;
    /* The choice used to live in localStorage. Anyone who picked one before the move
       still has it there, on this origin only; carry it over once so the switch does not
       silently reset them. */
    const stored = window.localStorage.getItem(THEME_KEY);
    if (isThemeChoice(stored)) {
      writeThemeCookie(stored, domain());
      window.localStorage.removeItem(THEME_KEY);
      return stored;
    }
    return "system";
  } catch {
    /* Storage can throw outright, not just return null — Safari's private mode and a
       browser with cookies switched off both do it. Dark is what `:root` and the boot
       script fall back to, so answering dark here keeps the three in step. */
    return "dark";
  }
}

// The attribute the tokens are keyed off. Written directly rather than through a watcher:
// a watcher created at module scope belongs to no effect scope and never gets torn down.
function paint(): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = resolveTheme(choice.value, systemPrefersDark.value);
}

function hydrate(): void {
  if (hydrated) return;
  hydrated = true;
  const mq = query();
  if (mq) systemPrefersDark.value = mq.matches;
  choice.value = read();
  paint();
}

/* The OS setting can flip while the app is open — macOS does it on a schedule — and a
   "system" choice that reads the preference once is not following the system. One
   listener for the whole app, because the state it writes to is one thing; it is
   reference-counted rather than left attached so a caller inside a component scope takes
   it down with itself. A caller outside any scope (a test, a plugin) still gets the live
   behaviour and simply has nothing to release it. */
function attach(): void {
  if (detach) return;
  const mq = query();
  if (!mq) return;
  const onChange = (event: MediaQueryListEvent) => {
    systemPrefersDark.value = event.matches;
    paint();
  };
  mq.addEventListener("change", onChange);
  detach = () => {
    mq.removeEventListener("change", onChange);
    detach = null;
  };
}

export function useTheme() {
  hydrate();
  attach();

  if (getCurrentScope()) {
    consumers += 1;
    onScopeDispose(() => {
      consumers -= 1;
      if (consumers === 0) detach?.();
    });
  }

  function setTheme(next: ThemeChoice): void {
    choice.value = next;
    paint();
    try {
      writeThemeCookie(next, domain());
    } catch {
      // Unwritable storage costs the choice its persistence, not the session its theme.
    }
  }

  return {
    theme: computed<ThemeChoice>(() => choice.value),
    resolved: computed<ResolvedTheme>(() => resolveTheme(choice.value, systemPrefersDark.value)),
    setTheme,
  };
}
