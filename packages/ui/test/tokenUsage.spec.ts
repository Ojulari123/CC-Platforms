import { existsSync, readdirSync, readFileSync, type Dirent } from "node:fs";
import { dirname, join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/* The other half of the contrast contract. tokens.spec.ts proves the palette is sound;
   this proves the products spend it correctly, by reading their source. It is a lint that
   happens to be a test, and it lives here rather than in each app because the rule it
   enforces belongs to the layer that defines the tokens.

   The rule: a token that does not clear 4.5:1 on the surfaces it can land on must never be
   set as a text colour. `--accent` is the one this exists for — it measures 3.08:1 on
   `--surface-active`, and the moment someone reaches for it as a link colour the platform
   quietly fails AA on every screen that uses it. `--accent-ink` is the colour they want. */

/* Read as plain text off disk rather than through `import.meta.glob`. A `?raw` glob still
   sends every matched `.ts` file through vite:esbuild, which loads the nearest tsconfig for
   it, and Forge's extends `./.nuxt/tsconfig.json`, a file Nuxt generates. A clean checkout
   has never run Nuxt, so the glob crashed on CI while passing on a machine that had built
   Forge. Nothing here needs the bundler; it needs the bytes. */
function repoRoot(): string {
  let dir = process.cwd(); // vitest sets this to the project root, packages/ui
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, "packages")) && existsSync(join(dir, "services"))) return dir;
    dir = dirname(dir);
  }
  throw new Error(`could not find the repo root above ${process.cwd()}`);
}

const ROOT = repoRoot();

const SKIP = new Set(["node_modules", ".nuxt", ".output", "dist", ".git"]);

function walk(dir: string, extensions: string[], found: Record<string, string>): void {
  let entries: Dirent[];
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return; // a directory one product has and another does not
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP.has(entry.name)) walk(full, extensions, found);
    } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
      found[relative(ROOT, full)] = readFileSync(full, "utf8");
    }
  }
}

const SOURCES: Record<string, string> = {};
for (const [dir, extensions] of [
  ["packages/ui/components", [".vue"]],
  ["packages/ui/composables", [".ts"]],
  ["packages/ui/utils", [".ts"]],
  ["packages/ui/types", [".ts"]],
  ["services/forge/frontend", [".vue", ".ts"]],
  ["services/identity/frontend", [".vue", ".ts"]],
  ["services/pulse/frontend", [".vue", ".ts"]],
] as const) {
  walk(join(ROOT, dir), [...extensions], SOURCES);
}

// Every colour token tailwind.config.js exposes, longest first so `accent-ink` is matched
// before `accent` would swallow it.
const TOKENS = [
  "surface-hover", "surface-active", "line-subtle", "line-strong", "ink-muted", "ink-faint", "ink-disabled",
  "accent-hover", "accent-surface", "accent-ink", "ok-surface", "warn-surface", "bad-surface", "info-surface",
  "surface", "sunken", "line", "ink", "accent", "app", "ok", "warn", "bad", "info",
];

/* Cleared for text. `--app` is on the list because it is the inverse: near-black type on
   the `--ink` fill of a primary button, which measures 17.41:1. The status four clear 4.5
   on all five surfaces and on their own tints. */
const TEXT_SAFE = new Set(["ink", "ink-muted", "ink-faint", "ink-disabled", "accent-ink", "app", "ok", "warn", "bad", "info"]);

const TEXT_CLASS = new RegExp(String.raw`(?<![\w-])(?:[a-z-]+:)*text-(${TOKENS.join("|")})(?![\w-])(/\d+)?`, "g");

// `text-*` on an <svg> sets currentColor for a stroke, not type — Cross.vue draws its
// crosshair that way. A decorative mark is 1.4.11's 3:1 at most, not 1.4.3's 4.5:1.
function isSvgTag(source: string, index: number): boolean {
  const open = source.lastIndexOf("<", index);
  if (open < 0 || index - open > 400) return false;
  const close = source.indexOf(">", open);
  if (close >= 0 && close < index) return false;
  return /^<svg[\s>]/.test(source.slice(open, open + 5));
}

type Hit = { file: string; token: string; modifier: string | undefined; snippet: string };

function textColourUses(): Hit[] {
  const hits: Hit[] = [];
  for (const [file, source] of Object.entries(SOURCES)) {
    for (const m of source.matchAll(TEXT_CLASS)) {
      if (isSvgTag(source, m.index!)) continue;
      hits.push({ file, token: m[1]!, modifier: m[2], snippet: source.slice(Math.max(0, m.index! - 40), m.index! + 40).replace(/\s+/g, " ") });
    }
  }
  return hits;
}

describe("token usage across the layer and all three products", () => {
  it("reads every product's source, not just this layer's", () => {
    const products = new Set(Object.keys(SOURCES).map((f) => f.match(/services\/([^/]+)\//)?.[1]).filter(Boolean));
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect([...products].sort()).toEqual(["forge", "identity", "pulse"]);
  });

  it("never sets a sub-4.5:1 token as a text colour", () => {
    const bad = textColourUses().filter((h) => !TEXT_SAFE.has(h.token));
    expect(bad.map((h) => `${h.file}: text-${h.token} — ${h.snippet}`)).toEqual([]);
  });

  /* An opacity modifier on a text colour is the same failure wearing a different hat:
     `text-ink-muted/50` is not `--ink-muted`, and nothing in tokens.css measures it. */
  it("never fades a text colour with an opacity modifier", () => {
    const faded = textColourUses().filter((h) => h.modifier);
    expect(faded.map((h) => `${h.file}: text-${h.token}${h.modifier}`)).toEqual([]);
  });

  /* The type floor, guarded the same way the colour rules are. 11px was removed across the
     platform in an earlier pass; 11.5px survived it in sixteen places, four of them buttons,
     which is the same rule broken by half a pixel. Anything a person has to read and act on
     is above the floor, not on it. */
  it("sets no type below the 12px floor", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(SOURCES)) {
      for (const m of source.matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)) {
        if (Number.parseFloat(m[1]!) < 12) offenders.push(`${file}: text-[${m[1]}px]`);
      }
    }
    expect(offenders).toEqual([]);
  });

  // All colour goes through the custom properties, so the theme is one attribute on <html>.
  // A `dark:` variant would be a second, private theme switch that data-theme cannot drive.
  it("has no `dark:` Tailwind variants", () => {
    const offenders = Object.entries(SOURCES)
      .filter(([, source]) => /(?<![\w-])dark:/.test(source))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });
});
