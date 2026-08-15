# Meridian frontend spec — rebuilding the React prototype in Nuxt/Vue

**Status:** handoff document. Nothing in it is shipped yet.
**Audience:** whoever builds the Nuxt screens. Assumes no prior context.

---

## 1. Purpose and status

There is a 20-screen prototype of the whole platform — landing page, auth,
Pulse, Forge and the Identity console — built as a single React component tree
by MagicPath. **It is a design artefact. It is not shipped and it will not be.**
It has no router, no data layer, no network calls; every screen reads a fixture
file and every write is a `setTimeout`.

**The target is Nuxt/Vue**, in the three frontends that already exist in this
repo:

| App | Port | Backend | Base |
|---|---|---|---|
| `services/identity/frontend` | 3002 | identity, `:8001` | — |
| `services/pulse/frontend` | 3001 | pulse, `:8002` | — |
| `services/forge/frontend` | 3000 | forge, `:8003` | — |
| `packages/ui` | — (Nuxt layer) | — | extended by all three |

Prototype source (outside the repo, in a scratchpad — copy anything you need
before it is cleaned up):

```
ws4_site/src/index.css                             design tokens
ws4_site/src/components/generated/site/chrome.tsx  shared primitives
ws4_site/src/components/generated/site/router.tsx  the 20-route union + ScreenProps
ws4_site/src/components/generated/site/data.ts     fixtures
ws4_site/src/components/generated/site/screens/    the 20 screens
```

Rendered screenshots of all 20 desktop screens are in `shots/out4/`.

Live prototype canvas: MagicPath project `438008400455041024`, component
`glad-pond-2813`.

**Roughly half the screens already have a shipped Vue counterpart.** Section 3
says which. Do not start building until you have read that table — three of the
"screens" are revisions of pages that already work against the real API, and one
(Sessions) needs backend endpoints that do not exist.

---

## 2. The design system

### 2.1 Tokens

Verbatim from `ws4_site/src/index.css`. Dark is the designed default; a light
theme exists in name only and is not the reference.

```css
/* surfaces — Radix step roles: 1 app bg, 2 subtle, 3 raised, 4 hover, 5 selected */
--app:            oklch(0.164 0.006 265);
--sunken:         oklch(0.186 0.007 265);
--surface:        oklch(0.213 0.008 265);
--surface-hover:  oklch(0.243 0.009 265);
--surface-active: oklch(0.272 0.011 265);

/* lines — 6 dividers, 7 component borders + focus base, 8 hovered borders */
--line-subtle:    oklch(0.29 0.011 265);
--line:           oklch(0.345 0.013 265);
--line-strong:    oklch(0.43 0.016 265);

/* text — 11 secondary, 12 primary */
--ink:            oklch(0.972 0.004 265);
--ink-muted:      oklch(0.715 0.014 265);
--ink-faint:      oklch(0.565 0.014 265);

--accent:         oklch(0.585 0.19 274);
--accent-hover:   oklch(0.645 0.19 274);
--accent-ink:     oklch(0.79 0.13 274);
--accent-surface: oklch(0.585 0.19 274 / 14%);

--ok:    oklch(0.735 0.16 155);   --ok-surface:   oklch(0.735 0.16 155 / 13%);
--warn:  oklch(0.8   0.15 78);    --warn-surface: oklch(0.8   0.15 78  / 14%);
--bad:   oklch(0.68  0.2  22);    --bad-surface:  oklch(0.68  0.2  22  / 14%);
--info:  oklch(0.7   0.14 245);   --info-surface: oklch(0.7   0.14 245 / 14%);

--radius-sm: 5px;  --radius-md: 7px;  --radius-lg: 10px;  --radius-xl: 14px;

--font-body:    'Inter', ui-sans-serif, system-ui, sans-serif;
--font-heading: 'Inter', ui-sans-serif, system-ui, sans-serif;
--font-mono:    'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
```

Base layer also sets, and these matter:

- `font-variant-numeric: tabular-nums` on `body` — numbers line up in columns
  with no hand-tuning.
- `.mono`, `code`, `kbd` get `font-feature-settings: 'zero' 1` — slashed zero, so
  machine values read as machine values.
- `::selection` uses `--accent-surface`.

The three existing Nuxt apps use `@nuxtjs/tailwindcss` with stock grey/white
utilities. **Porting these tokens is the first task** — every screen below
assumes them.

### 2.2 Rules that were fought for and must not regress

These are not preferences. Each one is a defect that was found and fixed.

**Near-monochrome. Colour only where it carries meaning.**
The primary CTA is near-white on near-black: `bg-ink font-medium text-app
hover:brightness-90 active:scale-[0.98]`. Never a coloured fill. `--accent` is
used for the focus ring and text selection and essentially nothing else.

**`--ink-faint` fails WCAG AA and is for chrome only.**
It measures **4.24:1** on the page background — under the 4.5:1 AA needs for body
text. It is legitimate on: eyebrow labels, column headers, decorative rules, the
ruler readout, placeholder text, disabled hints. It is **not** legitimate on any
value a user reads and acts on — ids, counts, timestamps, emails, deltas,
statuses, names. Those are `ink-muted` or `ink`. *This was the single biggest
visual defect found in the prototype and it must not come back.* When in doubt,
ask "would someone quote this number in a meeting?" If yes, it is not faint.

**Status decoration must not outrank the data it annotates.**
Measured on the page background: `--ok` **8.78:1**, `--warn` **10.15:1**,
`--ink-muted` **7.64:1**. Both status colours are *brighter* than the muted text
they sit beside — so a coloured status word in every row of a table makes the
decoration the loudest thing on screen. In repeated columns, **colour the dot and
mute the label**: `<StatusDot tone="ok" quiet>` renders a coloured 6px dot with an
`ink-muted` word. Full-colour `StatusDot` is for single, non-repeating places (a
page header, a connection state).

**Type.** Mono labels are 11px minimum. Tracking is capped at `0.08em` below
12px — the standard mono label string is
`mono text-[11px] uppercase tracking-[0.08em]`. Wider tracking at that size
shreds legibility. Body text sits at 12–13.5px; headings use
`text-[clamp(1.5rem,2.2vw,1.9rem)] font-semibold tracking-[-0.035em]` on console
screens and `clamp(2rem,4.6vw,3.2rem) tracking-[-0.04em]` on editorial ones.

**Radius.** Controls and containers take one step (`rounded-md`, `--radius-md`,
7px in the CSS — the intent stated during the design pass was 6px; pick one and
apply it everywhere). Small chips take Tailwind's default `rounded` (4px).
`rounded-full` appears **only** on 6px status dots and avatars. No other radii.

*Uncertainty: the CSS declares 5/7/10/14 for sm/md/lg/xl but the design rule as
stated is 6px/4px. I did not resolve which is authoritative. Decide once, before
building the button.*

**Hairline rules divide; nested boxes do not.**
Depth comes from the surface ramp, not from borders everywhere. Sections are
separated with `border-t border-line-subtle`, tables with
`divide-y divide-line-subtle`. A filled card (`bg-surface/40 ring-1 ring-inset
ring-line-subtle`) is used sparingly, for a thing that is genuinely a distinct
object. Never a box inside a box.

**Editorial and left-aligned.** No centred hero, no centred card layouts.
Everything hangs off a left rule. Content is capped at `max-w-[1200px]` with
`px-5 sm:px-8`; prose is capped in characters (`max-w-[74ch]`,
`max-w-[52ch]`) rather than pixels.

**Focus ring must clear 3:1.**
`index.css` still contains a `.focus-ring` utility built on `ring-accent/70`,
which measures **2.69:1** against the page — below the 3:1 WCAG 1.4.11 asks of a
non-text indicator. **It is dead code.** Every screen uses the `FOCUS` constant
exported from `chrome.tsx`:

```
outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-ink)]
focus-visible:ring-offset-2 focus-visible:ring-offset-app
```

`--accent-ink` at full opacity measures **9.61:1**. Port the `FOCUS` version and
delete `.focus-ring` rather than carrying both across.

*(Contrast figures above were measured during the prototype's accessibility pass.
I did not independently re-measure them for this document.)*

---

## 3. Screen inventory

`Owner` = which Nuxt app the route should live in. `Auth` = the guard.

| # | Route id | Prototype file | Proposed Nuxt path | New / Revision | Owner | Auth | Purpose |
|---|---|---|---|---|---|---|---|
| 1 | `landing` | `Landing.tsx` | identity `/` (signed out) | **NEW** | identity | public | Umbrella front door. Two products, one login. |
| 2 | `signin` | `SignIn.tsx` | `packages/ui` `/login` | **REVISION** of `identity/pages/login.vue`, `pulse/pages/login.vue`, `forge/pages/login.vue`, `forge/pages/signup.vue` | ui layer | public | Sign in / create account in one tabbed screen. |
| 3 | `forgot` | `Forgot.tsx` | `packages/ui` `/forgot-password` | **REVISION** of `packages/ui/pages/forgot-password.vue` | ui layer | public | Request a reset link. |
| 4 | `reset` | `Reset.tsx` | `packages/ui` `/reset-password?token=` | **REVISION** of `packages/ui/pages/reset-password.vue` | ui layer | public | Set a new password from an emailed token. |
| 5 | `invite` | `AcceptInvite.tsx` | `packages/ui` `/invites/accept?token=` | **REVISION** of `packages/ui/pages/invites/accept.vue` | ui layer | public | Preview and accept a department invite. |
| 6 | `products` | `Products.tsx` | identity `/products` | **NEW** | identity | signed in | Product picker after sign-in. |
| 7 | `account` | `Account.tsx` | identity `/account` | **REVISION** of `identity/pages/account.vue` | identity | signed in | Own profile, password, sessions. |
| 8 | `pulse.home` | `PulseHome.tsx` | pulse `/` | **NEW** (pulse `/` is currently Activity) | pulse | signed in | Pulse overview hub — what is waiting on you. |
| 9 | `pulse.activity` | `PulseActivity.tsx` | pulse `/activity` | **REVISION** of `pulse/pages/index.vue` | pulse | signed in | Synced GitHub activity, four counts + four lists. |
| 10 | `pulse.reports` | `PulseReports.tsx` | pulse `/reports` | **REVISION** of `pulse/pages/reports/index.vue` **and** `pulse/pages/review.vue` (merged) | pulse | signed in | My reports + review queue, tabbed. |
| 11 | `pulse.report` | `PulseReport.tsx` | pulse `/reports/:id` | **REVISION** of `pulse/pages/reports/[id].vue` | pulse | signed in | One report, its evidence, its history. |
| 12 | `pulse.newreport` | `PulseNewReport.tsx` | pulse `/reports/new` | **REVISION** of `pulse/components/NewReportForm.vue` (promoted from inline component to a route) | pulse | signed in | Create a report, blank or AI-drafted. |
| 13 | `pulse.repos` | `PulseRepos.tsx` | pulse `/repositories` | **REVISION** of `pulse/pages/repositories.vue` | pulse | signed in | File repos to departments, name lead/deputy, tracking. |
| 14 | `pulse.sync` | `PulseSync.tsx` | pulse `/sync` | **NEW route**, revising logic currently inline in `pulse/pages/index.vue` (GitHub account, connect, last 5 sync runs) | pulse | signed in | GitHub connection + full sync run ledger. |
| 15 | `forge.home` | `ForgeHome.tsx` | forge `/` | **REVISION** of `forge/pages/index.vue` + `datasets/index.vue` + `datasets/[id].vue` + `components/DatasetUpload.vue` (consolidated onto one screen) | forge | signed in | Upload, preview, delete datasets; honest "not built yet" rail. |
| 16 | `identity.people` | `IdentityPeople.tsx` | identity `/people` | **REVISION** of `identity/pages/users.vue` | identity | platform admin | Account directory, deactivate/delete/invite. |
| 17 | `identity.org` | `IdentityOrg.tsx` | identity `/departments` | **REVISION** of `identity/pages/departments/index.vue` + `departments/[id].vue` (merged into a master/detail) | identity | signed in (detail: dept member) | Departments, teams, rosters, heads. |
| 18 | `identity.access` | `IdentityAccess.tsx` | identity `/access` | **NEW** | identity | signed in | "Can X do Y" — 12 capabilities, computed, with the guard that enforces each. |
| 19 | `identity.sessions` | `IdentitySessions.tsx` | identity `/sessions` | **NEW** — and **partly unbuildable, see §8** | identity | platform admin | Refresh-token families, revocation, security events. |
| 20 | `notfound` | `NotFound.tsx` | `packages/ui` `error.vue` | **NEW** (currently Nuxt's stock 404) | ui layer | either | Says what was not found and offers two or three real places to go. |

### 3.1 The architectural question this table exposes

The prototype is **one site** with a top bar that walks between Pulse, Forge and
Identity. The repo is **three Nuxt apps on three ports with three separate
`authStoragePrefix` values** (`identity`, `pulse`, `forge` — see each
`nuxt.config.ts`). Signing in to Pulse today does **not** sign you in to Forge:
the tokens live under different `localStorage` keys on purpose.

So the prototype's "All products" button and the products picker do not work as
drawn. Two options, and this needs a decision before build:

- **(a) Keep three apps.** Cross-product links become absolute URLs from
  `runtimeConfig` and each hop re-authenticates. Cheap, honest, and the "one
  login" promise degrades to "one set of credentials".
- **(b) Share one token namespace** across the three apps (one prefix, or move to
  a cookie on a shared parent domain). Delivers the prototype's promise. Changes
  the storage contract in `packages/ui/composables/useTokenStorage.ts` and will
  sign out every existing browser once.

I recommend (b) with a cookie on a shared domain, but this is a product/security
call, not mine. Until it is made, build every screen inside its own app and put
cross-product links behind a `runtimeConfig` URL.

---

## 4. Per-screen detail

Conventions used below: **`I`** = identity service (`:8001`), **`P`** = pulse
(`:8002`), **`F`** = forge (`:8003`). All paths are as mounted (router prefixes
verified against `app/main.py` in each service).

---

### 4.1 `landing` — NEW — identity `/`

**Layout.** Sticky `TopBar` (logo, product links, Sign in, Get started) →
`RulerStrip` → hero in a 12-col grid: left column is the headline
(`One login. Every tool your engineers open.`) plus a paragraph and two CTAs;
right column is a `Tabs` (variant `mono`) switching a static Pulse/Forge preview
card. Below: a "Different jobs. Same account." two-product section, a "One
identity service" section with an SVG token-path diagram, and a closing CTA band.
A `TRUST` strip of four numbered items runs under the hero.

**State.** `active: 'pulse' | 'forge'` (preview tab); `cursor` (a mouse-position
value used for a subtle hover effect on the hero); `useReveal()` per section for
scroll-triggered entrance.

**Backend.** None. Every CTA calls `startAuth('signin' | 'signup')` → `/login`.

**Empty/loading/error.** None — it is static.

**A11y to preserve.** Skip link in `TopBar`. Real `role="tablist"` on the preview
switcher with a mounted `TabPanel`. All CTAs are buttons or links, never divs.

**Note.** The hero paragraph says "one permission model, **one audit trail**" and
the `TRUST` strip's fourth item is "Audit trail". There is no audit log. See §8.

---

### 4.2 `signin` — REVISION — `packages/ui` `/login`

**Layout.** Two-column editorial split. Left: eyebrow, large headline that swaps
with the tab, a paragraph explaining that identity is the only service that
stores a password, the `TRUST` list, and a signing-key line. Right: `Mark`, a
two-item `Tabs` (`Sign in` / `Create account`), then the form inside a
`TabPanel`.

**State.** `tab`, `email`, `pw`, `touched.{email,pw}`, `busy`, `note`.
Validation is **computed, not stored**, so the message tracks the field as it is
typed rather than lagging a keystroke. Errors only render once `touched`.

**Actions → endpoints.**

| Action | Call | Payload | Errors the UI must handle |
|---|---|---|---|
| Sign in | `POST I /auth/login` (10/min) | `{ email, password }` | 401 wrong credentials — one generic message, never "no such user"; 429 rate limited; 403 deactivated account |
| Create account | `POST I /auth/signup` (5/min) → 201 | `{ email, password, first_name, last_name }` | 400 password rules (`validate_password`); 409 email taken; 429 |
| After either | `GET I /me` | — | non-fatal; keep the `UserResponse` from the token pair (this is what `useAuth.login()` already does) |
| Forgot? | route to `/forgot-password` | — | — |

Both endpoints return a `TokenPair`; `useAuth().persist()` already handles
storage + `fetchMe()`.

**Client-side rules.** Email regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`. Password: min 8
on sign-in; on create-account use the **full** `usePasswordRules()` composable
that already exists in `packages/ui` — the prototype's create-account tab only
checks "8 chars + one digit", which is weaker than the server's
`validate_password()` and will produce a surprise 400. Fix this in the rebuild.

**Empty/loading/error.** `busy` disables submit and applies `.btn-busy` (a
sweeping hairline). The arrow icon **stays mounted** while the request is out
(opacity 0) so the button does not resize mid-wait.

**A11y to preserve.** `role="tablist"` with roving tabindex and a mounted panel;
`aria-invalid` + `aria-describedby` on both fields; `role="alert"` on every field
error; autofocus on the email field **only on fine pointers and ≥768px** — on a
phone it pops the keyboard over the page.

**Deviation from the prototype.** Drop the "Fill in the demo credentials" button
and the "this is a demonstration" paragraph. They are prototype-only.

---

### 4.3 `forgot` — REVISION — `packages/ui` `/forgot-password`

**Layout.** Same two-column editorial split. Left column explains why the answer
is deliberately unhelpful. Right column is either the form or the "Check your
email" confirmation.

**State.** `email`, `touched`, `busy`, `sent`, `sends` (a local counter to
anticipate the server's 5/min limit).

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| Send reset link | `POST I /auth/forgot-password` (5/min) → **204 either way** | 429 only. There is no 404 and must never be one — a different answer for a real address is an account-enumeration oracle |
| Send it again | same | 429 → show the throttle notice |

`PASSWORD_RESET_EXPIRE_MINUTES` is 30 in the identity service; the copy states
that number, so read it from config rather than hard-coding if you can.

**Empty/loading/error.** After success, focus moves to the confirmation
paragraph (`tabIndex={-1}` + `.focus()`) and `announce()` fires. The
sixth send in a minute renders a `role="alert"` warn panel.

**A11y to preserve.** Focus move to the confirmation; `aria-live` announcement;
`role="alert"` on the field error and the throttle notice; pointer-conditional
autofocus.

**Deviation.** Drop the "Open the reset link" demo shortcut and the fake token.

---

### 4.4 `reset` — REVISION — `packages/ui` `/reset-password?token=`

**Layout.** Same split. Right column has three states: dead link, form, done.

**State.** `pw`, `confirm`, `touched.{pw,confirm}`, `busy`, `done`. Token comes
from the query string and is **never rendered in full** — the prototype shows
`token.slice(0,8)…`, which is the right instinct; in the real build, do not
render it at all.

**Actions → endpoints.**

| Action | Call | Payload | Errors |
|---|---|---|---|
| Set new password | `POST I /auth/reset-password` (5/min) → 204 | `{ token, new_password }` | 400 invalid/expired/used token → render the dead-link state, not a field error; 400 password rules; 429 |

**Password rules.** Use `usePasswordRules()` from `packages/ui` — it already
mirrors `validate_password()` exactly (8 chars, upper, lower, digit, symbol) and
adds the 72-**byte** bcrypt cap that the prototype also enforces. Show the rules
as a live checklist with `sr-only` "— met" / "— not met yet" per item.

**A11y to preserve.** Live rule checklist with screen-reader state; `role="alert"`
errors; the "done" panel takes focus.

---

### 4.5 `invite` — REVISION — `packages/ui` `/invites/accept?token=`

**Layout.** Same split. Left column becomes a definition list of what the invite
actually says once the preview resolves. Right column: checking → dead → form.

**State.** `checking`, `preview`, `dead`, `first`, `last`, `pw`, `touched`,
`busy`.

**Actions → endpoints.**

| Action | Call | Payload | Errors |
|---|---|---|---|
| On mount | `GET I /invites/preview?token=` (20/min) | — | 400 invalid / expired / already-used → three **distinct** dead states with different advice (see `DEAD` in `AcceptInvite.tsx`); 429 |
| Accept | `POST I /invites/accept` (5/min) → `TokenPair` | `{ token, first_name?, last_name?, password? }` | 400 same three; 409 already accepted; 400 password rules |

`InvitePreview` returns `email`, `dept_name`, `team_name`, `role`,
`needs_account`, `invited_by_name`, `expires_at`. The last two were **just
added** and are uncommitted at time of writing — see §8.

When `needs_account` is false the address already has an account: hide the name
and password fields entirely, the button reads "Accept invitation", and the copy
says the password does not change.

**After success.** `useAuth().adoptSession(pair)` — accepting returns a token
pair, so the invitee lands signed in rather than at a second login form.

**Empty/loading/error.** The "checking" state renders three grey skeleton bars
with `aria-hidden` and a `role="status"` sentence. Nothing is typeable until the
preview resolves — deliberate.

**A11y to preserve.** `role="status"` on the checking copy; `role="alert"` on the
dead-link detail; live password rules; pointer-conditional autofocus once the
preview lands.

---

### 4.6 `products` — NEW — identity `/products`

**Layout.** `TopBar` (signed in) → `RulerStrip` → editorial header → three
"door" cards for Pulse, Forge and Identity. **The card itself is the button** —
Tab reaches it once, Enter opens it, and the "Open" line inside is a label, not a
second tab stop.

**State.** None. Counts on the cards are derived from the fixture; in the real
build they come from cheap summary calls.

**Actions → endpoints.**

| Card | Live figure it should show | Call |
|---|---|---|
| Pulse | reports total / mine / awaiting review | `GET P /reports?limit=1` for the total; `GET P /reports/review-queue?limit=1` for the count awaiting you |
| Forge | dataset count | `GET F /datasets/summary?recent=0` |
| Identity | live sessions / departments / people | `GET I /me/sessions`; `GET I /departments`; `GET I /platform/users?limit=1` (platform admin only) |

If a figure cannot be fetched, drop the line rather than showing zero — a zero
here is indistinguishable from a failure.

**Gating.** The Identity card should not be offered to a non-platform-admin who
has no department admin role. Prototype does not gate it.

**A11y to preserve.** One tab stop per card; `aria-label` on the card describing
the destination; 44px touch targets.

---

### 4.7 `account` — REVISION — identity `/account`

**Layout.** No `ProductShell` — this is not a product. `TopBar breadcrumb="Account"`
→ `RulerStrip` → editorial header → four hairline-separated sections in a
12-column grid (4-col explanation, 8-col content): **Profile**, **Where you sit**,
**Password**, **Sessions**.

The split is deliberate: things you administer yourself are forms; things a
department admin administers are **facts rendered as a definition list**, not
disabled inputs. A disabled input suggests it might one day be typed into.

**State.** `first`, `last`, `nameTouched`, `savingName`, `savedName`,
`nameDirty`; `current`, `next`, `confirm`, `pwTouched`, `savingPw`;
`confirmAll` (modal).

**Actions → endpoints.**

| Action | Call | Payload | Errors |
|---|---|---|---|
| Save profile | `PATCH I /me` → `UserMeResponse` | `{ first_name, last_name }` | 401; 422 on empty strings (schema has `min_length=1`) |
| Change password | `POST I /auth/change-password` (5/min per user-or-address) → **`TokenPair`** | `{ current_password, new_password }` | 401 wrong current password; 400 password rules; 429 |
| Load sessions | `GET I /me/sessions` → `SessionResponse[]` | — | 401 |
| Sign out everywhere | `POST I /auth/logout-all` → 204 | — | 401 |

**Important:** `change-password` returns a fresh token pair. It revokes every
refresh family on the account and bumps `token_version`, then re-issues *this*
device. So you must `persist()` the returned pair or the user is signed out of
the tab they just used. The copy already promises this behaviour.

**Session row fields** (from `SessionResponse`): `session_id`, `started_at`,
`last_used_at`, `rotations`, `expires_at`, `is_revoked`, `is_current`.
Derived states: revoked / expired (`expires_at` in the past) / idle
(`last_used_at` ≥ 3 days ago) / refreshing. **There is no device and no location
column** and the screen says so in plain text — keep that paragraph.

**Empty/loading/error.** Save button disabled unless `nameDirty`; an "unsaved"
mono marker appears when dirty. `.btn-busy` during both saves.

**A11y to preserve.** `role="alert"` on every field error; live password rule
checklist with `sr-only` state; `Modal` focus trap on "Sign out everywhere" with
focus landing on **Cancel**, not the destructive button (the `Modal` primitive
does this by skipping `data-modal-close` and preferring the first field, then the
first non-close control); `announce()` after each save.

---

### 4.8 `pulse.home` — NEW — pulse `/`

**Layout.** `ProductShell product="pulse"` → editorial header → a "This week"
panel naming the repository you lead → a `Tabs` (variant `mono`) switching
between "Waiting on you" and "Your recent reports", each a short list.

No dashboard. The figures that belong to a week live on that week's report, not
here — that is the stated rule and it is why this screen is short.

**State.** `scope: 'waiting' | 'mine'`.

**Actions → endpoints.**

| Element | Call |
|---|---|
| Waiting on you | `GET P /reports/review-queue?limit=5` |
| Your recent reports | `GET P /reports?author_user_id={me}&limit=5` |
| This week's counts | `GET P /activity/me?since={monday}&repo_id={lead repo}` |
| New report CTA | route to `/reports/new` |

**Empty/loading/error.** Both lists need an empty state. "Nothing waiting on you"
must say *why* it can be empty — reports you wrote are never in your own queue.

**A11y.** `aria-labelledby` on each section; `role="tablist"` on the scope
switcher.

---

### 4.9 `pulse.activity` — REVISION of `pulse/pages/index.vue` — pulse `/activity`

**Layout.** `ProductShell` → header with the subject's name → three `Select`
controls (person, period, repository) → four big count tiles → four lists
(commits, PRs, reviews, issues), each capped at ten rows. Selecting a tile
narrows to that one kind.

**State.** `subjectId`, `period: 7|30|90`, `repoId: number|null`, `only: Kind|null`,
`loading`, `data`. Counts animate with a `useCountUp` hook that is skipped under
`prefers-reduced-motion`.

**Actions → endpoints.**

| Action | Call |
|---|---|
| Own activity | `GET P /activity/me?since={ISO date}&repo_id={id?}` |
| Someone else's | `GET P /activity/{user_id}?since=&repo_id=` |
| Repository options | `GET P /github/repositories?limit=50` |
| Person options | teammates — the shipped `useTeammates()` composable already does this |

Errors: 403 when you ask for a user you have no oversight of; 404 unknown user.

**Three payload limitations the screen states out loud — keep all three.**
1. A review row carries an internal `pull_request_id` and **no** repository and
   **no** PR number. Do not invent them.
2. Repository names are resolved separately; an id identity cannot resolve renders
   as `repo_id 7 · unresolved`, in italic faint, never as a fabricated name.
3. Four zeroes for *someone else* can mean "you have no oversight of them", not
   "they did nothing". Say which.

There is **no per-day series in the payload**, so nothing on this screen may look
like a chart. Ten rows cannot honestly draw a thirty-day line.

**Empty/loading/error.** Skeleton rows during `loading`; a per-kind empty line;
a whole-screen empty state when the GitHub account is not connected, linking to
`/sync`.

**A11y to preserve.** `Select` listbox semantics (see §6); `aria-live` on the
count region when the period changes; the kind filter is a toggle group with
`aria-pressed`.

---

### 4.10 `pulse.reports` — REVISION of `reports/index.vue` + `review.vue` — pulse `/reports`

This screen **merges two shipped routes**. `pulse/pages/review.vue` currently
exists as its own page; the prototype makes it the second tab. Decide whether to
keep `/review` as a redirect.

**Layout.** `ProductShell` → header with a `GET /reports?…` readout chip and a
"New report" button → `Tabs` (`My reports` / `Review queue`, each with a count
hint) → a collapsible "Who decides" explainer (queue tab only) → a status filter
chip row + a repository `Select` (mine tab only) → the table → offset pagination.

**A queue row opens where it sits.** Reading a report and deciding it is one
task; bouncing to another screen and back is a worse version of the same thing.
The expanded panel shows the three summary fields, the counts it was drafted
from, and a decision box with a note textarea and three buttons.

**State.** `rows`, `scope`, `status`, `repo`, `dir`, `page`, `open` (expanded row),
`note`, `menu` (row ⋯ menu), `confirm` (delete modal), `who` (explainer).
`PER_PAGE = 8`.

**Actions → endpoints.**

| Action | Call | Notes |
|---|---|---|
| My reports | `GET P /reports?author_user_id={me}&repo_id=&status=&limit=8&offset=` | `status` is validated server-side; an unknown value is a 422 |
| Review queue | `GET P /reports/review-queue?status=submitted&limit=8&offset=` | defaults to `submitted` |
| Approve | `POST P /reports/{id}/approve` | body `DecisionRequest` optional — `{ note }` |
| Request changes | `POST P /reports/{id}/request-changes` | same |
| Reject | `POST P /reports/{id}/reject` | same |
| Submit for review (row menu) | `POST P /reports/{id}/submit` | **422** if all three summaries are null — the prototype pre-empts this client-side and shows `422 · report N has no summaries yet`; keep the pre-empt *and* handle the real 422 |
| Delete draft (row menu) | `DELETE P /reports/{id}` → 204 | enabled only when `status === 'draft'` |
| Open | route to `/reports/{id}` | |

Error cases on the decisions: **403 on your own report** — authorship is checked
before any admin power, so a platform admin is refused on their own report like
anyone else. Also 403 when you are not the repo lead/deputy or a dept admin;
409 when the report has already been decided.

**The queue rule, stated in code:** a report is in your queue when
`status === 'submitted'` **and** you are the repo's lead or deputy or an admin of
its department, **and** you did not write it. The third clause is the one people
assume is missing, so the "Who decides" panel says it out loud. Keep that panel.

**Three distinct empty states — all three are needed.**
1. Queue empty: "Nothing is waiting on you" + why an empty queue is not an idle
   team.
2. Mine empty: "You have not written a report yet" + a New report CTA.
3. Filtered to nothing: "No report matches this filter" + a Clear filters button.

**A11y to preserve.** `aria-sort` on the Week column header; `aria-expanded` +
`aria-controls` on the "Read and decide" button; the expanded row **stays
mounted** (so `aria-controls` always points at something real) but its controls
are `disabled` while collapsed, otherwise clipped content is still in the tab
order; `role="menu"` / `role="menuitem"` on the ⋯ menu with click-outside and
Escape; `<caption class="sr-only">` on the table, with `relative` on the scroll
wrapper — `sr-only` is `position: absolute` and with no positioned ancestor the
caption anchors to the page and widens the document.

**A status chip that filters to nothing keeps its word and loses its dot** —
colour with no referent is noise.

---

### 4.11 `pulse.report` — REVISION of `reports/[id].vue` — pulse `/reports/:id`

**Layout.** `ProductShell` → back link → header (week, repository, author,
status) → four count tiles that act as filters over an evidence list → the three
summary fields, each editable in place → a decision box when a decision is live →
an approval/comment history.

The evidence sits **beside** the claim, not behind a link. Selecting a count tile
narrows the evidence list to that kind. Reading the claim and checking it is one
movement.

**State.** `status`, `fields.{manager,exec,next}`, `edited` (per-field "edited"
marker), `editing` (which field is open), `draft` (the in-progress text), `only`
(count filter), `note`, `history`.

**Actions → endpoints.**

| Action | Call | Notes |
|---|---|---|
| Load | `GET P /reports/{id}` | 403 no read access; 404 |
| Evidence | `GET P /activity/{author_user_id}?since={week_start}&repo_id={repo_id}` | counts may come back empty on their own — say so, do not render zeros |
| Save a field | `PATCH P /reports/{id}` | `{ summary_manager? , summary_exec?, next_week_goals? }`; **409/403 when the report is approved** — an approved report is closed to edits |
| Submit | `POST P /reports/{id}/submit` | 422 if all three fields are null |
| Approve / reject / request changes | `POST P /reports/{id}/{approve\|reject\|request-changes}` | body `{ note }` optional; 403 on your own |
| History | `GET P /reports/{id}/approvals?limit=` | |
| Comments | `GET P /reports/{id}/comments`, `POST`, `PATCH /{comment_id}`, `DELETE /{comment_id}` | the shipped `[id].vue` already implements all four — **do not drop comments**, the prototype has no comment thread but the shipped page does |
| PDF | `GET P /reports/{id}/pdf` | returns a `Response`, not JSON |

**Rule the screen enforces:** nothing that would be a lie is possible. Editing is
disabled on an approved report; the decision box only exists while a decision is
being asked for; every change writes itself into the history with a name.

**Fallback.** The prototype falls back to report 340 when it has no param. In
Nuxt, a missing or unknown `:id` is a 404 — use `createError({ statusCode: 404 })`.

**A11y to preserve.** `role="alert"` on save failures; `aria-live` on the status
change; count tiles are `aria-pressed` toggles; focus returns to the field's edit
button after save.

---

### 4.12 `pulse.newreport` — REVISION of `NewReportForm.vue` — pulse `/reports/new`

**Layout.** `ProductShell` → back link → header → "Subject" (repository `Select`
+ week `Select` + a mono readout of `repo_id / week_start / dept_id`) → a panel
explaining which repositories are *not* offered and why → the duplicate warning
when one applies → "What a draft would be written from" (four count tiles) → two
buttons → once created, three editable textareas + Submit/Save.

**State.** `repoId`, `week`, `working: 'generate'|'blank'|null`, `report`,
`fields`, `saving`.

**Actions → endpoints.**

| Action | Call | Payload | Errors |
|---|---|---|---|
| Draft from synced activity | `POST P /reports/generate` (**10/hour** per user) → 201 | `{ repo_id, week_start }` | **422** nothing synced for that week; **409** duplicate; **502** model unavailable; 403 no activity in that repo |
| Start blank | `POST P /reports` (30/min) → 201 | `{ repo_id, week_start }` | **403** "You have no synced activity in this repo"; **409** duplicate |
| Save draft | `PATCH P /reports/{id}` | the three fields | |
| Submit | `POST P /reports/{id}/submit` | — | 422 when all three are empty |

**Both buttons create the report immediately.** The fields are editable from the
moment you choose because the draft already exists — pressing the button *is* the
write. Say so; do not present it as a two-step wizard.

**The duplicate constraint is `uq_report_author_repo_week`** —
`(author_user_id, repo_id, week_start)`. It is **per person** per repo per week,
not per repo per week. So somebody else writing about the same repo and week is
not in your way; only your own report is. The warning panel must say this, offer
"Open report #N", and — only when one exists — offer to jump to a free week.

**Week normalisation.** The API takes `week_start` and snaps it to the Monday
(`_monday()` in `services/pulse/app/services/reports.py`). The shipped
`NewReportForm.vue` computes `mondayOf()` client-side and shows the canonical
week; keep that.

**Eligibility conflict — read §8.5 before building the repository picker.**

**A11y.** Labelled `Select`s; `announce()` when a draft is created and when the
week is auto-moved; `role="alert"` on the 409/422 panels; character counts per
field are decorative and may stay faint.

---

### 4.13 `pulse.repos` — REVISION of `repositories.vue` — pulse `/repositories`

The screen the whole approval flow depends on. A repository arrives from the sync
with no department and nobody named; in that state a report about it belongs to
no department and only a platform admin can decide it.

**Layout.** `ProductShell` → header → **the unfiled queue** (a highlighted
section, one row per unfiled repo, each with a department `Select` and a File
button) → search + a three-way `Tabs` filter (All / Unfiled / Not tracked) →
a sortable table → per-row expandable "Manage" panel with two columns: the
lead/deputy pickers on the left, the report history on the right.

**State.** `rows`, `query`, `filter`, `sort: 'name'|'synced'|'reports'`,
`dir`, `openRow`, `fileTo` (per-row department draft), `leadDraft`,
`deputyDraft`, `approverError`, `busy` (keyed per write), `untrackId` (modal).

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| List | `GET P /github/repositories?limit=50&offset=0` (`tracked_only` optional) | 401 |
| Unfiled queue | `GET P /github/repositories/unfiled?limit=&offset=` | 401 |
| File to a department | `PUT P /github/repositories/{repo_id}/department/{dept_id}` | 403 not a dept admin / platform admin; 404 |
| Bulk file | `PUT P /github/repositories/department/{dept_id}` with a body of ids | same |
| Approver candidates | `GET P /github/repositories/{repo_id}/approver-candidates` | 403; 404 |
| Set lead | `PUT P /github/repositories/{repo_id}/lead/{user_id}` | 400 lead == deputy; 403; 404 |
| Clear lead | `DELETE P /github/repositories/{repo_id}/lead` | |
| Set deputy | `PUT P /github/repositories/{repo_id}/deputy/{user_id}` | 400 lead == deputy |
| Clear deputy | `DELETE P /github/repositories/{repo_id}/deputy` | |
| Track | `PUT P /github/repositories/{repo_id}/tracked` | 403 |
| Untrack | `DELETE P /github/repositories/{repo_id}/tracked` | 403 |
| Departments for the picker | `GET I /departments` | |

The shipped `repositories.vue` already sequences the lead/deputy saves correctly
(clear before set, so a swap does not trip the "two different people" rule).
**Reuse that mutation, do not rewrite it.**

**The approver picker is not a directory search.** `/approver-candidates` returns
the people whose commits, PRs or issues appear in that repository, **plus**
whoever holds a post today, and marks which is which. A post-holder with no
activity is shown and labelled `· no activity here`, not quietly dropped. Someone
who has never worked there is not in the list at all.

**Filing restamps.** Filing a repository moves every report already written about
it into that department, which is how a stranded report becomes reviewable
without being rewritten. Say this in the copy.

**Untracking asks first**, in a `Modal` with four specific consequences (the next
run records `skipped`; already-synced activity and reports stay; a report drafted
from now on draws on a stale week; the department and posts are untouched and
re-tracking resumes from the stored cursor). Keep the specifics — a generic "are
you sure" is useless here.

**Empty/loading/error.** "Every repository has a department" for an empty unfiled
queue, phrased so it is clear the list refills after the next sync. "No repository
matches" with a Clear button. "Nobody has synced work in this repository yet" when
the candidate list is empty.

**A11y to preserve.** `aria-sort` on the three sortable headers; `aria-expanded` +
`aria-controls` on the Manage toggle; per-write `busy` keys so two rows can be
saving independently; `<caption class="sr-only">`; `role="alert"` on the
lead-equals-deputy error.

---

### 4.14 `pulse.sync` — NEW route — pulse `/sync`

**Layout.** `ProductShell` → header → **the connection** (login, id, connected_at,
scopes, or a not-connected explainer with the three-step OAuth walkthrough) →
three small tiles (next scheduled run / last run / repositories visited) → a
"the cursor" explainer with three consequences → a warning band when recent runs
failed → the run history table with a repository `Select` filter → expandable
detail rows for runs that carry a reason instead of counts.

**State.** `connected`, `runs`, `repoFilter`, `openRun`, `syncing`, `connecting`,
`confirmDisconnect`.

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| Load account | `GET P /github/account` | **404 when nothing is connected** — that is the not-connected state, not an error toast |
| Connect | `GET P /github/connect` (10/min) → `{ authorize_url }`, then `window.location = authorize_url` | 429 |
| OAuth return | GitHub → `GET P /github/oauth/callback` → **303** back to Pulse with `?github=connected` \| `denied` \| `expired` \| `already_linked` \| `failed` | read the query param on mount and toast accordingly |
| Disconnect | `DELETE P /github/account` → 204 | |
| Sync now | `POST P /github/sync` (5/min) | **403 unless platform admin**; the response is an enqueue acknowledgement, not results — `?wait=true` runs inline and is dev/demo only |
| Run history | `GET P /github/sync-runs?repo_id=&limit=50&offset=0` | |

**Two things the payload cannot give you, said rather than faked.**
1. **There is no trigger column.** A run has no record of what started it. The
   prototype infers `scheduled` from an `02` hour in `started_at` and calls
   everything else `manual`. That is an inference, not a field. Either add the
   column server-side or label the column honestly ("inferred from the hour").
2. **Counts are parsed out of `detail`**, a single string the worker writes in
   the form `full_name: commits=3, branches=0, pull_requests=1, issues=0`. When
   the string does not parse (a failure, a rate limit, a skip), the count cells
   render `—` and the row becomes expandable to show the raw `detail`. Reviews
   are ingested with their pull request and are **not** counted separately in
   that string.

**Empty/loading/error.** "No run recorded for this repository" when the filter
matches nothing. The failure band appears whenever any recent run is `error` or
`rate_limited` and explains the consequence (those repos are stale, so a report
drafted from them is drafted from a short week).

**Disconnect asks first**, again with specifics: runs relying on that token stop
finding anything; already-ingested data and reports stay; your Activity counts
stop moving with no second warning ("four zeroes look the same as a quiet week");
reconnecting resumes from each repository's stored cursor.

**A11y to preserve.** `aria-expanded` + `aria-controls` on the outcome toggles;
`announce()` when a sync is queued; `<caption class="sr-only">`; `Modal` focus
trap.

---

### 4.15 `forge.home` — REVISION — forge `/`

**Layout.** `ProductShell product="forge"` → editorial header → an upload
dropzone → a dataset preview area using `Tabs` (one tab per dataset, real
`TabPanel`) → a right-hand **ledger** listing what runs today vs what is Week 6 →
learning-path and canvas sections drawn in **dashed hairlines with no Run
affordance**, explicitly labelled as not built.

The one rule this screen keeps from the marketing page: the part that works and
the part that does not are never allowed to blur together. Layout does the
differentiating — a work column with a ledger beside it, not Pulse's report rail.

**State.** `datasets`, `activeTab`, `dragging`, `accepted`, `uploadError`,
`rejection`, `pathKey`, `pendingDelete`, `notBuilt` (a modal for the unbuilt
features).

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| List | `GET F /datasets?limit=&offset=` | 401 |
| Summary | `GET F /datasets/summary?recent=5` | |
| Upload | `POST F /datasets` (multipart) → 201 | **5 MB cap** client- and server-side; 400 not a CSV / unparseable; 413 too large |
| Preview | `GET F /datasets/{id}/preview?rows=10` | 404 |
| Delete | `DELETE F /datasets/{id}` → 204 | 403 not yours; 404 |

The shipped `forge/components/DatasetUpload.vue` and `datasets/[id].vue` already
do upload and preview against these endpoints. Reuse them.

**Empty/loading/error.** `role="alert"` on the upload rejection with the specific
reason (the prototype carries a `REJECTIONS` list — keep those messages). Empty
dataset list needs its own state.

**A11y to preserve.** Real `tablist` over datasets; dropzone is keyboard-reachable
via a real `<input type="file">` behind a label; `role="alert"` errors; delete
confirmation in a `Modal`.

---

### 4.16 `identity.people` — REVISION of `users.vue` — identity `/people`

**Layout.** `ProductShell product="identity"` → header → search → a five-way
`Tabs` filter (All / Active / Deactivated / Unverified / Admins) → a table with
row checkboxes, a bulk action bar, and a per-row ⋯ menu → an invite `Modal`.

**State.** `query`, `filter`, `sortDir`, `selected[]`, `overrides` (optimistic
active/platformAdmin), `deleted[]`, `menuFor`, `confirmDelete`, `inviteOpen`,
`inviteEmail`, `inviteDept`, `inviteError`.

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| List | `GET I /platform/users?limit=&offset=&q=` | **403 unless platform admin** — this whole route is platform-admin-only |
| Deactivate | `POST I /platform/users/{id}/deactivate` | 403; 400 on yourself |
| Reactivate | `POST I /platform/users/{id}/reactivate` | 403 |
| Delete | `DELETE I /platform/users/{id}` → 204 | **409 while they still belong to a department** — the membership row would be left pointing at nothing. Surface this as the reason, not a generic failure |
| Grant platform admin | `PUT I /platform/admins/{user_id}` | 403 |
| Revoke platform admin | `DELETE I /platform/admins/{user_id}` | 403; 400 on the last admin |
| Invite | `POST I /departments/{dept_id}/invites` → 201 | 403 not a dept admin; 409 already invited/member |

**Deleting is deliberately harder than deactivating.** The prototype's delete
modal states this. Keep it, and keep the 409 explanation.

**The screen has to be honest about states that are not "fine":** an account can
exist with **no department** (`dept_id: null` → render "Unplaced", never a
guessed department), and an invite can go out and never be accepted. Both are
shown rather than hidden because both need someone to act.

**Invite modal.** `initialFocusRef` is the email field. The department select
offers "Place them later" — but note the invite endpoint is **nested under a
department** (`POST /departments/{dept_id}/invites`), so "later" has no endpoint.
Either drop that option or add a department-less invite path. Flagged.

**A11y to preserve.** `aria-sort`; row checkboxes with a header select-all and an
`aria-live` selection count; ⋯ menu with `role="menu"`, click-outside, Escape;
`Modal` with `initialFocusRef` and `role="alert"` on `inviteError`;
`useAnnounce()` after bulk actions.

---

### 4.17 `identity.org` — REVISION of `departments/*` — identity `/departments`

**Layout.** `ProductShell` → header → a left rail of departments (expandable, one
selected) and a right pane with the selected department's teams, roster, head and
invites. The shipped build splits this across `departments/index.vue` and
`departments/[id].vue`; the prototype makes it one master/detail screen.

**Decision needed:** keep `/departments/:id` as a deep-linkable route (it is
today, and `[id].vue` is 741 lines of working code) and render the master rail
alongside it, rather than collapsing to a single `/departments` with local state.
Deep links to a department already exist and should not break.

**State.** `expanded[]`, `selected`, `rosterQuery`, `openRow`, `removed[]`,
`confirmRemove`.

**Actions → endpoints.**

| Action | Call | Errors |
|---|---|---|
| Departments | `GET I /departments` | |
| One department | `GET I /departments/{id}` | 403 not a member |
| Rename | `PATCH I /departments/{id}` | 403 not a dept admin |
| Create / delete | `POST I /departments`, `DELETE I /departments/{id}` | **403 unless platform admin** |
| Set head | `PUT I /departments/{id}/head/{user_id}` | 403 platform admin only; 400 if the person does not already hold admin there |
| Clear head | `DELETE I /departments/{id}/head` | 403 |
| Members | `GET I /departments/{id}/members?limit=&role=` | 403 not a member |
| Add member | `POST I /departments/{id}/members` | 403 not a dept admin; 409 already a member |
| Change role | `PATCH I /departments/{id}/members/{user_id}?replacement_user_id=` | 403; 409 when the demotion would leave a team or the department unled — pass `replacement_user_id` or `allow_unled=true` |
| Remove member | `DELETE I /departments/{id}/members/{user_id}?replacement_user_id=&allow_unled=` | same |
| Teams | `GET I /departments/{id}/teams`, `POST`, `PATCH /{team_id}`, `DELETE /{team_id}` | 403 dept admin |
| Team manager | `PUT I /departments/{id}/teams/{team_id}/manager/{user_id}`, `DELETE .../manager` | 403 dept admin |
| Team members | `PUT/DELETE I /departments/{id}/teams/{team_id}/members/{user_id}` | 403 unless team manager |
| Invites | `GET/POST I /departments/{id}/invites`, `DELETE .../{invite_id}` | 403 dept admin |

**Two facts this screen exists to make visible.**
1. **A department can have no head.** `head_user_id` is nullable and Operations
   in the fixture has none. Render the gap, never a placeholder name.
2. **An account can belong to no department at all**, which is not the same as
   belonging to an empty one.

Also state the rule that catches people out: **being head grants nothing.**
`head_user_id` names a person; every permission check reads the `role` on the
membership row, never that field.

**A11y to preserve.** `aria-expanded` on the rail items; the roster is a real
table with `aria-sort`; `Modal` on remove-member with the specific consequence
("the account is kept; only the membership row goes").

---

### 4.18 `identity.access` — NEW — identity `/access`

**Layout.** `ProductShell` → header → **the question**: a sentence-shaped control
reading `Can [person ▾] [capability ▾] ?` with a large `Yes` / `No` verdict, a
plain-English reason, the guard that enforces it, and scope/weight marks →
`Tabs` (By person / By capability) → either a "reach ladder" plus can/cannot
lists, or capabilities ranked by what it costs if they are wrong → two rules
stated outright at the foot.

**State.** `personId`, `capId`, `mode: 'person'|'capability'`.

**Backend.** Read-only. `GET I /platform/users` (or `/departments/{id}/members`
for a non-platform-admin) for the person list. The verdicts are computed
client-side from the token claims + memberships — that is the point of the screen:
it shows the same answer the products compute locally.

**The 12 capabilities**, verbatim from `IdentityAccess.tsx`, with scope
(0 own work · 1 repos they lead · 2 their department · 3 the workspace) and weight
(1 routine · 2 changes access · 3 irreversible):

| id | Label | Scope | Weight | Guard |
|---|---|---|---|---|
| `report_own` | Write their own weekly report | 0 | 1 | membership derived from activity (`_may_report_on`) |
| `report_decide` | Approve or reject a report | 1 | 2 | `_can_approve` (pulse) |
| `repo_file` | File a repo and name its lead | 2 | 2 | `_require_can_admin_repo` (pulse) |
| `report_read` | Read every report in their department | 2 | 1 | `role == manager` |
| `invite` | Invite someone into their department | 2 | 2 | `dept_admin` = `require_dept_role("admin")` |
| `place` | Place or remove a member | 2 | 2 | `dept_admin` |
| `role` | Change someone's role | 2 | 2 | `dept_admin` |
| `dept_rename` | Rename their department | 2 | 1 | `dept_admin` |
| `dept_create` | Create or delete a department | 3 | 3 | `require_platform_admin` |
| `dept_head` | Name a department head | 3 | 2 | `require_platform_admin` |
| `directory` | See every account in the workspace | 3 | 1 | `require_platform_admin` |
| `deactivate` | Deactivate or delete an account | 3 | 3 | `require_platform_admin` |

Guard names verified against the code: `require_dept_role` and
`require_platform_admin` in `services/identity/app/security/dependencies.py`;
`_can_approve`, `_can_read`, `_may_report_on` in
`services/pulse/app/services/reports.py`; `_require_can_admin_repo` in
`services/pulse/app/services/repositories.py`.

**Both views are computed by one `verdict()` function.** There is no second table
of answers that could drift from the first. Keep that structure — it is the whole
integrity claim of the screen.

**The two rules at the foot, both worth keeping verbatim in spirit:**
- Being head of a department grants nothing on its own.
- Nobody approves their own report — authorship is checked before any admin
  power, so a platform admin gets the same refusal as an engineer.

**Design note.** Rank marks (`ScopeMark`, `WeightMark`) are **monochrome**, using
a `line-subtle → line → line-strong → ink` ramp. A darker step means further or
heavier. Nothing here is coloured because none of it is a status. The only
colour on the screen is the `Yes`/`No` verdict word and the two `can`/`cannot`
column headers.

**A11y.** Two labelled `Select`s; the verdict block re-keys on
`${personId}-${capId}` to replay a 240ms crossfade; `role="tablist"` with mounted
panels; scope/weight marks are `aria-hidden` with a text equivalent beside them.

---

### 4.19 `identity.sessions` — NEW — identity `/sessions` — **partly unbuildable**

**Layout.** `ProductShell` → header with a destructive "Revoke everything" →
three stat tiles (live sessions / people signed in / idle over 3 days) → a plain
statement of the device/location gap → a two-column body: a filtered table of
refresh-token families on the left, a rail of recent security events and a
"what a rotation count tells you" explainer on the right.

**State.** `killed[]`, `filter: 'active'|'stale'|'all'`, `confirmOne`,
`confirmAll`.

**Endpoints — this is where it breaks.**

| Action the prototype offers | Endpoint that exists | Verdict |
|---|---|---|
| List **your own** families | `GET I /me/sessions` → `SessionResponse[]` | ✅ exists (uncommitted, §8.1) |
| List **everyone's** families | — | ❌ **no endpoint** |
| Revoke **one** family by id | — | ❌ **no endpoint**. `POST /auth/logout` takes a raw refresh token, which a browser only holds for its own current session |
| Revoke **all your own** | `POST I /auth/logout-all` → 204 | ✅ exists |
| Revoke **everyone's** | — | ❌ **no endpoint** |
| Recent security events | — | ❌ **no audit log** (§8.4) |

Verified: the only session code paths are `list_sessions`, `revoke_refresh_token`
(by raw token) and `revoke_all_for_user` in
`services/identity/app/services/auth.py`, and the only route exposing any of them
is `GET /me/sessions`.

**Recommendation.** Build this screen in two stages.
- **Stage 1 (now):** ship it as *your own* sessions, backed by `GET /me/sessions`
  and `POST /auth/logout-all`. That is genuinely useful and needs no backend work.
  Drop the person column, the per-row revoke and the security-events rail.
- **Stage 2 (needs backend):** a platform-admin view needs three new endpoints —
  `GET /platform/users/{id}/sessions`, `DELETE /platform/sessions/{session_id}`,
  and `POST /platform/users/{id}/logout-all`. Do not build the UI first.

**The gap the screen states out loud, and must keep stating:** there is no device
and no location, because `refresh_tokens` records neither. "Chrome on Windows,
Port Harcourt" could only be guessed. What is real is the family id, when it
started, when it last refreshed, and how many times it has rotated — which is
enough to tell a working session from an abandoned one.

**A11y to preserve.** The row Revoke button is `opacity-0` until row hover or
keyboard focus (`focus-visible:opacity-100 group-hover/row:opacity-100
[@media(hover:none)]:opacity-100`) — it must never be unreachable by keyboard or
on touch; `<caption class="sr-only">` with `relative` on the scroll wrapper;
`Modal` focus trap, and the "this is the device you are reading this on" warning
when revoking your current session.

---

### 4.20 `notfound` — NEW — `packages/ui` `error.vue`

**Layout.** Same two-column editorial split as the auth screens. Left: what was
not found (the offending path, truncated — it may be a mistyped token, so never
render it in full). Right: "Where to go instead".

**Behaviour.** What it offers depends on whether there is a session. Signed out,
a list of product links is an invitation to bounce off a sign-in wall, so it
offers sign-in and the front page. Signed in, the front page is the least useful
link on the site, so it offers the product picker and the last place you were.

**"Last place you were"** needs a store. The prototype fakes it from the freshest
fixture report. In Nuxt, record the last successful route in a composable and read
it here, or drop the line.

**Nuxt note.** This becomes `error.vue` at the layer root, handling both 404 and
500. It is not a page and gets no `definePageMeta`.

---

## 5. Routing and URLs — read this before anything else

### 5.1 The prototype has no URLs at all

Navigation is `useState<Route>` over a **closed 20-member string union**
(`router.tsx:30`). One screen is mounted at a time; screens are never stacked.
`nav(route, param?)` sets both the route and a single loose `param` that the next
screen reads. Consequences:

- **Nothing deep-links.** You cannot send someone a link to report 341.
- **The back button does nothing.** There is no history.
- **`param` is untyped** — it is a report id on one screen and an invite token on
  another.
- **Two routes are unreachable from any in-app link.** `invite` is only reached
  from the Forgot screen's demo shortcut, and `notfound` only from a deliberate
  bad `nav()`. Both need real entry points in the rebuild: `invite` from an email
  link, `notfound` from Nuxt's error handler.

Nuxt gives file-based routing for free. **The URL for every screen is therefore a
decision this spec has to make, not something that falls out of the port.**

### 5.2 URL table

| Route id | URL | Params | Guard |
|---|---|---|---|
| `landing` | identity `/` | — | public; redirect to `/products` if signed in |
| `signin` | `/login?next=` | `next` (return path) | public; redirect away if signed in |
| `forgot` | `/forgot-password` | — | public |
| `reset` | `/reset-password?token=` | **`token` query, required** | public; missing token → dead state |
| `invite` | `/invites/accept?token=` | **`token` query, required** | public; missing token → dead state |
| `products` | identity `/products` | — | auth |
| `account` | identity `/account` | — | auth |
| `pulse.home` | pulse `/` | — | auth |
| `pulse.activity` | pulse `/activity?user=&since=&repo=` | optional query | auth |
| `pulse.reports` | pulse `/reports?scope=&status=&repo=&page=` | optional query | auth |
| `pulse.report` | pulse `/reports/:id` | **`id` path param** | auth |
| `pulse.newreport` | pulse `/reports/new?repo=&week=` | optional query | auth |
| `pulse.repos` | pulse `/repositories` (`?open=:id` for a row) | optional | auth |
| `pulse.sync` | pulse `/sync?github=` | `github` = OAuth outcome | auth; `Sync now` needs platform admin |
| `forge.home` | forge `/` | — | auth |
| `identity.people` | identity `/people` (`/people/:id` if a detail view is added) | — | auth + **platform admin** |
| `identity.org` | identity `/departments` and `/departments/:id` | `id` | auth; detail needs dept membership |
| `identity.access` | identity `/access?person=&cap=` | optional query | auth |
| `identity.sessions` | identity `/sessions` | — | auth + **platform admin** (stage 2) |
| `notfound` | any unmatched | — | either |

Filter and pagination state on Reports, Activity and Repositories **should live in
the query string**, not in `ref`s. The prototype could not do this; Nuxt can, and
"send me the link to my rejected reports" is a real request.

### 5.3 Guards

**The prototype has exactly one guard and no capability gating**, even though
Identity defines twelve distinct capabilities. `PUBLIC` in `router.tsx:81` lists
six routes; everything else needs a session, full stop. A signed-in engineer can
open `/sessions` and `/people` and see the whole workspace.

The real build needs three layers:

1. **`auth`** — already exists as `packages/ui/middleware/auth.ts`. Client-only
   (tokens are in `localStorage`, so a server-side decision bounces before
   hydration). Keep that behaviour.
2. **`platform-admin`** — new middleware reading `is_platform_admin` from
   `useAuth().user`. Applies to `/people`, `/sessions`, and gates the "Sync now"
   button on `/sync` and the create/delete department controls on
   `/departments`.
3. **`dept-admin`** — new middleware, per-department, reading the membership role
   from `/me`. Applies to the write controls inside `/departments/:id` and to the
   file/lead/deputy controls on `/repositories`.

Route-level capability requirements:

| Capability | Gates |
|---|---|
| `directory`, `deactivate` (platform admin) | route `/people` |
| — (see §4.19) | route `/sessions` |
| `dept_create`, `dept_head` (platform admin) | controls on `/departments` |
| `invite`, `place`, `role`, `dept_rename` (dept admin) | controls on `/departments/:id` |
| `repo_file` (dept admin or platform admin) | file / lead / deputy / tracking controls on `/repositories` |
| `report_decide` (`_can_approve`) | the decision box on `/reports` queue tab and `/reports/:id` |
| `report_read` (manager) | the department-wide filter on `/reports` |
| platform admin | "Sync now" on `/sync` |

**Client gating is cosmetic.** Every one of these is enforced server-side and the
UI must handle the 403 anyway. Gate to avoid offering a button that cannot work,
not as a security measure.

**`next=` handling.** The prototype's `pending` state ("Sign in required ·
continuing to Pulse · Reports") is a nice touch and should survive as a `next`
query param, with the destination named in words on the sign-in screen.

---

## 6. Shared components to build in `packages/ui`

All of these live in `chrome.tsx` today. They belong in
`packages/ui/components/` so all three apps get them at once.

| Component | What it must do |
|---|---|
| **`TopBar`** | Sticky, `bg-app/85 backdrop-blur-xl`, 56px. Logo + optional breadcrumb ("Meridian / Pulse"), optional primary nav with `aria-current="page"`, signed-in cluster (All products / avatar+name / Sign out) or signed-out cluster (Sign in / Get started). **Skip link first**, `sr-only` until focused — and the header must be the positioned ancestor, or `sr-only`'s `position:absolute` anchors to the page and widens it. |
| **`TickRuler` / `RulerStrip`** | The graticule under the top bar: hairline ticks, every 5th taller, every 10th taller still, so the eye reads a scale not a texture. `RulerStrip` adds a right-aligned mono readout that each screen sets (`11 reports`, `next run 9h 55m`, `user_id 1042 · 2 live`). `aria-hidden` on the ticks. |
| **`ProductShell`** | TopBar + RulerStrip + product sub-nav + `<main id="main">` + an empty live region. Sub-nav items per product are in `PRODUCT_NAV`; `NAV_ALIAS` maps `/reports/:id` and `/reports/new` back onto the Reports tab so the right item stays lit. The route-enter animation goes on `<main>` **only** — never on the bar or the ruler. |
| **`Btn`** | 4 variants (`primary` = `bg-ink text-app`; `secondary` = `ring-1 ring-inset ring-line-strong`; `ghost`; `destructive` = `text-bad ring-bad/30`), 3 sizes (sm/md/lg). Press feedback (`active:scale-[0.98]`) on **every** variant — inconsistent feedback reads as broken, not as restraint. `secondary` uses `ring-line-strong` not `ring-line`, because that ring is the button's only boundary and `line` is 1.64:1 against the page. Optional `arrow` slot and a `.btn-busy` class for in-flight work. |
| **`Select`** | A full listbox, **not** a native `<select>`. The native control brings its own chevron and font metrics and was the only element on the site that looked borrowed. Requirements: `role="combobox"` trigger with `aria-haspopup="listbox"`, `aria-controls`, `aria-expanded`, `aria-activedescendant`; focus **stays on the trigger**; `role="listbox"` + `role="option"` + `aria-selected`; keyboard Up/Down/Home/End/Enter/Space/Escape/Tab; click-outside close; `scrollIntoView({block:'nearest'})` on the active option; `data-overlay-open="true"` on the wrapper so a parent `Modal` yields Escape to it. |
| **`Modal`** | Real dialog behaviour. Focus moves in, is trapped, and is restored on close. Initial focus is the **first form field**, else the first control that is not `[data-modal-close]` — landing on × means the first keystroke goes nowhere. Escape closes, unless focus is inside an open listbox. Body scroll lock. **Focus restoration and the scroll lock are tied to the logical close, not the unmount** — waiting for the exit animation makes focus visibly lag the user's own decision. And the `onClose` handler must live in a ref: every call site passes an inline arrow, so depending on it re-ran the trap on each keystroke and dropped all but one character of typed input. |
| **`Toast`** | Bottom-centre, `role`-less node with the announcement routed through the shared live region. **Transition-based, not keyframe** — the node's identity is stable, so a second toast fired over the first must retarget from wherever it is; a keyframe would replay nothing. 3.6s auto-dismiss with an explicit dismiss button, 200ms exit. |
| **`Tabs` / `TabPanel`** | Real `role="tablist"` with roving tabindex (`tabIndex={on ? 0 : -1}`), Arrow/Home/End, and a **single sliding indicator** measured with `useLayoutEffect` + `ResizeObserver` and moved by CSS transition — so mashing tabs retargets from the live position instead of restarting a wipe from the destination's left edge. Only set `aria-controls` when a panel is actually in the document; a rail used purely as a filter has no panels. `TabPanel` takes a tab stop only when it holds nothing focusable of its own. |
| **`StatusDot`** | `tone: ok\|warn\|bad\|info\|muted` plus a **`quiet`** variant that colours the dot and leaves the label `ink-muted`. `quiet` is the default choice inside tables. |
| **`Eyebrow`** | `mono text-[11px] uppercase tracking-[0.08em] text-ink-faint`. The one place `ink-faint` is unambiguously correct. |
| **`Avatar`** | Initials in mono on `bg-surface` with a `ring-line-subtle`, `rounded-full`, sm/md. `aria-hidden` — the name is always beside it. |
| **`useReveal`** | IntersectionObserver entrance, fires once, unobserves on first intersection. **Landing page only.** A console screen whose data moves while someone is reading it is worse than one that never moves. |
| **`announce` / `useAnnounce`** | Writes into a live region that is **already in the document**. Screen readers routinely miss a region inserted with its message already inside. `ProductShell` mounts an empty one; anything outside the shell gets a lazily-created fallback with a *different* id so the two never collide. Clears first, then writes 60ms later, so the same message twice reads twice. |
| **`Icon` / `Mark` / `Cross` / `RuleTicks`** | 24px stroke icons at `strokeWidth 1.75`, all `aria-hidden`. `Mark` is the logo (a circle cut by its own bisector, in a ring frame — a rule, not a fill). `Cross` is the plate mark where hairlines meet. |

---

## 7. Motion

The prototype's rules, and they are short on purpose.

- **200ms route enter, on content only.** `.route-enter` (opacity + 4px rise) goes
  on `<main>`. The top bar and the ruler are the frame the content moves inside;
  if they re-animate on every navigation the page feels like it is rebuilding
  itself.
- **Exits are shorter than enters.** Modal: 200ms in, 150ms out. Toast: 250ms in,
  200ms out.
- **Modals, menus and toasts must all animate OUT.** Their absence — things
  appearing smoothly and then vanishing on a frame — was the single largest
  contributor to the site feeling dead. This is why `Modal` keeps the panel
  mounted past `open === false` for the length of the exit.
- **The tab indicator slides via `transition`, not a keyframe.** A keyframe
  restarts from the destination's left edge every time; a transition retargets
  from wherever the indicator currently is.
- **Section entrance.** `.sec` = 420ms `fadeUp`, staggered by section at
  0 / 40 / 80 / 120ms via inline `animationDelay`. **Row stagger is capped at 3**
  (`Math.min(i, 3) * 40ms`) — an uncapped stagger means the last row of a 40-row
  table arrives 1.6 seconds late.
- **Expand/collapse** uses `.sec-collapse`: a grid going `grid-template-rows: 0fr
  → 1fr` with the child doing the clipping. No height measurement, and it exits
  for free.
- **Reduced motion** is honoured globally: `prefers-reduced-motion: reduce` sets
  every animation and transition to 0.01ms. Every keyframe **ends on the resting
  state**, so turning motion off leaves the page whole rather than empty.

### Two traps that bit us

**(a) `animation-fill-mode: both` on a transform keyframe.**
With `both`, the final keyframe's `transform: none` is retained as an identity
matrix — which is still a transform, and a transform makes the element a
**stacking context** (and a containing block for `fixed` children) *forever*.
Every row-action dropdown in a table was trapped under whatever came after it in
the DOM and became unclickable. **Use `backwards`.** It still applies the
from-state before the animation starts, so there is no flash, and it lets the
property return to its natural value at the end. The keyframes already finish on
the resting state, so nothing looks different.

**(b) Never name a custom class `.collapse`.**
Tailwind owns it — it is `visibility: collapse`. The expand/collapse helper is
named `.sec-collapse` for exactly this reason. In Vue this trap is identical.

---

## 8. Known gaps and decisions the rebuild must resolve

### 8.1 `/me/sessions`, the `sid` claim and the extended `InvitePreview` are uncommitted

At time of writing, `git status` shows these as modified-not-committed in
`services/identity`:

```
app/routes/me.py            GET /me/sessions
app/schemas/auth.py         SessionResponse
app/schemas/departments.py  InvitePreview + invited_by_name, expires_at
app/security/jwt.py         the sid claim
app/services/auth.py        list_sessions()
app/services/invites.py
app/security/dependencies.py, app/security/__init__.py
app/config.py, .env.example
tests/test_me.py, tests/test_invites.py
```

**Do not start the Account or Invite screens until these are committed**, and
re-check them before you build — another session shares this tree.

`SessionResponse` is `{ session_id, started_at, last_used_at, rotations,
expires_at, is_revoked, is_current }`. `session_id` is a **digest** of the refresh
family id, so it names the row without handing back a value the database stores.

The **`sid` claim** was added to the access token so the service can derive
`is_current` — "is this the session I am reading this on". It is **additive and
backwards-compatible**: an older token simply has no `sid`, `TokenPayload.session_id`
returns `None`, and every session comes back with `is_current: false`. Nothing
breaks; the current-device badge just does not appear.

### 8.2 `refresh_tokens` has no user-agent and no IP column

So sessions cannot show device or location, on either the Account screen or the
Identity console. Both screens state this in plain text rather than guessing.
Keep the statement. If device/location is wanted, it is a migration plus a change
to token issuance — not a frontend task.

### 8.3 Email verification has no lifting mechanism

`users.email_verified` exists and `/me` returns it. Accepting an invite sets it
(opening the link proves you can read the mailbox). **Nothing else lifts it.**
Someone who signed up via `/auth/signup` stays unverified forever, and the People
screen has an "Unverified" filter that will therefore accumulate. There is no
"resend verification" endpoint. Either add one or drop the filter — do not ship a
filter for a state nobody can leave.

### 8.4 There is no audit log

The word "audit" appears in prototype marketing copy in **three places**:
- the landing hero paragraph — "one permission model, one audit trail";
- `TRUST[3]` on the landing page — "04 Audit trail";
- the same `TRUST` list reused on the sign-in screen.

And the Identity Sessions screen renders a `SECURITY_EVENTS` rail (login, key
rotation, revoke-all, token reuse) that has no backing table and no endpoint.

**Nothing of this exists.** Either build an audit log or cut all four. Shipping
the copy without the feature is the kind of thing that gets noticed in a security
review.

### 8.5 Report eligibility — the prototype and the shipped Vue genuinely disagree

| | Which repositories may I write a report about? |
|---|---|
| **API** (`_may_report_on` in `services/pulse/app/services/reports.py:71`) | Any repo you have **synced activity** in, or any repo at all if you are a platform admin. Department and lead are **not** checked. Unfiled repos are allowed. |
| **Shipped `NewReportForm.vue`** | Offers every repository from `useRepositories()`, and shows an **amber warning** when the chosen repo has no department and no lead and no deputy: "nobody can approve a report about it yet… you can still write one." |
| **Prototype `PulseNewReport.tsx`** | Offers only **tracked and filed** repositories (4 of 7 in the fixture) and lists the excluded three with the reason each is excluded. |

**Recommendation: match the shipped Vue.** The API allows it, the warning is
honest, and blocking the write means someone who has genuinely done work in an
unfiled repo cannot record it — which converts an admin's filing backlog into an
engineer's blocked week. Keep the prototype's *explanation* panel (it is better
copy) but as a warning next to an enabled option, not as an exclusion list.

**This is a product decision, not mine.** Flagging it because whichever way it
goes, the two implementations must stop disagreeing.

### 8.6 The duplicate-report constraint is per **person**

`uq_report_author_repo_week` = `(author_user_id, repo_id, week_start)`, defined in
`services/pulse/app/models/__init__.py:36` and migration `0003`. So it is **one
report per person per repo per week**, not one per repo per week. Somebody else's
report on the same repo and week is not in your way. The 409 message must say
this, or people will assume a colleague "took" their week.

### 8.7 Sync has no manual-vs-scheduled trigger column

`sync_runs` records no trigger. The prototype infers `scheduled` from an `02`
hour in `started_at` and calls everything else `manual`. That is a guess dressed
as a fact and it is wrong for any run that happens to start at 02:xx. Either add
the column or label it honestly.

### 8.8 Pulse uses GitHub OAuth on a personal account, not a GitHub App

There is **no installation id**, no org-wide install, and the sync reaches only
what that one person's scopes reach (`read:user, user:email, repo, read:org`).
`read:org` is what lets Pulse match GitHub logins back to identity users; without
it, commits arrive attributed to nobody. If the only connected account is
disconnected, the whole sync records an error rather than quietly doing nothing.
The copy on `/sync` already says all of this — keep it.

### 8.9 Fixtures, and the absence of a store

`data.ts` is a single 1087-line fixture module with no store behind it. Every
screen imports it directly and mutates local `useState` copies. Real state needs:

- a **query layer** — `@tanstack/vue-query` is already in all three apps; use it,
  with the same key conventions the shipped pages use (`["reports"]`,
  `["repositories"]`, …);
- **composables** for the cross-cutting reads: `useRepositories()` and
  `useTeammates()` already exist in Pulse; you will want `useDepartments()` and
  `usePeople()` in Identity;
- a **name-resolution helper**. The fixture's `personName(id)` and `repoLabel(id)`
  render `Unknown user (#1096)` and `repo_id 7 · unresolved` when an id does not
  resolve. **Keep that honesty** — never render a bare id as though it were a
  name, and never render a fabricated name. Pulse resolves names through
  `POST I /internal/users/profiles`.

### 8.10 Signing-key display

Several screens print `signing key 2393e58f · RS256` and a rotation history. The
kid is real and readable from `GET I /.well-known/jwks.json`; the rotation
timestamp and "previous kid" are fixture. Either read what JWKS actually
publishes or drop the rotation line.

---

## 9. Build order

Dependency-ordered. Each stage unblocks the next; do not start a stage before the
one above it is done.

**Stage 0 — decide.** Three questions block real work:
1. One token namespace or three (§3.1)?
2. Report eligibility: prototype or shipped Vue (§8.5)?
3. Sessions: own-sessions now, or wait for admin endpoints (§4.19)?

**Stage 1 — tokens.** Port §2.1 into `packages/ui` and wire it into all three
`tailwind.config.js`. Delete `.focus-ring`; add the `FOCUS` utility. Add the
Inter + JetBrains Mono faces. Verify `--ink-faint` is not used for data anywhere
you touch. *Nothing renders correctly before this.*

**Stage 2 — shared components.** In dependency order: `Icon`, `Eyebrow`,
`StatusDot`, `Avatar`, `Btn` → `Select`, `Modal`, `Toast`, `Tabs`/`TabPanel` →
`TickRuler`/`RulerStrip`, `TopBar` → `ProductShell`. Then `announce`/`useAnnounce`
and `useReveal`. Add the motion CSS from §7 as a layer stylesheet, with the
`backwards` and `.sec-collapse` notes as comments so the traps do not get
re-introduced.

**Stage 3 — shell, routing and guards.** `ProductShell` wired into each app's
`layouts/default.vue`. The URL table from §5.2. The `platform-admin` and
`dept-admin` middleware. `error.vue`. `next=` handling on `/login`.

**Stage 4 — auth.** `signin`, `forgot`, `reset`, `invite`. These are revisions of
working pages, so they are mostly a restyle plus the validation fix on the
create-account tab (§4.2). Doing them early gets the new design system exercised
against real endpoints before anything complicated depends on it.

**Stage 5 — the two screens that unblock everything else in Pulse.**
- **`pulse.repos`** first. Every report routing decision — which department a
  report belongs to, who can decide it, whether it reaches a queue at all — is
  set here. Nothing about the approval flow can be tested until repositories are
  filed and led.
- **`pulse.sync`** second. Every figure anywhere in Pulse was put there by a sync
  run. Activity counts, report drafting material, the "drafted from" evidence —
  all of it is zero until sync works, and a zero is indistinguishable from a quiet
  week.

**Stage 6 — the Pulse core.** `pulse.reports` → `pulse.report` →
`pulse.newreport` → `pulse.activity` → `pulse.home`. Reports before the detail
page because the queue is where the approval rule lives; `newreport` after both
because it depends on eligibility (§8.5) being settled.

**Stage 7 — Identity console.** `identity.org` → `identity.people` →
`identity.access`. Org first: it is the biggest revision (741 lines of working
`[id].vue`) and People's invite flow depends on departments existing.
`identity.access` is pure read and can slip.

**Stage 8 — the umbrella.** `products` → `account` → `landing`. `products`
depends on the token-namespace decision from Stage 0. `landing` is last because
it ships nothing functional and is the easiest thing to cut if time runs out.

**Stage 9 — Forge.** `forge.home`. Independent of everything above; can be done
in parallel by a second pair of hands if there is one.

**Stage 10 — `identity.sessions`,** in whichever of the two forms Stage 0 chose.

---

## Appendix — endpoint reference used by this document

Router prefixes verified against `app/main.py` and each `routes/*.py`.

**Identity (`:8001`)**
`POST /auth/register` · `POST /auth/signup` · `POST /auth/login` ·
`POST /auth/refresh` · `POST /auth/logout` · `POST /auth/logout-all` ·
`POST /auth/change-password` · `POST /auth/forgot-password` ·
`POST /auth/reset-password` · `GET /me` · `PATCH /me` · `GET /me/sessions` ·
`GET|POST /departments` · `GET|PATCH|DELETE /departments/{id}` ·
`PUT|DELETE /departments/{id}/head[/{user_id}]` ·
`GET|POST /departments/{id}/members` ·
`PATCH|DELETE /departments/{id}/members/{user_id}` ·
`GET|POST /departments/{id}/invites` · `DELETE /departments/{id}/invites/{invite_id}` ·
`GET|POST /departments/{dept_id}/teams` · `GET|PATCH|DELETE .../teams/{team_id}` ·
`PUT|DELETE .../teams/{team_id}/manager[/{user_id}]` ·
`GET .../teams/{team_id}/members` · `PUT|DELETE .../teams/{team_id}/members/{user_id}` ·
`GET /teams` · `GET /platform/users` · `POST /platform/users/{id}/deactivate` ·
`POST /platform/users/{id}/reactivate` · `DELETE /platform/users/{id}` ·
`GET /platform/admins` · `PUT|DELETE /platform/admins/{user_id}` ·
`GET /invites/preview?token=` · `POST /invites/accept` ·
`GET /.well-known/jwks.json` · `POST /oauth/token` ·
`POST /internal/users/{emails,profiles,token-versions}`

**Pulse (`:8002`)**
`POST /reports` · `POST /reports/generate` · `GET /reports` ·
`GET /reports/review-queue` · `GET|PATCH|DELETE /reports/{id}` ·
`GET /reports/{id}/pdf` · `POST /reports/{id}/submit` ·
`POST /reports/{id}/{approve,reject,request-changes}` ·
`GET /reports/{id}/approvals` · `GET|POST /reports/{id}/comments` ·
`PATCH|DELETE /reports/{id}/comments/{comment_id}` ·
`GET /github/connect` · `GET /github/oauth/callback` ·
`GET|DELETE /github/account` · `POST /github/sync` · `GET /github/sync-runs` ·
`GET /github/repositories` · `GET /github/repositories/unfiled` ·
`PUT /github/repositories/department/{dept_id}` ·
`GET /github/repositories/{repo_id}` ·
`PUT /github/repositories/{repo_id}/department/{dept_id}` ·
`PUT|DELETE /github/repositories/{repo_id}/tracked` ·
`GET /github/repositories/{repo_id}/approver-candidates` ·
`PUT|DELETE /github/repositories/{repo_id}/lead[/{user_id}]` ·
`PUT|DELETE /github/repositories/{repo_id}/deputy[/{user_id}]` ·
`GET /activity/me` · `GET /activity/{user_id}` · `GET /admin/llm-usage`

**Forge (`:8003`)**
`POST /datasets` · `GET /datasets` · `GET /datasets/summary` ·
`GET /datasets/{id}` · `GET /datasets/{id}/preview` · `DELETE /datasets/{id}`
</content>
</invoke>
