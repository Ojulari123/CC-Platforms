# Runbook: rotating identity's JWT signing key

**Applies to:** `services/identity` · **Script:** `scripts/rotate-identity-keys.sh`
**Read this if:** you are replacing the RSA keypair identity signs JWTs with.

Identity signs every access and service token with one RSA private key. Pulse and
Forge verify those tokens locally against the public keys identity publishes at
`/.well-known/jwks.json`; they never call identity to check a token. So the whole
risk of a rotation is a window where a token is signed by a key the verifier has
not seen yet.

The phased procedure below closes that window. Each phase leaves the system fully
working, so **you can stop after any phase and go to bed.**

---

## The one thing that surprises people

**Identity reads each key file once per process and never again.** Every function
in `app/security/keys.py` that touches disk is `@lru_cache`d, and nothing
invalidates those caches at runtime (`reset_key_cache()` exists for tests only).
Editing files in `keys/` does nothing at all until identity restarts.

The retired directory is pinned earliest: `validate_retired_public_keys()` reads
and validates all of it during startup, so the retired set a process serves is the
set it validated. A file that goes bad later cannot take `/.well-known/jwks.json`
down mid-flight, and that endpoint failing would break token verification across
every service at once. (The active keypair is cached on first use rather than at
startup, which makes no operational difference: it is used within the first
request.)

**Consequence: every phase below ends with "restart identity". It is not optional.**

---

## Directory layout

```
services/identity/keys/
├── private.pem              the ACTIVE signing key
├── public.pem               the ACTIVE public key
├── next/                    phase 1 only — the prepared keypair, not signing yet
│   ├── private.pem
│   ├── public.pem
│   ├── PREPARED_AT          epoch seconds, drives the promote wait
│   └── STAMP
├── retired/                 PUBLISHED at /.well-known/jwks.json, never signed with
│   ├── public-<stamp>.pem   a superseded key, kept until its tokens expire
│   └── next-<stamp>.pem     a PRE-published key that is not active yet (phase 1)
└── archive/                 NOT published — private key material
    ├── private-<stamp>.pem  the previous private key, kept only for rollback
    └── promoted-<stamp>.at  epoch seconds, drives the finish wait
```

`retired/` is overloaded and it matters: **every `*.pem` in it is published**,
whether it is a superseded key (`public-*`) or a key that is not active yet
(`next-*`). Both are verification-only. Only `keys/private.pem` ever signs.

`archive/` holds a private key. It sits `600` inside a `700` directory on the same
host as the live private key, so it is behind the same boundary and adds no new way
in, but it only exists between `promote` and `finish`. `rotate-now` never creates
it.

The phase is derived from what is on disk, not from a state file, so `status` is
always truthful even after an interrupted run.

---

## Procedure A: planned rotation (use this by default)

Three phases. Total wall-clock: about 35 minutes, almost all of it waiting.

```
prepare → restart → wait 60s → promote → restart → wait 30 min → finish → restart
```

### Phase 1: prepare (publish the new public key; old key still signs)

1. `scripts/rotate-identity-keys.sh status`, then confirm `Phase: IDLE`.
2. `scripts/rotate-identity-keys.sh prepare`
   Generates a 2048-bit RSA keypair into `keys/next/` and copies its **public**
   half to `keys/retired/next-<stamp>.pem`. The live keypair is untouched. If
   `openssl` fails, nothing has changed (the script is `set -e` and builds off to
   the side).
3. **Restart every identity instance.** Until you do, the new public key is not
   published.
4. Confirm with `curl -s http://<identity>/.well-known/jwks.json | jq '.keys[].kid'`.
   You should now see **two** kids.

**Why this phase exists:** downstream `JWKSClient` (`packages/core/crescent_core/jwks.py`)
refuses to re-fetch more often than once every 30 seconds, even when it sees an
unknown `kid`. If a key started signing the same instant it started being
published, tokens minted in that 30-second window could be rejected by a service
holding the older document. Publishing first removes the window.

**Safe to stop here.** Identity keeps signing with the old key; the extra published
key is inert because nothing signs with it. Cancel with
`scripts/rotate-identity-keys.sh abort` (then restart identity).

### Phase 2: promote (the new key starts signing)

5. Wait **60 seconds** after the last instance is back, twice the 30s downstream
   refresh floor, for slack.
6. `scripts/rotate-identity-keys.sh promote`
   Moves `next/` into place as the live keypair, copies the outgoing public key to
   `keys/retired/public-<stamp>.pem`, moves the outgoing **private** key to
   `keys/archive/private-<stamp>.pem`, and removes the now-redundant `next-*.pem`.
   Refuses if fewer than 60s have elapsed since `prepare`; `--force` overrides.
7. **Restart every identity instance.** Until you do it is still signing with the
   old key, which still works, so this is not urgent.

**Safe to stop here.** The cost of stopping is that identity publishes a key nobody
signs with.

> **Read the timer carefully.** The 60s is measured from when `prepare` *ran*
> (`next/PREPARED_AT`), not from when identity restarted, despite what the
> `status` output says. If your restart took longer than 60s, the script will let
> you promote immediately. Do the restart first, then start counting yourself.

### Phase 3: finish (stop publishing the old key, destroy its private half)

8. Wait **30 minutes** after the last instance restarted in step 7. Access tokens
   live `ACCESS_TOKEN_EXPIRE_MINUTES` (15 by default); one minted a second before
   the restart is good for another 15 minutes and needs the old public key to
   verify. 30 minutes is that plus slack for a staggered restart and clock drift.
9. `scripts/rotate-identity-keys.sh finish`
   Deletes `retired/public-<stamp>.pem` and the archived private key. Refuses
   inside the 30 minutes; `--force` overrides and **will log out anyone still
   holding a token signed by the old key.**
10. **Restart every identity instance** so it stops publishing the retired key.
11. `scripts/rotate-identity-keys.sh status`, expecting `Phase: IDLE`, 0 retired keys.

> Same caveat as phase 2: the 30 minutes is measured from when `promote` ran
> (`archive/promoted-<stamp>.at`), not from your restart.

---

## Procedure B: suspected compromise (`rotate-now`)

Use when the private key may be known to someone else. Cutting the old key out now
is worth some rejected tokens.

1. `scripts/rotate-identity-keys.sh rotate-now`
   Generates a new keypair, makes it live immediately, copies the outgoing public
   key to `keys/retired/public-<stamp>.pem`, and **overwrites the old private key.
   It is never archived, so there is no rollback.**
2. **Restart identity immediately.**
3. Expect tokens minted in the first ~30s after the restart to be rejected by
   services still holding the previous JWKS document. That is the cost of the
   single-phase path.
4. Leave the retired public key in place for at least 30 minutes after the last
   restart, then delete it and restart again.

If the concern is a *leaked user session* rather than the signing key, this is the
wrong tool. Use identity's logout-all / `revoke_all_for_user`, which bumps
`token_version`.

---

## Undoing things

| Situation | Command | Possible when |
|---|---|---|
| Prepared a rotation you no longer want | `abort` | phase `PREPARED` only |
| Promoted a key that turns out to be wrong | `rollback` | phase `PROMOTED`, i.e. before `finish` |
| After `finish` | — | not possible; the private key is gone |

`rollback` swaps the previous keypair back in and retires the rolled-back key the
same way any superseded key is retired: it has already signed tokens that are
still in circulation, so it stays published. You then restart, wait 30 minutes, and
run `finish` to retire the bad key for good.

Both leave the system working. Restart identity after either.

---

## Pruning retired keys

Retired public keys are only needed until the last token they signed expires
(minutes), but nothing deletes them automatically. Every one is read at boot and
served on every JWKS fetch.

**Pruning is an operator command, never something identity does on a timer.** A
service that deletes its own key material turns a paused deploy or a clock skew
into "everyone is logged out", a worse failure than a slowly growing directory.

```bash
scripts/rotate-identity-keys.sh prune                      # lists, deletes nothing
scripts/rotate-identity-keys.sh prune --yes                # deletes, default 30 days
scripts/rotate-identity-keys.sh prune --older-than-days 7 --yes
```

- Refuses while a rotation is in flight unless you pass `--force`.
- Age is file mtime via `find -mtime +N`, so `N` means *strictly more than* N×24h;
  `--older-than-days 0` will not match a file created today.
- Restart identity afterwards.

**The nudge:** at **5 or more** retired keys, identity logs a warning at startup
and `status` says so. The threshold lives in two places that must stay in step:
`RETIRED_KEY_WARN_THRESHOLD` in `services/identity/app/security/keys.py` and the
same name in the script. Hitting it usually means someone has been skipping
`finish`.

---

## A malformed file in `retired/` refuses the boot

Identity will not start if any `*.pem` in the retired directory is not a usable RSA
**public** key. The error names the offending file:

```
Retired public key <path> is not a usable RSA public key (...).
Identity will not start: this file is published at /.well-known/jwks.json,
which every service uses to verify tokens. Remove it, or replace it with
the PEM public key it was meant to be.
```

This is on purpose. A failed deploy is loud and reversible; the alternatives are
worse:

- **Skipping the bad file** would silently stop publishing a key, and everyone
  holding a token signed by it is logged out with no signal anywhere.
- **Finding it at request time** would 500 `/.well-known/jwks.json` on a system
  that was already running, breaking authentication platform-wide.

A **private** key left in `retired/` also refuses the boot, which is the mistake
the phased script is built to avoid, caught anyway.

**Fix:** remove or replace the named file, then start identity. A missing retired
directory is fine and means "no retired keys": that is what every single-keypair
deployment looks like.

---

## Quick reference

| Command | Does | Wait enforced |
|---|---|---|
| `status` | Where this key directory is and what is next | — |
| `prepare` | Phase 1: build new keypair, publish its public half | — |
| `promote` | Phase 2: make the prepared key the signing key | 60s since `prepare` (`--force`) |
| `finish` | Phase 3: unpublish + destroy the previous key | 30 min since `promote` (`--force`) |
| `abort` | Cancel a prepared rotation | — |
| `rollback` | Undo a promote (before `finish`) | — |
| `prune` | Delete retired public keys older than N days | needs `--yes`; refuses mid-rotation |
| `rotate-now` | Single-phase rotation, no rollback | — |

The key directory defaults to `services/identity/keys`; override with a positional
argument or `$IDENTITY_KEYS_DIR`.

**If you just want to see what a command does, point it at a throwaway directory.
Never rehearse against a directory a running identity is using.**

```bash
mkdir -p /tmp/rehearse-keys
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out /tmp/rehearse-keys/private.pem
openssl rsa -pubout -in /tmp/rehearse-keys/private.pem -out /tmp/rehearse-keys/public.pem
scripts/rotate-identity-keys.sh status /tmp/rehearse-keys
```
