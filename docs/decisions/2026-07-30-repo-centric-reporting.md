# Repo-centric reporting: repos replace teams; each repo has a lead + deputy

**Date:** 2026-07-30 · **Status:** BUILT (Pulse migration `0003`, session 05)
**Context:** Week 3. Boss asked to reorganise reporting around GitHub repos
instead of teams. Supersedes Decision 6 in `2026-07-23-identity-structure.md`.
The design questions are resolved and tracked in `docs/questions.md`.

---

## The shape

```
Department              (identity — unchanged; each repo belongs to one)
└── Repository          (Pulse — synced from GitHub) — LEAD + DEPUTY, both approve
    └── Engineers       derived from who has activity in the repo (by user_id)
        └── Report      one per engineer, per repo, per week
```

Reporting is tied to the **repo**, not a team. Ada working in repo A and repo B
files **two** reports: one to A's lead/deputy, one to B's.

## Decisions

1. **The repo is the unit of work.** Engineers are grouped by the repos they work
   in; a report is about a repo. Teams no longer drive reporting/approval.
2. **Membership is derived from GitHub activity**: contributing (commits/PRs) is
   what puts you "on" a repo. No hand-maintained rosters. (May materialise a
   `repo_members` table later purely for speed/UX; not needed to start.)
3. **Repos belong to a department** (`repositories.dept_id`). A **department
   admin** sees every report across their department's repos.
4. **One report per (engineer, repo, week).** The report count scales with the
   number of repos a person touched that week.
5. **Every repo has a lead + a deputy, and BOTH approve** (co-approvers) who can
   approve / reject / request-changes. Rationale: there's no reliable way to
   detect a lead being "away" (no leave/presence system, out of scope), so
   co-approval means nothing stalls if one is out. Department admin and platform
   admin may also approve (override). Constraints: **lead ≠ deputy**; never
   silently leave a repo without either; one person may lead/deputise many repos.
6. **Assignment** of a repo's lead, deputy and department is done by a
   **department admin (of that dept) or a platform admin**, either one. Lead/deputy
   must hold the manager or admin role.
7. **No lead/deputy yet? Don't block.** Engineers may create **and submit**
   reports; they wait in `submitted` until a lead/deputy is assigned, at which
   point the backlog appears in that person's queue. Nothing is lost.
8. **Pulse owns all of this** (repo → lead / deputy / dept / membership),
   referencing identity by `user_id`. **Identity stays lean.** The token `leads`
   claim is no longer used for approval routing (Pulse reads its own tables).

## Visibility (read)

- engineer → their own reports
- repo lead / deputy → all reports for their repo(s)
- department admin → all reports across their department's repos
- platform admin → everything
- the plain `manager` role grants no dept-wide read on its own, only what the
  person actually leads/deputises

## Schema impact

- **Pulse `repositories`**: add `dept_id`, `lead_user_id`, `deputy_user_id`
  (all nullable until assigned; reference identity by id).
- **Pulse `reports`**: add `repo_id` (FK → repositories); **drop `team_id`**;
  weekly uniqueness becomes `(author_user_id, repo_id, week_start)`; keep
  `dept_id` (sourced from the repo's department). Approval = repo lead **or**
  deputy (or dept/platform admin).
- **Identity**: no change (teams left parked; see below).

---

## Repos replace teams, and how to retire teams later

The boss is set on **repos, not teams**. For now Identity's team model stays
**parked**: built, tested, and simply unused by Pulse's new flow. Smaller change,
fully reversible.

**If/when the user says "delete teams", this is exactly what that means** (so
there's no guessing):

- **Identity code:** remove the `Team` model + `teams` table; `Team.manager_user_id`;
  `memberships.team_id`; `invites.team_id`; `app/routes/teams.py` (incl.
  `flat_router`); `app/services/teams.py`; team schemas; the `require_team_manager`
  dependency; team assignment inside the invite flow; the `leads` claim in the
  access-token minting.
- **Shared core:** drop `leads` and `leads_team` from `crescent_core` claims.
- **Migrations:** a new Identity migration dropping `teams`, `memberships.team_id`,
  `invites.team_id`, and the `manager_user_id` FK. (Department `head_user_id`
  **stays**, since that's dept-level, unrelated to teams.)
- **Tests:** delete `test_teams.py`; adjust the membership/invite tests that
  reference a team.

This is a deliberate, sizeable removal. Perform it **only on an explicit
"delete teams"** instruction.
