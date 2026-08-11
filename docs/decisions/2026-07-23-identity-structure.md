# Identity structure: departments, teams, roles, and who can sign up

**Date:** 2026-07-23 · **Status:** implemented, pending review
**Context:** Week 1–2 of the internship plan (identity service)

This records five decisions about how people, departments and teams are
modelled, and the questions I'd like confirmed. Each decision is reversible,
but the longer we build on one the more it costs to change, so they're worth a
few minutes now.

---

## The shape we settled on

```
CypherCrescent (the company — not modelled; it's the whole system)
└── Department        Engineering, Data, Finance ...
    └── Team          Platform, Data Infra ...
        └── People    with a role: admin / manager / engineer
```

A person's role belongs to a **department**, not to them globally. The same
person can be an admin in Engineering and an engineer in Data.

---

## Decision 1: Every department action names the department

`PATCH /departments/12`, not `PATCH /dept`.

**Why it changed.** The first version derived "your department" from your login,
so URLs were shorter. That silently broke as soon as anyone belonged to two
departments: the code picked whichever membership the database returned first.
In testing, a user who was **admin of his own department** and an **engineer in
another** got the second one, and was locked out of administering the
department he actually ran, with a 403 and no way to reach it.

Permission is now always checked against the department named in the URL, so
that class of bug can't occur.

**Cost:** the frontend passes a department id. It already has one from `/me`.

---

## Decision 2: Platform administrators

A new `is_platform_admin` flag on a user account. Platform admins create
departments, can administer any department, and appoint other platform admins
(`PUT /platform/admins/{user_id}`).

**Why.** Nobody could create a second department: departments only appeared as
a side effect of someone registering. CypherCrescent couldn't actually set up
Engineering + Data + Finance. Somebody has to run the workspace, and a
department admin can't, by definition: their authority stops at their own
department.

Guard: the last platform admin can't be removed, so we can't lock ourselves out.

> **QUESTION FOR REVIEW:** Who should hold this? Right now it's whoever
> registered first (me, during development). In real use it's probably IT or an
> engineering lead. It's a small number of people (2 or 3), and it should
> probably not be the same person as every department admin.

---

## Decision 3: One team per person, per department

A person's team is a single field on their department membership.

**Why.** A weekly Pulse report then has exactly one team and one approving
manager, with no tie to break. Allowing multiple teams means answering "which
manager approves this engineer's report?" before we can build the approval flow
in weeks 3–4.

> **QUESTION FOR REVIEW:** Is one team per person actually true at
> CypherCrescent? If people routinely split across teams, we should change this
> now rather than after reports are built on top of it. Changing later means a
> new join table, a data migration, and re-deciding how report approval works.
> Changing now is about half a day.

**Each team has one named lead.** `Team.manager_user_id`, appointed by an
admin via `PUT /departments/{d}/teams/{t}/manager/{user}`. They must be in the
department and hold manager or admin.

This replaced an inferred rule (manager = "has the manager role and happens to
be assigned to this team"), which allowed a team to have none or several. Pulse
routes every weekly report to the engineer's team lead for approval, and that
flow needs exactly one answer.

**Leading a team is separate from being on it.** The first version forced a
lead onto the team they led, which (combined with one-team-per-person) meant
appointing someone to a second team silently moved them and left the first team
pointing at a lead who was no longer on it. Rather than patch that, leading and
being rostered are now independent facts. Appointing moves nobody, so the
problem cannot occur.

> **Contingency, if you say a manager may run several teams:** this already
> works. `manager_user_id` is an ordinary column with no uniqueness constraint,
> so one person can lead Alpha and Beta today and manage both rosters. Zero
> migration, zero code change; it's covered by tests. The only thing that ever
> blocked it was the coupling described above, which is gone.

> **QUESTION FOR REVIEW:** What happens when a lead is on leave? Right now
> approvals would wait for them, or a department admin steps in. If cover is
> needed routinely we'd add deputies, so say so before Pulse's approval flow is
> built in week 4.
>
> **ANSWERED 2026-08-08: deputies were built.** Cover is permanent, not
> occasional: every Pulse repository carries a **lead and a deputy** and both can
> approve, so nothing stalls when one is away. There is no leave/presence system
> to detect "away" with, so co-approval replaced the fallback rather than adding
> to it. Note this landed on the **repo**, not the team; see
> `2026-07-30-repo-centric-reporting.md`.

**Who can put people on a team.** Department admins, for any team, plus that
team's lead, for their own team only. The reasoning: the lead approves the
team's weekly reports, so they should own who's on it without routing every
change through an admin. Leads still can't create, rename or delete teams,
invite people into the department, or change anyone's role.

**Two ways to join a team.** An invite carries an optional team, so someone can
be hired straight onto Platform and land there on day one; the invite email and
the accept page both name the team. Otherwise they join the department
unassigned and an admin or their team's lead adds them afterwards.

**Nobody in charge disappears silently.** Removing a person who leads a team,
or heads the department, is refused with a clear message naming what would be
left with nobody running it. You then either name a successor
(`?replacement_user_id=`) or confirm you accept the gap (`?allow_unled=true`).
Ordinary members are removed with no friction. Without this, a team could end
up with nobody able to approve its weekly reports and nobody would notice for
weeks.

---

## Decision 4: Registration is bootstrap-only

> **STATUS 2026-08-08, partly superseded: domain self-signup shipped.** The open
> question at the end of this decision has been answered by what was built. There
> are now **three** doors, not two: bootstrap registration, invites, and
> `POST /auth/signup`, open self-signup gated by the `SIGNUP_ALLOWED_DOMAINS`
> allowlist, so only addresses at a listed domain may use it. (Blank means any
> domain, which is the wrong setting for production.)
>
> The two objections raised below are both handled rather than overruled: a
> self-signup lands with **no department and no membership** and is never a
> platform admin, so nobody self-assigns "manager" and no department is created by
> accident. They can log in but belong to nothing until an admin places them. What
> signup does *not* give us is the free email verification invites had: the
> allowlist proves the domain, not the mailbox.
>
> The reasoning below is left as written; it is why signup was built this narrowly.

The **first** registration creates the platform admin and the first department.
After that `POST /auth/register` returns 403 and everyone joins by invite
(`POST /departments/{id}/invites` → emailed link → `POST /invites/accept`).

**Why.** This is an internal tool. Open self-signup would let anyone with the
URL create an account, and (as it was originally built) a brand-new
department along with it. Departments were multiplying by accident during
testing. Invite-only also means an admin chooses your role and department, so
nobody self-assigns "manager", and we get email verification free: you proved
you control the address by opening the link.

> **QUESTION FOR REVIEW:** Is invite-only right, or should staff with a
> `@cyphercrescent.com` address be able to self-register and wait for approval?
> Invite-only is tighter and is what I've built; domain-based signup is more
> convenient at larger headcounts.
>
> **ANSWERED 2026-08-08: domain self-signup shipped.** See the status note at
> the top of this decision.

---

## Decision 5: Each department has one named head

`Department.head_user_id`, appointed by a platform admin via
`PUT /departments/{id}/head/{user_id}`.

**Why.** "Who runs Engineering?" previously had no answer in the data. There was
only the *set* of people holding `role: admin`, which can be empty or five
people. That's the same ambiguity we'd just fixed for teams, one level up. An
org chart needs one name, and Pulse will need one person to escalate to.

Three different things that were previously easy to confuse:

| | what it means | who sets it |
|---|---|---|
| `is_platform_admin` | runs the whole workspace, every department | another platform admin |
| `role: "admin"` | a *permission* inside one department | a department admin |
| `head_user_id` | the one named person who *runs* that department | a platform admin |

Only a platform admin can appoint a head: who runs a department is decided
from above it, not by the department itself. The head must already hold the
admin role there, so naming someone head never silently grants them power; you
promote them first, deliberately. Like a team lead, it's a title, not a team
assignment: nobody is moved.

> **QUESTION FOR REVIEW:** Should a department head be able to appoint their own
> successor, or must that always come from a platform admin? Currently the
> latter.

---

## A gap worth naming: what does `role: "manager"` actually do?

**Today, on its own: nothing.** I checked every place the role is read, and both
are eligibility gates: you must be manager-or-admin to *be appointed* a team
lead, or to be a handover replacement. Every actual power comes from being named
in `Team.manager_user_id`, not from the role.

So a "manager" who leads no team currently has exactly the same permissions as
an engineer. That's a reasonable starting point (the role is a job title plus
eligibility) but it should be a decision rather than an accident.

> **QUESTION FOR REVIEW:** When Pulse lands, should a department's managers see
> or approve anything beyond the team they lead, for example reading all reports
> in their department? If yes, the role starts carrying real permissions and we
> should say so before the approval flow is written.
>
> **ANSWERED 2026-08-08: no. The answer stayed "nothing".** Decision 6 below
> proposed giving `manager` a department-wide read, but it was superseded before
> it was built (see `2026-07-30-repo-centric-reporting.md`). Pulse gates every
> read and every approval on being the report's author, the repo's lead or
> deputy, `role: "admin"` in the department, or a platform admin. The plain
> `manager` role appears in none of those checks. So it remains a job title plus
> an eligibility gate: you must hold manager-or-admin to be *appointed* a repo
> lead or deputy, and the power comes from the appointment, not the role.

---

## Decision 6: Report visibility vs approval in Pulse (agreed session 04, not yet built)

> **STATUS 2026-08-08: SUPERSEDED, never built. Do not implement from this
> section.** A week after this was agreed, reporting was reorganised around
> **GitHub repositories instead of teams**, which replaced both halves of the
> model below. See `2026-07-30-repo-centric-reporting.md` for what actually
> shipped. The short version:
>
> - **Approval** is not the team lead. It's the **repo's lead *and* deputy**,
>   either of whom can decide, plus a department admin or platform admin as an
>   override. `Team.manager_user_id` no longer routes anything.
> - **Reading** does not widen by the `manager` role. The table below gives a
>   department `manager` read access to every report in the department; that was
>   dropped. In the shipped code the plain `manager` role grants **no** dept-wide
>   read on its own: you see your own reports, plus the repos you lead or
>   deputise. Department-wide read is `role: "admin"` only.
> - **Absent leads** are covered by the deputy co-approving, not by a department
>   admin stepping in as a fallback.
>
> Kept in place because it records what was considered and why the repo model had
> to replace it.

This answers the two questions left open above (what `role: "manager"` should
do, and what happens when a lead is away) now that the supervisor has weighed
in. It's enforced in **Pulse**, not identity; identity keeps modelling
who-leads-what, and Pulse reads that from the token to decide who-sees-what.

**Approving a report** is the job of the report's **team lead**, the one person
named in `Team.manager_user_id` for that engineer's team, and only for their own
team's reports. One report, one approver, no tie to break. *Confirmed: one team
per person is correct at CypherCrescent (Decision 3), so this holds.*

**Reading reports** widens by role:

| who | can read |
|---|---|
| engineer | their own reports |
| team lead (`Team.manager_user_id`) | their team's reports |
| department `manager` role | **every** report in the department, read-only |
| department `admin` / head | every report in the department |
| platform admin | everything, every department |

So `role: "manager"` finally carries a real permission, department-wide
visibility, **without** gaining approval power. Reading and approving are
deliberately separate: a manager can see how the whole department is doing, but
only the named team lead signs a report off.

**Absent leads:** no dedicated deputy yet. If a lead is on leave, a **department
admin** approves as the fallback. Add real deputies only if that turns out to be
routine; decide before the Week 4 approval flow if so.

---

## One consequence worth knowing about

Access tokens now carry **every** membership a person has, not one:

```json
"memberships": [
  {"dept_id": 1, "team_id": 3, "role": "admin"},
  {"dept_id": 2, "team_id": null, "role": "engineer"}
],
"is_platform_admin": false
```

Pulse and the ML platform read this to decide what someone may do, without
calling identity on every request. A single `dept_id` in the token would have
re-introduced exactly the bug from Decision 1, invisibly, and inside a signed
token that other services trust.

---

## Summary for the reviewer

| # | Decision | Confirm? |
|---|---|---|
| 1 | Department id in the URL; role scoped per department | Mostly technical; no action needed |
| 2 | Platform admin flag + endpoint to appoint others | **Who holds it?** |
| 3 | One team per person per department | ✅ Confirmed session 04: one team per person |
| 4 | Bootstrap-only registration, then invite-only | ✅ Answered 2026-08-08, **both**: domain self-signup shipped alongside invites, gated by `SIGNUP_ALLOWED_DOMAINS` |
| 5 | Each department has one named head | **Can a head name their successor?** |
| 6 | Pulse: `manager` reads all dept reports, team lead approves; admin covers absent leads | ⚠️ **SUPERSEDED 2026-08-08, never built**, replaced by repo lead + deputy co-approval; see `2026-07-30-repo-centric-reporting.md` |
| — | A manager may lead several teams | **Not needed yet, but already supported if you want it** |

Also still open from earlier sessions: confirming **Brevo** as the email
provider (it is sending for real now) and the sender address it sends from,
currently `noreply@cyphercrescent.com`.
