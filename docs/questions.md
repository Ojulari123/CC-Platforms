# Questions & resolutions

Design questions raised during sessions, with how they were resolved. Grouped by
session. Session notes link here instead of carrying questions inline, so there's
one place to find every open/closed question.

**Status key:** ✅ resolved · ❓ open

---

## Session 05 (2026-07-30): repo-centric restructure

All resolved on 2026-07-30. Design recorded in
`docs/decisions/2026-07-30-repo-centric-reporting.md`.

1. ✅ **Repo membership: derived or assigned?**
   → **Derived from GitHub activity** (contributed to a repo → you report on it).
   May materialise a list later if speed/UX needs it.
2. ✅ **Do repos belong to a department?**
   → **Yes.** A department admin sees all reports across their department's repos.
3. ✅ **Who assigns a repo's lead + deputy?**
   → **Department admin or platform admin** (either). Lead/deputy must hold the
   manager or admin role.
4. ✅ **A repo with no lead/deputy yet: block reports?**
   → **No.** Engineers may create and submit; reports wait in `submitted` until a
   lead/deputy is assigned, then appear in that person's queue.

---

## Earlier sessions

Design questions from sessions 01–04 were tracked inline in the decisions docs
(see the "QUESTION FOR REVIEW" markers in
`docs/decisions/2026-07-23-identity-structure.md`, all since resolved). From
session 05 onward, questions live here.
