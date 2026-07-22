# CypherCrescent Platform — context & rules for Claude Code

## What we're building
An internal platform for CypherCrescent. Two separate products that share one login system:

1. **Pulse** (product 1) — Engineering Performance & Reporting. Pulls GitHub activity
   into weekly reports, adds AI-written summaries, and routes them through a manager
   approval flow.
2. **ML platform** (product 2, later) — a no-code environment for trying ML / LLM
   workflows without writing code first.

Built by one developer moving fast. The quality bar is dev-ready, not throwaway prototype.

---

## The three rules that must not be broken (and why)

### 1. One repo (monorepo). Worked on together, shipped separately.
Everything lives in a single repository. Shared code sits in one place, so fixing it once
updates every product at the same time — no copying a change into multiple repos and hoping
they stay in sync.

This does **not** mean the products are coupled: each service still builds, runs, and deploys
on its own. "One folder" is about how we *develop*, not how things *run*.

Why not separate repos: separate repos exist to give many teams hard walls and independent
release schedules. There is one developer here, so those walls only add busywork (version
bumps, dependency updates across repos) with no payoff.

### 2. Identity is its own service. No other service stores users.
There is exactly one login / identity service. It is the single source of truth for who a
person is and what they are allowed to do. Every product trusts the same login — one account,
one session, works everywhere.

Why: if each product kept its own users, they would drift apart and could never share a login.
Keeping identity separate is what lets both products (and future ones) sit on the same accounts.

### 3. Products own their own data and reference identity by ID.
Each product stores its own data (Pulse: reports, GitHub data; ML platform: datasets,
workflows) and refers to people and teams by their id (`user_id`, `team_id`, `org_id`) —
never by keeping its own copy of the user.

No service reads another service's database directly. If one product needs another's data,
it asks through that product's API using the shared login token.

Why: this is what keeps the products independently deployable instead of fusing into one
thing that can't be shipped separately.

---

## Repo layout (target)
```
crescent-platform/
├── packages/
│   ├── core/          # shared backend helpers (config, token checking, etc.)
│   └── ui/            # shared frontend components + login helpers
├── services/
│   ├── identity/      # the login / accounts / teams service
│   ├── pulse/         # product 1
│   └── ml-platform/   # product 2 (later)
├── docker-compose.yml # one dev environment for all services
└── .github/workflows/ # one CI
```
Each service gets its own database and its own container image.

## Working style
- Explain non-obvious decisions in plain language.
- Make small, reviewable changes.
- Ask before big structural moves or rewrites.
- Treat the three rules above as hard boundaries. If something tempts you to cross one
  (e.g. a product reading the identity database directly), stop and flag it instead of
  doing it quietly.

---

## Identity service — what it MUST do

I have login code from existing, dev-ready projects that I want to reuse to save time. This
section defines the **bar** the identity service has to meet — the behaviours, not a specific
implementation. When I hand you that existing login code, your job is to check it against this
bar (see "How to use my existing login code" below), not to rebuild from scratch by default.

The identity service **must**:

1. **Register and log in users**, storing passwords only in scrambled form using a strong,
   deliberately slow, modern password-hashing method — never plaintext, never a fast/weak hash.
   *(Goal: a stolen password database is impractical to crack.)*
2. **Hand out short-lived access tokens** (~10–15 min) that carry who the user is and what they
   can do — at minimum their id, their org/team, and their role.
   *(Goal: products can check permissions on their own without asking identity on every request,
   and a stolen token is useless within minutes.)*
3. **Hand out longer-lived refresh tokens that can be rotated and revoked**, so a login/session
   can be cut off immediately when needed.
   *(Goal: real "log this person out everywhere / kill this session" ability.)*
4. **Let other services verify a token is genuine without sharing the secret that creates tokens.**
   Publish the public means of verification; keep the token-signing key private inside identity.
   *(Goal: products verify tokens locally; the master key never leaves the identity service.)*
5. **Model organisations, teams, and memberships** — who belongs to which org and team, and with
   what role. Products reference these by id only.
6. **Support roles/permissions** the products can act on (e.g. manager vs engineer).
7. **Handle the unglamorous-but-critical flows**: token expiry, refresh, and logout/revoke.
   Password reset is expected. Two-step verification is a plus, not required now.

The identity service **must not**:
- Issue tokens that never expire.
- Rely on a single fixed shared secret that unlocks everything with no way to revoke.
- Store passwords in plaintext or with a weak/fast hash.
- Share the token-signing key with any product.

Optional tips (not requirements — any approach that meets the behaviours above is fine):
- Signing tokens with a private key while publishing a matching public key is the clean way
  to satisfy #4.
- argon2 or bcrypt are standard choices for #1.
- The specific token/JWT library matters far less than meeting the behaviours above.

## How to use my existing login code
When I give you login logic from another project:

1. Read it and map it against the "Identity service — what it MUST do" list above.
2. Give me a short **gap report**: what it already satisfies, what's missing or below the bar,
   and anything risky.
3. For each gap, ask whether you should **(a)** implement the fix or **(b)** leave it and record
   it as a known limitation — don't decide silently.
4. Reuse and adapt working logic rather than rewriting it. Only start fresh if the existing code
   is fundamentally short of these requirements.

Do not silently rewrite code that already meets the bar to match a preferred style, and do not
silently accept code that misses these requirements.
