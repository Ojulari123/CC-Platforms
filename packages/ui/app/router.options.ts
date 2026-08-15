import type { RouterScrollBehavior } from "vue-router";

/* Scroll handling for every product on this layer, and the one place the sign-in fragment
   is kept out of the console.

   Vue Router hands whatever is in `to.hash` to document.querySelector as a CSS selector.
   The cross-product handoff lands on /auth/callback with the access token in the fragment
   (composables/useSSO.ts), and "#access_token=eyJ…" is not a valid selector, so the dev
   build of vue-router catches the parse error and warns — with the whole JWT and the state
   value inlined — before the callback page has had a chance to erase the hash. The token
   goes in the fragment precisely because a fragment never reaches a server; a console line
   throws that away, and console text is copied into tickets and screen recordings.

   So a hash is only ever treated as a scroll target when it is shaped like a plain element
   id. Everything else is dropped in silence: not logged, not echoed, not stored.

   Nuxt 3 reads <srcDir>/app/router.options.ts from every layer and merges them with the
   app's own file last, so this sits under identity, pulse and forge without any of them
   opting in, and any of them could still override it. */

// Deliberately narrower than what an id may legally contain. An id can hold "=", "&", "."
// and "/" — which is why vue-router asks for escaped selectors in the first place — but
// those are exactly the characters a token fragment is made of. Every anchor the platform
// actually uses is a plain CSS identifier, so refusing the rest costs nothing and leaves
// no shape a credential could be squeezed through.
const ELEMENT_ID = /^[A-Za-z_][A-Za-z0-9_-]*$/;
const MAX_ID_LENGTH = 128;

export function isElementIdHash(hash: string): boolean {
  if (!hash.startsWith("#")) return false;
  const id = hash.slice(1);
  return id.length > 0 && id.length <= MAX_ID_LENGTH && ELEMENT_ID.test(id);
}

/* getElementById, never querySelector: it takes an id rather than a selector, so it has
   nothing to parse and nothing to throw, and no error message can carry the string. */
function scrollMarginTop(id: string): number {
  if (typeof document === "undefined") return 0;
  const el = document.getElementById(id);
  if (!el) return 0;
  const own = Number.parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
  const root = Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  return own + root;
}

function anchor(hash: string) {
  // No `behavior`, so the hash lands at the browser's own setting. Smooth scrolling here
  // would be motion the reduced-motion block in assets/css/motion.css cannot reach — that
  // reset can only turn off animations and transitions, not a scroll this file asked for.
  return { el: hash, top: scrollMarginTop(hash.slice(1)) };
}

export const scrollBehavior: RouterScrollBehavior = (to, from, savedPosition) => {
  // Back and forward put the page back where the person left it, hash or no hash.
  if (savedPosition) return savedPosition;

  const hash = typeof to.hash === "string" ? to.hash : "";
  const target = isElementIdHash(hash) ? hash : "";

  // Same page, only the query or the fragment moved: a filter or a tab must not throw the
  // view back to the top. Trailing slashes are stripped so /reports and /reports/ match.
  if (to.path.replace(/\/$/, "") === from.path.replace(/\/$/, "")) {
    if (target) return anchor(target);
    if (from.hash && !hash) return { left: 0, top: 0 };
    return false;
  }

  // Nuxt's `definePageMeta({ scrollToTop: false })`, kept working because dropping it
  // would be a silent behaviour change for any page that reaches for it later.
  const meta = to.meta.scrollToTop;
  const scrollToTop = typeof meta === "function" ? (meta as (a: typeof to, b: typeof from) => unknown)(to, from) : meta;
  if (scrollToTop === false) return false;

  if (target) return anchor(target);
  return { left: 0, top: 0 };
};

export default { scrollBehavior };
