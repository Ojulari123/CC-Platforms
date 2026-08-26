// `useRuntimeConfig` comes from "#imports" because this file is compiled twice: by Nitro,
// where "#imports" is Nitro's own auto-import map, and by `nuxt typecheck` in each app,
// where it is the app's. Both export this name. `defineNitroPlugin` exists only in the
// first, so it is not used — it is an identity function, and a plain default export is
// the same plugin.
import { useRuntimeConfig } from "#imports";

interface RenderContext {
  htmlAttrs: string[];
}

interface NitroApp {
  hooks: { hook: (name: "render:html", fn: (html: RenderContext) => void) => void };
}

/* Puts the configured cookie domain on <html> at render time.

   The theme boot script has to run before the first paint, which means before any bundle
   has loaded and before `window.__NUXT__.config` is written, so it cannot call
   useRuntimeConfig() itself. Baking the value in at build time does not work either: the
   three web images are built once and configured per environment, and NUXT_PUBLIC_* only
   exists when the container runs.

   So the value is carried on an attribute of the element the parser reads first. This
   hook runs on every render, `htmlAttrs` lands on the opening <html> tag ahead of <head>,
   and the boot script reads it back with getAttribute. Nothing is emitted when no domain
   is configured, which is the dev and single-host case. */
export default (nitroApp: NitroApp) => {
  const domain = useRuntimeConfig().public.themeCookieDomain;
  if (typeof domain !== "string" || !domain) return;
  const escaped = domain.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  nitroApp.hooks.hook("render:html", (html) => {
    html.htmlAttrs.push(`data-theme-cookie-domain="${escaped}"`);
  });
};
