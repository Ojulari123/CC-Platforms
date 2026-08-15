import type { TokenPair } from "../types/api";

/* Cross-product sign-in, as a redirect handoff through identity.

   The three apps run on three origins (3000/3001/3002) and hold their tokens under three
   `authStoragePrefix` values, so localStorage cannot be shared and "one login, every
   product" does not fall out of storage on its own. This is the hop that makes it work:

     product  →  identity /sso/authorize?return_to=&state=&next=
     identity →  (already signed in) → return_to#access_token=…&state=…
     product  →  stores the token under its own prefix and carries on

   What crosses the origin boundary is ONE short-lived access token, in the URL fragment,
   read and erased before anything else runs. The refresh token never leaves identity —
   see the note on `completeHandoff` for why copying it would be actively harmful. */

export interface SsoTokens {
  accessToken: string;
  expiresIn: number;
}

export interface SsoRequest {
  returnTo: string;
  state: string;
  next: string;
}

export type SsoResult =
  | { ok: true; tokens: SsoTokens; next: string }
  | { ok: false; reason: string };

const STATE_BYTES = 16;

function configError(key: string): Error {
  return new Error(
    `[@crescent/ui] runtimeConfig.public.${key} is not set, so the cross-product sign-in handoff is refused. ` +
      "Set ssoAuthorizeUrl (identity's /sso/authorize) and ssoReturnAllowlist (the origins a token may be handed back to) in this app's nuxt.config.",
  );
}

/** A return URL is only ever one of a small, configured set. Never a URL from the query
    string taken on trust — that is an open redirect, and here it would be an open redirect
    that hands an access token to whoever asked. */
export function isAllowedReturnUrl(candidate: string, allowlist: readonly string[]): boolean {
  if (!candidate || !allowlist.length) return false;

  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    // Relative and protocol-relative ("//evil.example") values are refused rather than
    // resolved: which origin they mean depends on where they are resolved, which is
    // exactly the ambiguity an attacker needs.
    return false;
  }

  if (url.protocol !== "https:" && url.protocol !== "http:") return false;
  // https://identity.internal@evil.example/ parses with host evil.example and reads, to a
  // human, like the identity host.
  if (url.username || url.password) return false;

  return allowlist.some((entry) => {
    let allowed: URL;
    try {
      allowed = new URL(entry);
    } catch {
      return false;
    }
    if (url.origin !== allowed.origin) return false;
    // Path match on a segment boundary, so /auth/callback does not also allow
    // /auth/callback-evil on a co-hosted origin.
    const base = allowed.pathname.replace(/\/+$/, "");
    if (!base) return true;
    return url.pathname === base || url.pathname.startsWith(`${base}/`);
  });
}

/* A `next` names a route to come back to, and nothing else. Everything from a "#" onwards
   is a fragment: a client-side scroll target the browser keeps to itself and re-appends on
   the real navigation anyway, so carrying it through `?next=` buys nothing.

   It costs a great deal. The handoff below returns the access token in the fragment
   precisely because a fragment is never sent to a server. Promote that same string into a
   query string and the token lands in the access log of every request the page makes and in
   the Referer header of every asset it pulls. So a fragment is cut off before a value can
   become a `next`, and refused outright by the predicate — raw "#" or percent-encoded, since
   "%23" is a "#" again after one round of query decoding. */
const FRAGMENT_MARKER = /#|%(?:25)*23/;

// Tab, CR and LF are deleted from a URL by the WHATWG parser rather than escaped, so
// "/\t/evil.example" is read as "//evil.example" — protocol-relative, and off the origin.
const CONTROL_CHARS = /[\u0000-\u001F\u007F]/;

/** The route part of a candidate `next`, with any fragment removed. */
export function stripFragment(next: string): string {
  const at = next.search(FRAGMENT_MARKER);
  return at === -1 ? next : next.slice(0, at);
}

/** Where to continue once the token has landed. In-app path only: an absolute URL here
    would be a second open redirect wearing a different name. */
export function isSafeNextPath(next: string): boolean {
  if (!next.startsWith("/")) return false;
  // "//host" is protocol-relative and "/\host" is treated as protocol-relative by some
  // parsers; both leave the app.
  if (next.startsWith("//") || next.startsWith("/\\")) return false;
  if (CONTROL_CHARS.test(next)) return false;

  // Decoded as well as raw. A value travels through `?next=` and comes back one decode
  // lighter, so what matters is not only what this string says but what it becomes.
  let probe = next;
  for (let round = 0; round < 4; round += 1) {
    if (probe.includes("#")) return false;
    if (probe.startsWith("//") || probe.startsWith("/\\")) return false;
    let decoded: string;
    try {
      decoded = decodeURIComponent(probe);
    } catch {
      // A stray "%" that is not an escape sequence: nothing further to reveal, and the
      // rounds already run were the ones that could have hidden a "#".
      break;
    }
    if (decoded === probe) break;
    probe = decoded;
  }
  return true;
}

export function safeNextPath(next: string | null | undefined, fallback = "/"): string {
  if (typeof next !== "string" || !next) return fallback;
  const route = stripFragment(next);
  return isSafeNextPath(route) ? route : fallback;
}

function randomState(): string {
  const bytes = new Uint8Array(STATE_BYTES);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The allowlist is a comma-separated string in config so it can be overridden by a single
    environment variable at deploy time; an array is accepted too. */
export function parseAllowlist(value: unknown): string[] {
  const raw = typeof value === "string" ? value.split(",") : Array.isArray(value) ? value : [];
  return raw.map((entry) => String(entry).trim()).filter(Boolean);
}

export function useSSO() {
  const config = useRuntimeConfig();
  const prefix = config.public.authStoragePrefix;
  const authorizeUrl = (config.public.ssoAuthorizeUrl ?? "") as string;
  const allowlist = parseAllowlist(config.public.ssoReturnAllowlist);
  const stateKey = `${prefix}.sso_state`;

  /** Called by a product that has no session. Sends the browser to identity, having first
      left a one-use `state` in this origin's sessionStorage. */
  function startHandoff(next = "/"): void {
    if (!authorizeUrl || !allowlist.length) throw configError(!authorizeUrl ? "ssoAuthorizeUrl" : "ssoReturnAllowlist");

    const returnTo = `${window.location.origin}${window.location.pathname}`;
    // Belt and braces: this app's own callback has to be on the list it will later check
    // a handoff against, or the round trip is guaranteed to fail at the far end.
    if (!isAllowedReturnUrl(returnTo, allowlist)) {
      throw new Error(`[@crescent/ui] ${returnTo} is not in ssoReturnAllowlist, so the sign-in handoff would be rejected on return.`);
    }

    const state = randomState();
    sessionStorage.setItem(stateKey, state);

    const url = new URL(authorizeUrl);
    url.searchParams.set("return_to", returnTo);
    url.searchParams.set("state", state);
    url.searchParams.set("next", safeNextPath(next));
    // replace, not assign: the handoff is not a place in history to go back to.
    window.location.replace(url.toString());
  }

  /** Identity's side of the hop: what the authorize screen was asked to do. */
  function readRequest(query: Record<string, unknown>): SsoRequest | null {
    const returnTo = typeof query.return_to === "string" ? query.return_to : "";
    const state = typeof query.state === "string" ? query.state : "";
    if (!isAllowedReturnUrl(returnTo, allowlist)) return null;
    if (!state) return null;
    return { returnTo, state, next: safeNextPath(typeof query.next === "string" ? query.next : "/") };
  }

  /* The token goes in the fragment, not the query string. A fragment is never sent to a
     server, so it stays out of access logs and out of the Referer header; the callback
     erases it from the address bar before anything else runs.

     Only the access token crosses. Copying the refresh token would look tidier and would
     be a real defect: refresh tokens rotate, and identity treats a second use of a rotated
     token as theft — services/identity/app/services/auth.py revokes the whole family and
     bumps token_version, which signs the person out of every device. Two apps holding one
     refresh token would trip that on their own, without an attacker. */
  function completeHandoff(request: SsoRequest, pair: TokenPair): string {
    if (!isAllowedReturnUrl(request.returnTo, allowlist)) {
      throw new Error("[@crescent/ui] refusing to hand a token to a return URL that is not on the allowlist.");
    }
    const fragment = new URLSearchParams({
      access_token: pair.access_token,
      expires_in: String(pair.expires_in),
      state: request.state,
      next: request.next,
    });
    return `${request.returnTo}#${fragment.toString()}`;
  }

  /** The product's side of the return. Reads the fragment, clears it, and checks the
      handoff is one this browser actually asked for. */
  function consumeHandoff(): SsoResult {
    const raw = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
    if (!raw) return { ok: false, reason: "no-handoff" };

    const params = new URLSearchParams(raw);
    // Erased first, before any await, so a token cannot be read back out of the address
    // bar or left behind in the history entry.
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

    const expected = sessionStorage.getItem(stateKey);
    sessionStorage.removeItem(stateKey);

    const error = params.get("error");
    if (error) return { ok: false, reason: error };

    const accessToken = params.get("access_token") ?? "";
    const state = params.get("state") ?? "";
    if (!accessToken) return { ok: false, reason: "no-token" };
    // Without this an attacker can send someone a link that signs them into an account
    // that is not theirs, and everything they then write goes to the attacker's account.
    if (!expected || state !== expected) return { ok: false, reason: "state-mismatch" };

    const expiresIn = Number(params.get("expires_in") ?? 0);
    return {
      ok: true,
      tokens: { accessToken, expiresIn: Number.isFinite(expiresIn) ? expiresIn : 0 },
      next: safeNextPath(params.get("next")),
    };
  }

  const configured = computed(() => Boolean(authorizeUrl && allowlist.length));

  return { authorizeUrl, allowlist, configured, startHandoff, readRequest, completeHandoff, consumeHandoff };
}
