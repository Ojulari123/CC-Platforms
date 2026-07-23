# Identity structure: departments, teams, roles, and who can sign up

**Date:** 2026-07-23 · **Status:** implemented, pending review
**Context:** Week 1–2 of the internship plan (identity service)

This records four decisions about how people, departments and teams are
modelled — and the four questions I'd like confirmed. Each decision is
reversible, but the longer we build on one the more it costs to change, so
they're worth a few minutes now.

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

## Decision 1 — Every department action names the department

`PATCH /departments/12`, not `PATCH /dept`.

**Why it changed.** The first version derived "your department" from your login,
so URLs were shorter. That silently broke as soon as anyone belonged to two
departments: the code picked whichever membership the database returned first.
In testing, a user who was **admin of his own department** and an **engineer in
another** got the second one — and was locked out of administering the
department he actually ran, with a 403 and no way to reach it.

Permission is now always checked against the department named in the URL, so
that class of bug can't occur.

**Cost:** the frontend passes a department id. It already has one from `/me`.

---

## Decision 2 — Platform administrators

A new `is_platform_admin` flag on a user account. Platform admins create
departments, can administer any department, and appoint other platform admins
(`PUT /platform/admins/{user_id}`).

**Why.** Nobody could create a second department — departments only appeared as
a side effect of someone registering. CypherCrescent couldn't actually set up
Engineering + Data + Finance. Somebody has to run the workspace, and a
department admin can't, by definition: their authority stops at their own
department.

Guard: the last platform admin can't be removed, so we can't lock ourselves out.

> **QUESTION FOR REVIEW:** Who should hold this? Right now it's whoever
> registered first (me, during development). In real use it's probably IT or an
> engineering lead. It's a small number of people — 2 or 3 — and it should
> probably not be the same person as every department admin.

---

## Decision 3 — One team per person, per department

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

**Each team has one named lead.** `Team.manager_user_id` — set by an admin, must
already be in the department and hold manager or admin. Appointing someone also
puts them on the team, and if they later leave the team or the department the
role is vacated rather than left pointing at someone who's gone.

This replaced an inferred rule (manager = "has the manager role and happens to
be assigned to this team"), which allowed a team to have none or several. Pulse
routes every weekly report to the engineer's team lead for approval, and that
flow needs exactly one answer.

> **QUESTION FOR REVIEW:** What happens when a lead is on leave? Right now
> approvals would wait for them, or a department admin steps in. If cover is
> needed routinely we'd add deputies — say so before Pulse's approval flow is
> built in week 4.

**Who can put people on a team.** Department admins, for any team — plus that
team's lead, for their own team only. The reasoning: the lead approves the
team's weekly reports, so they should own who's on it without routing every
change through an admin. Leads still can't create, rename or delete teams,
invite people into the department, or change anyone's role.

**Two ways to join a team.** An invite carries an optional team, so someone can
be hired straight onto Platform and land there on day one; the invite email and
the accept page both name the team. Otherwise they join the department
unassigned and an admin or their manager adds them afterwards.

---

## Decision 4 — Registration is bootstrap-only

The **first** registration creates the platform admin and the first department.
After that `POST /auth/register` returns 403 and everyone joins by invite
(`POST /departments/{id}/invites` → emailed link → `POST /invites/accept`).

**Why.** This is an internal tool. Open self-signup would let anyone with the
URL create an account, and — as it was originally built — a brand-new
department along with it. Departments were multiplying by accident during
testing. Invite-only also means an admin chooses your role and department, so
nobody self-assigns "manager", and we get email verification free: you proved
you control the address by opening the link.

> **QUESTION FOR REVIEW:** Is invite-only right, or should staff with a
> `@cyphercrescent.com` address be able to self-register and wait for approval?
> Invite-only is tighter and is what I've built; domain-based signup is more
> convenient at larger headcounts.

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
re-introduced exactly the bug from Decision 1 — invisibly, and inside a signed
token that other services trust.

---

## Summary for the reviewer

| # | Decision | Confirm? |
|---|---|---|
| 1 | Department id in the URL; role scoped per department | Mostly technical — no action needed |
| 2 | Platform admin flag + endpoint to appoint others | **Who holds it?** |
| 3 | One team per person per department | **Is this true here?** |
| 4 | Bootstrap-only registration, then invite-only | **Invite-only, or domain self-signup?** |

Also still open from earlier sessions: confirming **Brevo** as the email
provider and the sender address it sends from.
