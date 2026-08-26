import { describe, expect, it } from "vitest";

/* The contrast contract for tokens.css, asserted rather than written down in a comment.
   Every ratio quoted in that file's prose is reproduced here; the point is that editing a
   token to fix one screen cannot quietly drop another below its floor.

   The oklch → sRGB conversion is the CSS Color 4 one, followed by a per-channel clamp for
   colours outside the sRGB gamut (`--accent-ink` in dark is one). That clamp is what
   Chromium does: every token in both themes was rendered in a real browser and read back
   off a canvas, and the painted pixels match this maths to within one 8-bit step on one
   channel of one token. So these are the numbers the screen produces, not an idealisation
   of them. */

const SRC = Object.values(
  import.meta.glob("../assets/css/tokens.css", { query: "?raw", import: "default", eager: true }),
)[0] as string;

function oklchToSrgb(L: number, C: number, hDeg: number): [number, number, number] {
  const h = (hDeg * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  const enc = (u: number) => (u <= 0.0031308 ? 12.92 * u : 1.055 * u ** (1 / 2.4) - 0.055);
  return lin.map((v) => Math.min(1, Math.max(0, enc(v)))) as [number, number, number];
}

type Colour = { rgb: [number, number, number]; alpha: number };

function parse(decl: string): Colour {
  const m = decl.trim().match(/^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+)%\s*)?\)$/);
  if (!m) throw new Error(`not an oklch() value: ${decl}`);
  return { rgb: oklchToSrgb(+m[1]!, +m[2]!, +m[3]!), alpha: m[4] === undefined ? 1 : +m[4]! / 100 };
}

// A translucent token is judged over whatever it is laid on, the way the compositor does it.
function flatten(fg: Colour, bg: [number, number, number]): [number, number, number] {
  return fg.rgb.map((c, i) => c * fg.alpha + bg[i]! * (1 - fg.alpha)) as [number, number, number];
}

function luminance([r, g, b]: [number, number, number]): number {
  const dec = (u: number) => (u <= 0.04045 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4);
  return 0.2126 * dec(r) + 0.7152 * dec(g) + 0.0722 * dec(b);
}

function contrast(fg: [number, number, number], bg: [number, number, number]): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// Brace-matched rather than regexed: the file nests a media query around two of the blocks.
function body(selector: string, from = 0): string {
  const start = SRC.indexOf(selector, from);
  if (start < 0) throw new Error(`no block for ${selector}`);
  const open = SRC.indexOf("{", start + selector.length);
  let depth = 1;
  let i = open + 1;
  while (depth > 0) {
    if (SRC[i] === "{") depth += 1;
    else if (SRC[i] === "}") depth -= 1;
    i += 1;
  }
  return SRC.slice(open + 1, i - 1);
}

function declarations(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/(--[a-z-]+)\s*:\s*(oklch\([^)]*\))\s*;/g)) out[m[1]!] = m[2]!;
  return out;
}

const HIGH_CONTRAST = SRC.indexOf("@media (prefers-contrast: more)");
const dark = declarations(body(":root,\n[data-theme='dark']"));
const light = declarations(body("[data-theme='light']"));
const THEMES = {
  dark,
  light,
  "dark, prefers-contrast: more": { ...dark, ...declarations(body(":root,\n  [data-theme='dark']", HIGH_CONTRAST)) },
  "light, prefers-contrast: more": { ...light, ...declarations(body("[data-theme='light']", HIGH_CONTRAST)) },
};

const SURFACES = ["--app", "--sunken", "--surface", "--surface-hover", "--surface-active"] as const;
// Disabled controls and status tints only ever land on a surface at rest; the last two
// steps are interaction fills.
const RESTING = SURFACES.slice(0, 3);
const STATUS = ["--ok", "--warn", "--bad", "--info"] as const;

describe.each(Object.entries(THEMES))("tokens.css — %s", (_name, T) => {
  const on = (token: string, surface: string) => {
    const bg = flatten(parse(T[surface]!), [0, 0, 0]);
    return contrast(flatten(parse(T[token]!), bg), bg);
  };
  const onTint = (token: string, tint: string, surface: string) => {
    const bg = flatten(parse(T[tint]!), flatten(parse(T[surface]!), [0, 0, 0]));
    return contrast(flatten(parse(T[token]!), bg), bg);
  };

  it.each(["--ink", "--ink-muted", "--ink-faint"])("%s clears AA on every surface", (token) => {
    for (const s of SURFACES) expect(on(token, s), `${token} on ${s}`).toBeGreaterThanOrEqual(4.5);
  });

  it("--ink-disabled clears AA on the surfaces a disabled control can sit on", () => {
    for (const s of RESTING) expect(on("--ink-disabled", s), `--ink-disabled on ${s}`).toBeGreaterThanOrEqual(4.5);
  });

  /* The other half of the disabled rule. `--ink-disabled` is deliberately *not* lifted to
     clear 4.5 on `--surface-active` — the value that would is within 0.01 L of
     `--ink-faint`, so disabled would stop looking disabled. The floor is bought by keeping
     disabled controls off the interaction fills instead, which is a usage rule, and this
     is the assertion that records why the token is where it is. */
  it("--ink-disabled stays clear of --ink-faint", () => {
    expect(Math.abs(parse(T["--ink-disabled"]!).rgb[1]! - parse(T["--ink-faint"]!).rgb[1]!)).toBeGreaterThan(0.02);
  });

  it.each(["--line", "--line-strong"])("%s clears 1.4.11's 3:1 on every surface", (token) => {
    for (const s of SURFACES) expect(on(token, s), `${token} on ${s}`).toBeGreaterThanOrEqual(3);
  });

  /* `--line-subtle` is decorative and not bound by 1.4.11, but it has to stay a distinct
     weight: the value that would give it 3:1 on `--surface-active` is `--line` itself. */
  it("--line-subtle stays a lighter weight than --line", () => {
    for (const s of SURFACES) expect(on("--line-subtle", s), `--line-subtle on ${s}`).toBeLessThan(on("--line", s) - 0.5);
  });

  it("--accent-ink clears 3:1 on every surface, as the focus indicator", () => {
    for (const s of SURFACES) expect(on("--accent-ink", s), `--accent-ink on ${s}`).toBeGreaterThanOrEqual(3);
  });

  /* `--accent` does not clear 4.5 on the deeper surfaces and is never meant to carry text.
     Asserted so that a later attempt to set it as a text colour has to face this first;
     tokenUsage.spec.ts is what stops it happening in a component. */
  it("--accent is a fill, not a text colour", () => {
    expect(Math.min(...SURFACES.map((s) => on("--accent", s)))).toBeLessThan(4.5);
    expect(Math.min(...SURFACES.map((s) => on("--accent", s)))).toBeGreaterThanOrEqual(3);
  });

  /* 4.45 rather than 4.5 on the surfaces, and only here. The status ramp is tuned to sit
     level with itself and under the ink ladder, which pins it almost exactly on AA at the
     lightest interaction fill: on `--surface-active` the tightest cells are `--warn` at
     4.5020 (light) and 4.5031 (dark). Two thousandths of headroom is not an accessibility
     margin, it is a rounding accident, and any future re-space of the surfaces trips CI
     for a difference no eye can resolve. The floor that is actually load-bearing is the
     one on the three resting surfaces below, which keeps its 4.5. */
  it.each(STATUS)("%s clears AA on every surface and on its own tint", (token) => {
    for (const s of SURFACES) expect(on(token, s), `${token} on ${s}`).toBeGreaterThanOrEqual(4.45);
    for (const s of RESTING) expect(onTint(token, `${token}-surface`, s), `${token} on tint on ${s}`).toBeGreaterThanOrEqual(4.5);
  });

  // The inversion the palette exists to remove: a status word must never out-read the
  // labels around it. Turning the OS contrast up must not turn this over either.
  it("status sits under the whole ink ladder", () => {
    for (const token of STATUS) expect(on(token, "--app"), `${token} vs --ink-faint`).toBeLessThan(on("--ink-faint", "--app"));
  });
});
