#!/bin/bash
# Rotate the RSA keypair identity signs JWTs with, in PHASES, without signing
# anyone out and without a window where freshly minted tokens get rejected.
#
# Why phases. Downstream services verify tokens with the JWKS document they
# cached from identity, and packages/core's JWKSClient will not re-fetch more
# often than once every 30 seconds however many unknown key ids arrive. So if a
# key starts SIGNING at the same instant it starts being PUBLISHED, every token
# minted in the next ~30s can be rejected by a service that cached the document
# a moment earlier. Publishing the new public key first, waiting out that
# interval, and only then switching signing over closes that window.
#
#   prepare  -> restart identity -> wait -> promote -> restart identity
#            -> (>= 30 min later) finish
#
# Every phase leaves the system fully working. Stopping after any of them is
# safe: the only cost of stopping is that identity keeps signing with the old
# key (after prepare) or keeps publishing a key nobody signs with (after
# promote). Run `status` at any time to see where you are and what is next.
set -e

# packages/core/crescent_core/jwks.py: JWKSClient(min_refresh_interval_seconds=30).
# A downstream that has cached the pre-publication document can pick up the new
# key 30s after it first sees an unknown kid; we wait double that for slack.
DOWNSTREAM_REFRESH_SECONDS=30
PREPUBLISH_WAIT_SECONDS=$((DOWNSTREAM_REFRESH_SECONDS * 2))
# Access tokens live ACCESS_TOKEN_EXPIRE_MINUTES (15 by default). A token minted
# a second before the promote restart is good for another 15 minutes; the rest is
# slack for a staggered restart and clock drift.
RETIRE_WAIT_MINUTES=30
# More retired keys than this and someone has been skipping `finish`. Every one
# of them is read at boot and served on every JWKS fetch. Kept in step with
# RETIRED_KEY_WARN_THRESHOLD in services/identity/app/security/keys.py.
RETIRED_KEY_WARN_THRESHOLD=5
PRUNE_DEFAULT_DAYS=30

CMD="${1:-status}"
[ $# -gt 0 ] && shift
KEYS_DIR="${IDENTITY_KEYS_DIR:-services/identity/keys}"
case "${1:-}" in
  ""|--*) ;;
  *) KEYS_DIR="$1"; shift ;;
esac

NEXT_DIR="$KEYS_DIR/next"
RETIRED_DIR="$KEYS_DIR/retired"
ARCHIVE_DIR="$KEYS_DIR/archive"

usage() {
  cat <<EOF
Usage: scripts/rotate-identity-keys.sh <command> [keys-dir] [options]

  status      Where this key directory is in a rotation, and the next step.
  prepare     Phase 1. Build the new keypair and PUBLISH its public half. The
              old key keeps signing. Safe to stop here.
  promote     Phase 2. Make the prepared key the signing key. Refuses until
              ${PREPUBLISH_WAIT_SECONDS}s after prepare. Safe to stop here.
  finish      Phase 3. Stop publishing the previous public key and destroy the
              archived previous private key. Refuses for ${RETIRE_WAIT_MINUTES} minutes
              after promote (--force overrides).
  abort       Cancel a prepared rotation (phase 1 only). Restores the exact
              pre-rotation state.
  rollback    Undo a promote: put the previous keypair back as the signing key.
              Only possible while its private half is still archived, i.e.
              before finish.
  prune       Delete retired public keys older than N days (default ${PRUNE_DEFAULT_DAYS}).
              Lists them and does nothing without --yes.
  rotate-now  Single-phase rotation, the old behaviour: new key signs and is
              published at the same moment, and the old private key is destroyed
              immediately. Use for a suspected compromise, where cutting the old
              key out now is worth up to ${DOWNSTREAM_REFRESH_SECONDS}s of rejected fresh tokens.

Options: --force (skip a wait), --yes (confirm prune), --older-than-days N
Keys dir defaults to services/identity/keys, or \$IDENTITY_KEYS_DIR.
EOF
}

FORCE=0
CONFIRM=0
PRUNE_DAYS="$PRUNE_DEFAULT_DAYS"
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --yes) CONFIRM=1 ;;
    --older-than-days) PRUNE_DAYS="$2"; shift ;;
    *) echo "Unknown option: $1"; echo; usage; exit 1 ;;
  esac
  shift
done

now_epoch() { date -u +%s; }

# Second-resolution stamp, with a counter appended if this second already named a
# key file. Two operations inside one second (a promote you immediately roll back)
# would otherwise pick the same name and be refused as a clobber.
stamp() {
  local base st n=1
  base=$(date -u +%Y%m%dT%H%M%SZ)
  st="$base"
  while [ -e "$RETIRED_DIR/public-$st.pem" ] || [ -e "$RETIRED_DIR/next-$st.pem" ] || [ -e "$ARCHIVE_DIR/private-$st.pem" ]; do
    st="$base-$n"
    n=$((n + 1))
  done
  echo "$st"
}

# Seconds left of a wait. $1 is the file holding the epoch it started at, $2 the
# length. A missing or unreadable file (an interrupted phase) reports the whole
# wait rather than waving the operator through; --force is the way past it.
remaining_seconds() {
  local file="$1" required="$2" started elapsed
  started=$(cat "$file" 2>/dev/null || true)
  case "$started" in
    ''|*[!0-9]*) echo "$required"; return ;;
  esac
  elapsed=$(( $(now_epoch) - started ))
  if [ "$elapsed" -ge "$required" ]; then echo 0; else echo $(( required - elapsed )); fi
}

require_active_keypair() {
  if [ ! -f "$KEYS_DIR/private.pem" ] || [ ! -f "$KEYS_DIR/public.pem" ]; then
    echo "No keypair at $KEYS_DIR — nothing to rotate. Run scripts/generate-identity-keys.sh first."
    exit 1
  fi
}

# Phase is derived from what is on disk, not from a state file that could drift.
#   PREPARED = phase 1 done (next/ exists), PROMOTED = phase 2 done (archive/ has
#   a private key still awaiting finish), IDLE = no rotation in flight.
current_phase() {
  if [ -f "$NEXT_DIR/private.pem" ]; then echo PREPARED
  elif ls "$ARCHIVE_DIR"/private-*.pem >/dev/null 2>&1; then echo PROMOTED
  else echo IDLE
  fi
}

retired_count() {
  ls "$RETIRED_DIR"/*.pem 2>/dev/null | wc -l | tr -d ' '
}

# The stamp of the in-flight rotation's archived private key (phase PROMOTED).
promoted_stamp() {
  local f
  f=$(ls "$ARCHIVE_DIR"/private-*.pem 2>/dev/null | head -1)
  [ -n "$f" ] || return 1
  basename "$f" | sed 's/^private-//; s/\.pem$//'
}

cmd_status() {
  require_active_keypair
  local phase count
  phase=$(current_phase)
  count=$(retired_count)
  echo "Keys dir:  $KEYS_DIR"
  echo "Phase:     $phase"
  echo "Published: 1 active + $count retired public key(s)"
  if [ "$count" -ge "$RETIRED_KEY_WARN_THRESHOLD" ]; then
    echo "           ^ that is a lot. Every one is served on every JWKS fetch."
    echo "             Consider: scripts/rotate-identity-keys.sh prune $KEYS_DIR"
  fi
  echo
  case "$phase" in
    IDLE)
      echo "No rotation in flight. The active keypair is the only key identity signs with."
      echo "Next: scripts/rotate-identity-keys.sh prepare $KEYS_DIR"
      ;;
    PREPARED)
      local left
      left=$(remaining_seconds "$NEXT_DIR/PREPARED_AT" "$PREPUBLISH_WAIT_SECONDS")
      echo "A new keypair is prepared in $NEXT_DIR and its public half is already"
      echo "published. Identity is still signing with the OLD key — this state is stable,"
      echo "you can sit here indefinitely."
      if [ "$left" -gt 0 ]; then
        echo
        echo "Wait ${left}s more before promoting (downstream JWKS caches refresh at most"
        echo "once per ${DOWNSTREAM_REFRESH_SECONDS}s, measured from the LAST identity restart)."
      fi
      echo
      echo "Next: restart identity if you have not since prepare, then"
      echo "      scripts/rotate-identity-keys.sh promote $KEYS_DIR"
      echo "To cancel: scripts/rotate-identity-keys.sh abort $KEYS_DIR"
      ;;
    PROMOTED)
      local s left
      s=$(promoted_stamp)
      left=$(remaining_seconds "$ARCHIVE_DIR/promoted-$s.at" $((RETIRE_WAIT_MINUTES * 60)))
      echo "The new key is signing. The previous public key is still published as"
      echo "$RETIRED_DIR/public-$s.pem so tokens minted before the swap keep verifying,"
      echo "and its private half is still archived so a rollback is possible."
      if [ "$left" -gt 0 ]; then
        echo
        echo "$(( (left + 59) / 60 )) minute(s) left before finish will run without --force."
      fi
      echo
      echo "Next: scripts/rotate-identity-keys.sh finish $KEYS_DIR   (then restart identity)"
      echo "To undo: scripts/rotate-identity-keys.sh rollback $KEYS_DIR"
      ;;
  esac
}

cmd_prepare() {
  require_active_keypair
  local phase
  phase=$(current_phase)
  if [ "$phase" != "IDLE" ]; then
    echo "A rotation is already in flight (phase $phase) — refusing to start another."
    echo "Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi

  local st pub_published
  st=$(stamp)
  pub_published="$RETIRED_DIR/next-$st.pem"
  if [ -e "$NEXT_DIR" ] || [ -e "$pub_published" ]; then
    echo "$NEXT_DIR or $pub_published already exists — refusing to overwrite key material."
    exit 1
  fi

  mkdir -p "$NEXT_DIR" "$RETIRED_DIR"
  chmod 700 "$NEXT_DIR"
  # Built off to the side: if openssl fails, set -e stops here and neither the
  # live keypair nor the published document has been touched.
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$NEXT_DIR/private.pem"
  openssl rsa -pubout -in "$NEXT_DIR/private.pem" -out "$NEXT_DIR/public.pem"
  chmod 600 "$NEXT_DIR/private.pem"
  chmod 644 "$NEXT_DIR/public.pem"

  # Publishing the new PUBLIC key now is what makes phase 2 gapless. Nothing signs
  # with it yet; a published key with no tokens naming it is inert.
  cp "$NEXT_DIR/public.pem" "$pub_published"
  chmod 644 "$pub_published"
  now_epoch > "$NEXT_DIR/PREPARED_AT"
  echo "$st" > "$NEXT_DIR/STAMP"

  echo "Phase 1 of 3 done: new keypair prepared, its public half published."
  echo "  new keypair (not signing yet): $NEXT_DIR/{private,public}.pem"
  echo "  published for verification:    $pub_published"
  echo
  echo "Identity is still signing with the old key. THIS STATE IS SAFE TO LEAVE — every"
  echo "token in circulation verifies, and nothing has changed for users."
  echo
  echo "Next:"
  echo "  1. Restart every identity instance. Keys are read once per process, so a"
  echo "     running process does not publish the new key until it restarts."
  echo "  2. Wait ${PREPUBLISH_WAIT_SECONDS}s after the LAST instance is back, so downstream services"
  echo "     have had a chance to re-fetch (their floor is one fetch per ${DOWNSTREAM_REFRESH_SECONDS}s)."
  echo "  3. scripts/rotate-identity-keys.sh promote $KEYS_DIR"
}

cmd_promote() {
  require_active_keypair
  if [ "$(current_phase)" != "PREPARED" ]; then
    echo "Nothing prepared to promote. Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi

  local left
  left=$(remaining_seconds "$NEXT_DIR/PREPARED_AT" "$PREPUBLISH_WAIT_SECONDS")
  if [ "$left" -gt 0 ] && [ "$FORCE" -ne 1 ]; then
    echo "Too soon: ${left}s left of the ${PREPUBLISH_WAIT_SECONDS}s publication window."
    echo "Promoting now can get tokens rejected for up to ${DOWNSTREAM_REFRESH_SECONDS}s by services still"
    echo "holding the previous JWKS document. Wait, or pass --force if you know every"
    echo "consumer has already re-fetched."
    exit 1
  fi

  local st
  st=$(stamp)
  mkdir -p "$RETIRED_DIR" "$ARCHIVE_DIR"
  chmod 700 "$ARCHIVE_DIR"
  if [ -e "$RETIRED_DIR/public-$st.pem" ] || [ -e "$ARCHIVE_DIR/private-$st.pem" ]; then
    echo "$RETIRED_DIR/public-$st.pem or $ARCHIVE_DIR/private-$st.pem already exists — refusing to overwrite a retired key."
    exit 1
  fi

  # Order matters, and every intermediate state is safe to be interrupted in:
  # the old public is published before it stops being active, and the leftover
  # duplicate at step 4 is deduplicated by kid when the document is built.
  cp "$KEYS_DIR/public.pem" "$RETIRED_DIR/public-$st.pem"
  chmod 644 "$RETIRED_DIR/public-$st.pem"
  # Archived rather than destroyed: see the note above cmd_rollback.
  mv "$KEYS_DIR/private.pem" "$ARCHIVE_DIR/private-$st.pem"
  chmod 600 "$ARCHIVE_DIR/private-$st.pem"
  mv "$NEXT_DIR/public.pem" "$KEYS_DIR/public.pem"
  mv "$NEXT_DIR/private.pem" "$KEYS_DIR/private.pem"
  chmod 600 "$KEYS_DIR/private.pem"
  rm -f "$RETIRED_DIR/next-$(cat "$NEXT_DIR/STAMP").pem"
  now_epoch > "$ARCHIVE_DIR/promoted-$st.at"
  rm -rf "$NEXT_DIR"

  echo "Phase 2 of 3 done: the prepared key is now the signing key."
  echo "  signing keypair:   $KEYS_DIR/{private,public}.pem"
  echo "  previous public:   $RETIRED_DIR/public-$st.pem   (published, verification only)"
  echo "  previous private:  $ARCHIVE_DIR/private-$st.pem  (kept only until finish, for rollback)"
  echo
  echo "Next:"
  echo "  1. Restart every identity instance so it signs with the new key. Until then"
  echo "     it keeps signing with the old one — which still works, so this state is"
  echo "     safe to leave."
  echo "  2. At least ${RETIRE_WAIT_MINUTES} minutes after the LAST instance has restarted:"
  echo "     scripts/rotate-identity-keys.sh finish $KEYS_DIR"
  echo "If the new key turns out to be wrong: scripts/rotate-identity-keys.sh rollback $KEYS_DIR"
}

cmd_finish() {
  require_active_keypair
  if [ "$(current_phase)" != "PROMOTED" ]; then
    echo "Nothing to finish. Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi
  local st left
  st=$(promoted_stamp)
  left=$(remaining_seconds "$ARCHIVE_DIR/promoted-$st.at" $((RETIRE_WAIT_MINUTES * 60)))
  if [ "$left" -gt 0 ] && [ "$FORCE" -ne 1 ]; then
    echo "Too soon: $(( (left + 59) / 60 )) minute(s) left of the ${RETIRE_WAIT_MINUTES}-minute grace period."
    echo "Access tokens minted just before the promote restart are still valid and still"
    echo "need $RETIRED_DIR/public-$st.pem to verify. Finishing now logs those people out."
    echo "Wait, or pass --force if you accept that."
    exit 1
  fi

  rm -f "$RETIRED_DIR/public-$st.pem"
  rm -f "$ARCHIVE_DIR/private-$st.pem" "$ARCHIVE_DIR/promoted-$st.at"
  rmdir "$ARCHIVE_DIR" 2>/dev/null || true

  echo "Phase 3 of 3 done: rotation complete."
  echo "  stopped publishing: $RETIRED_DIR/public-$st.pem"
  echo "  destroyed:          the previous private key (rollback is no longer possible)"
  echo
  echo "Next: restart identity so it stops publishing the retired key."
}

cmd_abort() {
  if [ "$(current_phase)" != "PREPARED" ]; then
    echo "Nothing prepared to abort. Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi
  rm -f "$RETIRED_DIR/next-$(cat "$NEXT_DIR/STAMP").pem"
  rm -rf "$NEXT_DIR"
  echo "Prepared rotation cancelled. The key directory is back to its pre-prepare state."
  echo "Next: restart identity so it stops publishing the abandoned public key."
}

# Rollback exists because promote is the one step that can be wrong for a reason
# no script can check: the operator points identity at a key some part of the
# estate cannot use. The previous private key is kept, 600, in a 700 directory on
# the same host that already holds the live private key — so it is behind exactly
# the same boundary and adds no new way in — and only until finish. For a
# suspected compromise use `rotate-now`, which destroys the old private key on
# the spot and never archives it.
cmd_rollback() {
  require_active_keypair
  if [ "$(current_phase)" != "PROMOTED" ]; then
    echo "Nothing to roll back — the previous private key is only kept between promote and finish."
    echo "Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi
  local old new
  old=$(promoted_stamp)
  new=$(stamp)
  if [ -e "$RETIRED_DIR/public-$new.pem" ] || [ -e "$ARCHIVE_DIR/private-$new.pem" ]; then
    echo "$RETIRED_DIR/public-$new.pem or $ARCHIVE_DIR/private-$new.pem already exists — refusing to overwrite key material."
    exit 1
  fi

  # The key being rolled back has signed tokens that are still in circulation, so
  # it is retired the same way any superseded key is rather than deleted.
  cp "$KEYS_DIR/public.pem" "$RETIRED_DIR/public-$new.pem"
  chmod 644 "$RETIRED_DIR/public-$new.pem"
  mv "$KEYS_DIR/private.pem" "$ARCHIVE_DIR/private-$new.pem"
  chmod 600 "$ARCHIVE_DIR/private-$new.pem"
  now_epoch > "$ARCHIVE_DIR/promoted-$new.at"

  cp "$RETIRED_DIR/public-$old.pem" "$KEYS_DIR/public.pem"
  chmod 644 "$KEYS_DIR/public.pem"
  mv "$ARCHIVE_DIR/private-$old.pem" "$KEYS_DIR/private.pem"
  chmod 600 "$KEYS_DIR/private.pem"
  rm -f "$RETIRED_DIR/public-$old.pem" "$ARCHIVE_DIR/promoted-$old.at"

  echo "Rolled back: the previous keypair is the signing key again."
  echo "  signing keypair: $KEYS_DIR/{private,public}.pem"
  echo "  rolled-back key: $RETIRED_DIR/public-$new.pem (still published — it signed tokens"
  echo "                   that have not expired yet)"
  echo
  echo "Next:"
  echo "  1. Restart every identity instance."
  echo "  2. At least ${RETIRE_WAIT_MINUTES} minutes later: scripts/rotate-identity-keys.sh finish $KEYS_DIR"
}

# Retired keys are only needed until the last token they signed expires (minutes),
# but nothing deletes them, and every one is read at boot and served on every JWKS
# fetch. Pruning is a command rather than something identity does on a timer: the
# service deleting key material by itself turns a paused deploy or a clock skew
# into "everyone is logged out", and that is a worse failure than a directory that
# grows slowly. The default age is far past any token lifetime, so a prune inside
# it cannot log anyone out.
cmd_prune() {
  if [ ! -d "$RETIRED_DIR" ]; then
    echo "No retired keys at $RETIRED_DIR — nothing to prune."
    return
  fi
  local phase
  phase=$(current_phase)
  if [ "$phase" != "IDLE" ] && [ "$FORCE" -ne 1 ]; then
    echo "A rotation is in flight (phase $phase) — refusing to prune keys it may depend on."
    echo "Run finish or abort first, or pass --force."
    exit 1
  fi

  local victims
  victims=$(find "$RETIRED_DIR" -maxdepth 1 -name '*.pem' -mtime "+$PRUNE_DAYS" | sort)
  if [ -z "$victims" ]; then
    echo "Nothing in $RETIRED_DIR is older than $PRUNE_DAYS days. $(retired_count) key(s) kept."
    return
  fi
  echo "Retired public keys older than $PRUNE_DAYS days:"
  echo "$victims" | sed 's/^/  /'
  if [ "$CONFIRM" -ne 1 ]; then
    echo
    echo "Nothing deleted. Re-run with --yes to delete them, then restart identity."
    echo "Anyone still holding a token signed by one of these is logged out — at $PRUNE_DAYS days"
    echo "old that cannot happen, since access tokens live minutes."
    return
  fi
  echo "$victims" | while read -r f; do rm -f "$f"; done
  echo
  echo "Deleted. Next: restart identity so it stops publishing them."
}

# The old single-phase behaviour, kept for the case it is actually right for: the
# key may be known to someone else, so cutting it out now beats a clean handover.
cmd_rotate_now() {
  require_active_keypair
  if [ "$(current_phase)" != "IDLE" ]; then
    echo "A rotation is already in flight — finish or abort it first."
    echo "Run: scripts/rotate-identity-keys.sh status $KEYS_DIR"
    exit 1
  fi
  local st archived
  st=$(stamp)
  archived="$RETIRED_DIR/public-$st.pem"
  if [ -f "$archived" ]; then
    echo "$archived already exists — refusing to overwrite a retired key."
    exit 1
  fi
  mkdir -p "$RETIRED_DIR"

  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$KEYS_DIR/private.pem.new"
  openssl rsa -pubout -in "$KEYS_DIR/private.pem.new" -out "$KEYS_DIR/public.pem.new"
  chmod 600 "$KEYS_DIR/private.pem.new"

  cp "$KEYS_DIR/public.pem" "$archived"
  chmod 644 "$archived"

  mv "$KEYS_DIR/public.pem.new" "$KEYS_DIR/public.pem"
  # The old PRIVATE key is destroyed, not archived: you rotate this way because it
  # might be known to someone else, and keeping a copy defeats the point.
  mv "$KEYS_DIR/private.pem.new" "$KEYS_DIR/private.pem"

  echo "Rotated in one phase. New signing keypair at $KEYS_DIR/{private,public}.pem"
  echo "Previous public key retired to $archived; previous private key destroyed."
  echo
  echo "Tokens minted in the first ${DOWNSTREAM_REFRESH_SECONDS}s after the restart below may be rejected by"
  echo "services still holding the old JWKS document. That is the cost of the single-"
  echo "phase path; prepare/promote avoids it."
  echo
  echo "Next:"
  echo "  1. Restart identity. Keys are read once per process, so a running process"
  echo "     keeps signing and publishing the OLD key until it restarts."
  echo "  2. Leave $archived in place for at least ${RETIRE_WAIT_MINUTES} minutes after the LAST identity"
  echo "     instance has restarted, so tokens minted just before it keep verifying."
  echo "  3. After that, delete $archived and restart again to stop publishing it."
}

case "$CMD" in
  status) cmd_status ;;
  prepare) cmd_prepare ;;
  promote) cmd_promote ;;
  finish) cmd_finish ;;
  abort) cmd_abort ;;
  rollback) cmd_rollback ;;
  prune) cmd_prune ;;
  rotate-now) cmd_rotate_now ;;
  -h|--help|help) usage ;;
  *)
    if [ -d "$CMD" ]; then
      echo "This script now takes a command first: the old one-shot rotation is 'rotate-now'."
      echo "  scripts/rotate-identity-keys.sh status     $CMD"
      echo "  scripts/rotate-identity-keys.sh prepare    $CMD   # the no-outage path"
      echo "  scripts/rotate-identity-keys.sh rotate-now $CMD   # the old behaviour"
      exit 1
    fi
    echo "Unknown command: $CMD"
    echo
    usage
    exit 1
    ;;
esac
