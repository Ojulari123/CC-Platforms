<script setup lang="ts">
import type { CSSProperties } from "vue";
import { FOCUS, MONO_LABEL, ORIGIN, TAP } from "@crescent/ui/utils/ui";
import type { NavItem, TabItem } from "@crescent/ui/types/ui";
import { TRUST } from "~/utils/site";

/* The umbrella front door. Two products, one login. Identity is not in the product grid
   because it is not a product you visit — it sits in the middle of the diagram, holding
   the other two together. Every call to action leads to the sign-in screen. */

definePageMeta({
  layout: false,
  middleware: [
    () => {
      // Signed in, the front page is the least useful screen on the site: the picker is.
      if (import.meta.server) return;
      const auth = useAuth();
      auth.hydrate();
      if (auth.isAuthenticated.value) return navigateTo("/products", { replace: true });
    },
  ],
});

const config = useRuntimeConfig();

const active = ref<"pulse" | "forge">("pulse");
const cursor = ref<number | null>(null);
const hero = ref<HTMLElement | null>(null);

const { el: productsEl, shown: productsIn } = useReveal();
const { el: loginEl, shown: loginIn } = useReveal();
const { el: ctaEl, shown: ctaIn } = useReveal();
const { el: footEl, shown: footIn } = useReveal();

const navItems: NavItem[] = [
  { label: "Pulse", to: config.public.pulseUrl as string },
  { label: "Forge", to: config.public.forgeUrl as string },
];

const tabs: TabItem[] = [
  { id: "pulse", label: "Pulse" },
  { id: "forge", label: "Forge" },
];

const PRODUCTS = [
  {
    key: "pulse" as const,
    name: "Pulse",
    tag: "Engineering reporting",
    icon: "pulse" as const,
    file: "pulse/week-32.report.md",
    meta: "wk 32 · draft",
    line: "Turns GitHub activity into weekly reports, drafts them with AI, and routes them for approval.",
    points: ["Syncs commits, PRs, reviews and issues", "AI drafts you edit and own", "Lead + deputy approval, on the record"],
  },
  {
    key: "forge" as const,
    name: "Forge",
    tag: "No-code ML",
    icon: "layers" as const,
    file: "forge/revenue.csv",
    meta: "3 cols · 4 rows",
    line: "Upload a dataset, build a workflow, and see the steps instead of hiding them behind a Run button.",
    points: ["CSV upload with instant preview", "Guided classification and forecasting", "Canvas that maps to real Python"],
  },
];

// Illustrative, and labelled as a preview rather than as live data: nothing on this page
// is signed in, so there is nothing real to read.
const PULSE_STATS: [string, string][] = [["commits", "128"], ["pull requests", "31"], ["reviews", "44"]];
const PULSE_SECTIONS: [string, string][] = [
  ["manager", "Token rotation shipped; sync backlog cleared."],
  ["exec", "On track. Review latency is the one risk."],
  ["next week", "Finish key rollout, start CSV upload in Forge."],
];
const REVENUE_ROWS: string[][] = [
  ["West", "Q1", "182,400"],
  ["West", "Q2", "196,010"],
  ["East", "Q1", "141,880"],
  ["East", "Q2", "158,220"],
];

// A single hairline that follows the pointer across the hero, the way a chart cursor
// does. Percentage, so it survives any container width.
function onMove(event: MouseEvent) {
  const rect = hero.value?.getBoundingClientRect();
  if (!rect) return;
  cursor.value = ((event.clientX - rect.left) / rect.width) * 100;
}

const readout = computed(() =>
  cursor.value === null ? ORIGIN : `${(cursor.value * 1.8).toFixed(2).padStart(6, "0")}°  E`,
);

/* Scroll entrance for everything below the hero. Without it three screens of this page
   have finished animating before they are ever on screen. 8px and opacity only — this is
   an editorial page, not a deck. */
function reveal(shown: boolean, delay = 0): CSSProperties {
  const ease = "cubic-bezier(0.23,1,0.32,1)";
  return {
    opacity: shown ? "1" : "0",
    transform: shown ? "none" : "translateY(8px)",
    transition: `opacity 420ms ${ease} ${delay}ms, transform 420ms ${ease} ${delay}ms`,
  };
}

useHead({ title: "One login. Every tool your engineers open." });
</script>

<template>
  <div class="w-full overflow-x-hidden">
    <TopBar :signed-in="false" home-to="/" :nav-items="navItems" sign-in-to="/login" get-started-to="/login?mode=signup" />
    <RulerStrip :readout="readout" />

    <main id="main">
      <!-- ── hero: asymmetric, hung off a vertical rule ── -->
      <section
        ref="hero"
        class="relative overflow-hidden border-b border-line-subtle"
        @mousemove="onMove"
        @mouseleave="cursor = null"
      >
        <div
          v-if="cursor !== null"
          class="pointer-events-none absolute inset-y-0 w-px bg-line-subtle"
          :style="{ left: `${cursor}%` }"
          aria-hidden="true"
        />

        <div class="relative mx-auto w-full max-w-[1200px] px-5 sm:px-8">
          <div class="grid lg:grid-cols-12">
            <div class="relative border-line-subtle py-14 lg:col-span-7 lg:border-l lg:py-20 lg:pl-10 lg:pr-14">
              <RuleTicks />
              <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

              <div class="sec flex items-center gap-3">
                <Eyebrow>Internal platform</Eyebrow>
                <span class="rule-draw h-px w-8 bg-line" style="animation-delay: 160ms" aria-hidden="true" />
                <StatusDot tone="ok">All systems operational</StatusDot>
              </div>

              <h1
                class="sec mt-6 max-w-[15ch] text-[clamp(2.3rem,6vw,4.1rem)] font-semibold leading-[0.96] tracking-[-0.045em] lg:max-w-none"
                style="animation-delay: 40ms"
              >
                One login.<br />
                Every tool your<br />
                <span class="text-ink-muted">engineers open.</span>
              </h1>

              <div class="sec mt-8 flex max-w-[46ch] gap-5" style="animation-delay: 80ms">
                <span class="rule-draw mt-1 h-px w-8 shrink-0 bg-line-strong" style="animation-delay: 240ms" aria-hidden="true" />
                <p class="text-[14.5px] leading-relaxed text-ink-muted">
                  Weekly engineering reports that write themselves, and a no-code workspace for trying ML — on one account
                  and one permission model.
                </p>
              </div>

              <div class="sec mt-9 flex flex-wrap items-center gap-2.5" style="animation-delay: 120ms">
                <NuxtLink
                  to="/login?mode=signup"
                  :class="[FOCUS, TAP, 'group/cta inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2.5 text-[13.5px] font-medium text-app transition-[transform,filter] duration-100 ease-out hover:brightness-90 active:scale-[0.98]']"
                >
                  Get started
                  <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta:translate-x-0.5" />
                </NuxtLink>
                <NuxtLink
                  to="/login"
                  :class="[FOCUS, TAP, 'inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-[13.5px] font-medium text-ink ring-1 ring-inset ring-line-strong transition-[transform,background-color,box-shadow] duration-100 ease-out hover:bg-surface-hover hover:ring-ink-faint active:scale-[0.98]']"
                >
                  Sign in
                </NuxtLink>
              </div>
            </div>

            <!-- product pane column, divided by the second rule -->
            <div class="sec relative border-line-subtle pb-16 lg:col-span-5 lg:border-l lg:py-20 lg:pl-10" style="animation-delay: 160ms">
              <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />

              <Tabs
                id="preview"
                :items="tabs"
                :model-value="active"
                label="Product preview"
                variant="mono"
                has-panel
                @update:model-value="active = $event === 'forge' ? 'forge' : 'pulse'"
              >
                <span :class="[MONO_LABEL, 'text-ink-faint']">Live preview</span>
              </Tabs>

              <TabPanel id="preview" :tab="active">
                <!-- Both panes stay mounted in one grid cell, so the outgoing one actually
                     fades and the container keeps the taller pane's height. -->
                <div class="mt-5 grid">
                  <figure
                    v-for="product in PRODUCTS"
                    :key="product.key"
                    :aria-hidden="product.key !== active"
                    class="bg-sunken ring-1 ring-line-subtle transition-[opacity,transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]"
                    :style="{
                      gridArea: '1 / 1',
                      opacity: product.key === active ? '1' : '0',
                      transform: product.key === active ? 'none' : 'translateY(4px)',
                      pointerEvents: product.key === active ? undefined : 'none',
                    }"
                  >
                    <figcaption class="flex items-center justify-between border-b border-line-subtle px-3.5 py-2">
                      <span class="mono text-[11px] text-ink-muted">{{ product.file }}</span>
                      <span class="mono text-[11px] text-ink-faint">{{ product.meta }}</span>
                    </figcaption>

                    <div class="p-3.5">
                      <div v-if="product.key === 'pulse'" class="space-y-4">
                        <div class="grid grid-cols-3 gap-px bg-line-subtle">
                          <div v-for="[k, v] in PULSE_STATS" :key="k" class="bg-app px-3 py-2.5">
                            <p :class="[MONO_LABEL, 'text-ink-faint']">{{ k }}</p>
                            <p class="mono mt-1 text-[15px] font-medium text-ink">{{ v }}</p>
                          </div>
                        </div>
                        <div class="border-t border-line-subtle">
                          <div
                            v-for="[k, v] in PULSE_SECTIONS"
                            :key="k"
                            class="flex items-baseline gap-2.5 border-b border-line-subtle py-[5px] last:border-b-0"
                          >
                            <span :class="[MONO_LABEL, 'w-[62px] shrink-0 text-ink-faint']">{{ k }}</span>
                            <span class="truncate text-[11px] leading-snug text-ink-muted">{{ v }}</span>
                          </div>
                        </div>
                        <div class="flex items-center justify-between border-t border-line-subtle pt-3">
                          <span class="mono text-[11px] text-ink-faint">approval</span>
                          <StatusDot tone="warn">Awaiting lead review</StatusDot>
                        </div>
                      </div>

                      <div v-else class="space-y-3">
                        <div class="grid grid-cols-3 gap-px bg-line-subtle">
                          <div v-for="head in ['region', 'quarter', 'revenue']" :key="head" :class="[MONO_LABEL, 'bg-sunken px-2.5 py-1.5 text-ink-faint']">
                            {{ head }}
                          </div>
                          <template v-for="row in REVENUE_ROWS" :key="row.join('-')">
                            <div
                              v-for="(cell, i) in row"
                              :key="`${row[0]}-${i}`"
                              :class="['bg-app px-2.5 py-1.5 text-[11px] text-ink-muted', i === 2 ? 'mono text-right text-ink' : '']"
                            >
                              {{ cell }}
                            </div>
                          </template>
                        </div>
                        <div class="flex items-center justify-between border-t border-line-subtle pt-2.5">
                          <span class="mono text-[11px] text-ink-faint">step 1 / 4 · schema inferred</span>
                          <span class="inline-flex items-center gap-1.5 text-[11px] text-ok">
                            <Icon name="check" class="h-3 w-3" />
                            Preview ready
                          </span>
                        </div>
                      </div>
                    </div>
                  </figure>
                </div>

                <p class="mt-3 text-[12px] leading-relaxed text-ink-muted">
                  {{
                    active === "pulse"
                      ? "Drafted from the week’s activity, edited by the author, approved on the record."
                      : "Every step stays visible — no hidden Run button doing the work for you."
                  }}
                </p>
              </TabPanel>
            </div>
          </div>

          <!-- the guarantees, subdivided along the same rules -->
          <ul class="grid grid-cols-2 border-t border-line-subtle lg:grid-cols-4">
            <li
              v-for="([n, t], i) in TRUST"
              :key="n"
              class="sec flex items-baseline gap-2.5 border-line-subtle py-4 lg:border-l lg:pl-6"
              :style="{ animationDelay: `${200 + i * 40}ms` }"
            >
              <span class="mono text-[11px] text-ink-faint">{{ n }}</span>
              <span :class="[MONO_LABEL, 'text-ink-muted']">{{ t }}</span>
            </li>
          </ul>
        </div>
      </section>

      <!-- ── products ── -->
      <section ref="productsEl" class="mx-auto w-full max-w-[1200px] px-5 py-16 sm:px-8">
        <div class="flex flex-wrap items-end justify-between gap-4 border-b border-line-subtle pb-5" :style="reveal(productsIn)">
          <div>
            <Eyebrow>Two products</Eyebrow>
            <h2 class="mt-2.5 text-[26px] font-semibold tracking-[-0.025em]">Different jobs. Same account.</h2>
          </div>
          <span :class="[MONO_LABEL, 'text-ink-faint']">02 of 02 shipped</span>
        </div>

        <div class="grid md:grid-cols-2">
          <article
            v-for="(product, idx) in PRODUCTS"
            :key="product.key"
            :style="reveal(productsIn, 60 + idx * 60)"
            :class="[
              'group/card relative border-b border-line-subtle py-7 transition-colors hover:bg-surface-hover/25 md:pr-10',
              idx === 1 ? 'md:border-l md:pl-10 md:pr-0' : '',
            ]"
          >
            <Cross class="absolute -bottom-[5px] -right-[5px] hidden md:block" />
            <div class="flex items-start justify-between gap-4">
              <div class="flex items-center gap-3">
                <span class="grid h-9 w-9 place-items-center rounded-md bg-sunken text-ink-muted ring-1 ring-inset ring-line-subtle transition-colors group-hover/card:text-ink">
                  <Icon :name="product.icon" class="h-4 w-4" />
                </span>
                <div>
                  <h3 class="text-[16px] font-semibold tracking-tight">{{ product.name }}</h3>
                  <p :class="[MONO_LABEL, 'text-ink-faint']">{{ product.tag }}</p>
                </div>
              </div>
              <span class="mono text-[11px] text-ink-faint">0{{ idx + 1 }}</span>
            </div>

            <p class="mt-5 max-w-[46ch] text-[13.5px] leading-relaxed text-ink-muted">{{ product.line }}</p>

            <ul class="mt-5 space-y-2">
              <li v-for="point in product.points" :key="point" class="flex items-start gap-2.5 text-[12.5px] text-ink-muted">
                <span class="mt-[7px] h-px w-2.5 shrink-0 bg-line-strong" aria-hidden="true" />
                {{ point }}
              </li>
            </ul>

            <NuxtLink
              to="/login"
              :class="[FOCUS, TAP, 'group/l mt-6 inline-flex items-center gap-1.5 rounded text-[12.5px] font-medium text-ink transition-colors hover:text-ink-muted']"
            >
              Explore {{ product.name }}
              <Icon name="arrow" class="h-3.5 w-3.5 transition-transform group-hover/l:translate-x-0.5" />
            </NuxtLink>
          </article>
        </div>
      </section>

      <!-- ── one login ── -->
      <section ref="loginEl" class="border-y border-line-subtle bg-sunken/50">
        <div class="mx-auto grid w-full max-w-[1200px] gap-12 px-5 py-16 sm:px-8 lg:grid-cols-12 lg:gap-0">
          <div class="lg:col-span-6 lg:pr-14" :style="reveal(loginIn)">
            <Eyebrow>Underneath</Eyebrow>
            <h2 class="mt-2.5 max-w-[26ch] text-[26px] font-semibold leading-tight tracking-[-0.025em]">
              One identity service, and nothing stores your users twice
            </h2>
            <p class="mt-5 max-w-lg text-[13.5px] leading-relaxed text-ink-muted">
              Every product verifies the same signed token against a published public key. The signing key never leaves
              identity, no product keeps its own copy of a person, and revoking a session cuts it off everywhere within a
              minute.
            </p>
            <ul class="mt-6 border-t border-line-subtle">
              <li
                v-for="claim in [
                  'Short-lived access tokens, rotatable refresh tokens',
                  'Products reference people by id, never by a copied record',
                  'Departments, roles and memberships in exactly one place',
                ]"
                :key="claim"
                class="flex items-start gap-3 border-b border-line-subtle py-3 text-[13px] text-ink-muted"
              >
                <span class="mt-0.5 shrink-0 text-ink-faint"><Icon name="shield" class="h-3.5 w-3.5" /></span>
                {{ claim }}
              </li>
            </ul>
          </div>

          <!-- the diagram: identity in the middle, products hanging off it -->
          <div class="relative border-line-subtle lg:col-span-6 lg:border-l lg:pl-14" :style="reveal(loginIn, 60)">
            <Cross class="absolute -left-[5px] -top-[5px] hidden lg:block" />
            <Eyebrow>Token path</Eyebrow>
            <svg
              viewBox="0 0 320 200"
              class="mt-5 w-full"
              role="img"
              aria-label="Identity sits between Pulse and Forge, issuing one token to both"
            >
              <path class="flow" d="M160 100 C 160 50, 90 50, 70 50" fill="none" stroke="var(--line-strong)" stroke-width="1" stroke-dasharray="4 4" />
              <path class="flow" d="M160 100 C 160 150, 90 150, 70 150" fill="none" stroke="var(--line-strong)" stroke-width="1" stroke-dasharray="4 4" />
              <path d="M202 100 h30" fill="none" stroke="var(--line-subtle)" stroke-width="1" stroke-dasharray="3 3" />

              <rect x="118" y="80" width="84" height="40" rx="4" fill="var(--surface-active)" stroke="var(--line-strong)" />
              <text x="160" y="97" text-anchor="middle" fill="var(--ink)" font-size="10" font-family="Inter" font-weight="600">Identity</text>
              <text x="160" y="110" text-anchor="middle" fill="var(--ink-faint)" font-size="7" font-family="JetBrains Mono">issues tokens</text>

              <rect x="14" y="34" width="70" height="32" rx="4" fill="var(--app)" stroke="var(--line)" />
              <text x="49" y="54" text-anchor="middle" fill="var(--ink-muted)" font-size="9.5" font-family="Inter" font-weight="500">Pulse</text>

              <rect x="14" y="134" width="70" height="32" rx="4" fill="var(--app)" stroke="var(--line)" />
              <text x="49" y="154" text-anchor="middle" fill="var(--ink-muted)" font-size="9.5" font-family="Inter" font-weight="500">Forge</text>

              <g opacity="0.8">
                <rect x="232" y="84" width="74" height="32" rx="4" fill="none" stroke="var(--line-subtle)" stroke-dasharray="3 3" />
                <text x="269" y="104" text-anchor="middle" fill="var(--ink-faint)" font-size="8.5" font-family="Inter">next product</text>
              </g>

              <path d="M160 4v12M160 184v12" stroke="var(--line-subtle)" stroke-width="1" />
            </svg>

            <p class="mt-3 border-t border-line-subtle pt-3 text-[12px] text-ink-muted">
              Adding a product means trusting the same key — not migrating any users.
            </p>
          </div>
        </div>
      </section>

      <!-- ── final CTA ── -->
      <section ref="ctaEl" class="mx-auto w-full max-w-[1200px] px-5 py-20 sm:px-8">
        <div class="flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <div :style="reveal(ctaIn)">
            <Eyebrow>{{ ORIGIN }}</Eyebrow>
            <h2 class="mt-3 max-w-[22ch] text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-[1.02] tracking-[-0.035em]">
              Start with one account
            </h2>
            <p class="mt-4 max-w-md text-[13.5px] leading-relaxed text-ink-muted">
              Sign in and you land in whichever product you have access to. No second setup.
            </p>
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-2.5" :style="reveal(ctaIn, 60)">
            <NuxtLink
              to="/login?mode=signup"
              :class="[FOCUS, TAP, 'group/cta2 inline-flex items-center gap-2 rounded-md bg-ink px-5 py-3 text-[14px] font-medium text-app transition-[transform,filter] duration-100 ease-out hover:brightness-90 active:scale-[0.98]']"
            >
              Create your account
              <Icon name="arrow" class="h-4 w-4 transition-transform group-hover/cta2:translate-x-0.5" />
            </NuxtLink>
            <NuxtLink
              to="/login"
              :class="[FOCUS, TAP, 'inline-flex items-center gap-2 rounded-md px-5 py-3 text-[14px] font-medium text-ink-muted transition-colors hover:text-ink active:scale-[0.98]']"
            >
              I already have one
            </NuxtLink>
          </div>
        </div>
      </section>
    </main>

    <footer ref="footEl" class="border-t border-line-subtle">
      <div class="mx-auto flex w-full max-w-[1200px] flex-wrap items-center justify-between gap-4 px-5 py-7 sm:px-8">
        <div class="flex items-center gap-2.5" :style="reveal(footIn)">
          <span class="grid h-6 w-6 place-items-center rounded text-ink-faint ring-1 ring-inset ring-line-subtle">
            <Icon name="meridian" class="h-3 w-3" />
          </span>
          <span class="text-[12.5px] text-ink-muted">Meridian · internal platform</span>
        </div>
        <div class="flex flex-wrap items-center gap-x-5 gap-y-2" :style="reveal(footIn, 60)">
          <!-- Only the destinations that exist. A footer of links to nothing is worse than
               a short footer. -->
          <a :href="config.public.pulseUrl as string" :class="[FOCUS, 'rounded text-[12px] text-ink-muted transition-colors hover:text-ink']">Pulse</a>
          <a :href="config.public.forgeUrl as string" :class="[FOCUS, 'rounded text-[12px] text-ink-muted transition-colors hover:text-ink']">Forge</a>
          <NuxtLink to="/login" :class="[FOCUS, 'rounded text-[12px] text-ink-muted transition-colors hover:text-ink']">Sign in</NuxtLink>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* The dashes travel along the token path. Scoped, because it is the only place on the
   platform that needs it — and it finishes on the resting state, so reduced motion
   leaves the diagram whole. */
@keyframes flow {
  to {
    stroke-dashoffset: -16;
  }
}

.flow {
  animation: flow 2.4s linear infinite;
}
</style>
