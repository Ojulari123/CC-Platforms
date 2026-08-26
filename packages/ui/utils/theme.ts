export type ThemeChoice = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_CHOICES: ThemeChoice[] = ["system", "light", "dark"];

/* One name for all three products, deliberately not namespaced by
   `runtimeConfig.public.authStoragePrefix` the way the token storage is. That prefix
   exists so one product cannot read or clobber another product's *session*; a theme
   preference is not a credential, and the three apps are one platform to the person
   using them.

   It is a cookie rather than localStorage because localStorage is scoped per *origin*,
   and origin includes the port: in dev the three products sit on :3000/:3001/:3002, so a
   stored choice reset at every hop. Cookies are scoped by host and path only, so one
   cookie on `localhost` is shared by all three ports (and, in production, one on the
   parent domain is shared across its subdomains).

   The boot script below hardcodes the same string. It has to: it runs before Nuxt, so
   it cannot import anything. */
export const THEME_KEY = "meridian.theme";

// A year. The choice is a preference, not a session, and re-picking it every month is
// exactly the resetting this cookie exists to stop.
export const THEME_MAX_AGE = 60 * 60 * 24 * 365;

const COOKIE_PATTERN = `(?:^|; )${THEME_KEY.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]*)`;

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): ResolvedTheme {
  if (choice === "system") return systemPrefersDark ? "dark" : "light";
  return choice;
}

/* `domain` picks which of two same-named cookies wins during the migration described on
   writeThemeCookie: with a domain configured the newer one is the parent's, and equal-path
   cookies arrive oldest first. The boot script applies the same rule. */
export function readThemeCookie(domain = ""): ThemeChoice | null {
  const all = [...document.cookie.matchAll(new RegExp(COOKIE_PATTERN, "g"))];
  const match = domain ? all[all.length - 1] : all[0];
  if (!match) return null;
  const value = decodeURIComponent(match[1]!);
  return isThemeChoice(value) ? value : null;
}

/* The attribute the render-time boot value is carried on. Set on <html> by the layer's
   Nitro plugin so the inline boot script below can read the deployment's cookie domain
   before any bundle has loaded; `dataset.themeCookieDomain` is the same string
   `runtimeConfig.public.themeCookieDomain` holds. */
export const THEME_DOMAIN_ATTR = "data-theme-cookie-domain";

/* `Secure` is added only on https: a Secure cookie set over plain http is dropped
   silently, which on localhost would mean the choice never persists at all.

   `domain` is empty in dev and on a single host, which writes a host-only cookie exactly
   as before. On subdomains it is the parent (".example.com"), because a host-only cookie
   set by pulse.example.com is not sent to identity.example.com and the theme would stop
   following the person from one product to the next.

   Setting it also has to clear the host-only cookie of the same name. Two cookies can
   carry one name — one host-only, one on the parent — and `document.cookie` hands back
   both with no way to tell them apart, oldest first at equal path. Anyone who used the
   site before the domain was configured has the host-only one, so without this the new
   choice would be written and then shadowed by the old value on every read. */
export function writeThemeCookie(choice: ThemeChoice, domain = ""): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  if (domain) {
    document.cookie = `${THEME_KEY}=; path=/; max-age=0; SameSite=Lax${secure}`;
  }
  const scope = domain ? `; Domain=${domain}` : "";
  document.cookie = `${THEME_KEY}=${choice}; path=/${scope}; max-age=${THEME_MAX_AGE}; SameSite=Lax${secure}`;
}

/** The cookie domain this page was rendered with, or "" when none is configured. */
export function themeCookieDomain(): string {
  if (typeof document === "undefined") return "";
  return document.documentElement.getAttribute(THEME_DOMAIN_ATTR) ?? "";
}

/* Inlined into <head> by the layer's nuxt.config and run before first paint. `ssr: false`
   means the app shell is dark from `:root` until JavaScript boots, so without this a
   light user gets a dark flash on every hard load. Kept dependency-free and tiny for the
   same reason — it is a render-blocking script.

   It reads localStorage only when the cookie says nothing, so a choice made before the
   move to cookies still paints correctly on the load that migrates it.

   The last clause of the cookie read is the domain half of the same problem writeThemeCookie
   handles. When a cookie domain is configured, a browser part-way through that migration can
   send two cookies of this name; they arrive oldest first, and the newer one is the one the
   parent domain now owns. So with a domain set the script takes the last match rather than
   the first. With no domain — dev, and any single-host deployment — there is only ever one,
   and taking the first is what it has always done. The value is read off <html>, which the
   parser has already seen by the time this runs, so nothing has to be baked in at build.

   Reading either store throws outright in some private-browsing configurations, so the
   whole thing is wrapped and falls back to dark, which is what `:root` already says. */
export const THEME_BOOT_SCRIPT = [
  "(function(){try{",
  `var e=document.documentElement,d=e.getAttribute(${JSON.stringify(THEME_DOMAIN_ATTR)})||"";`,
  `var a=String(document.cookie||"").match(new RegExp(${JSON.stringify(COOKIE_PATTERN)},"g"))||[];`,
  'var m=a.length?a[d?a.length-1:0].split("=").slice(1).join("="):"";',
  'var c=m?decodeURIComponent(m):"";',
  `if(c!=="light"&&c!=="dark"&&c!=="system"){try{c=localStorage.getItem(${JSON.stringify(THEME_KEY)})||"";}catch(e2){}}`,
  'if(c!=="light"&&c!=="dark")c=(!window.matchMedia||window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";',
  "e.dataset.theme=c;",
  '}catch(e3){document.documentElement.dataset.theme="dark";}})();',
].join("");
