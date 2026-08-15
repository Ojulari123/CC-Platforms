# identity frontend

The admin UI for accounts, departments and access. Nuxt 3 + TypeScript + Tailwind +
TanStack Query, on port **3002**.

```bash
npm install
npm run dev        # http://localhost:3002
npm run typecheck  # vue-tsc, strict — CI runs this
npm run build
```

Needs identity running on `http://localhost:8001`, and `http://localhost:3002` listed in
identity's `CORS_ORIGINS`.

## Why this exists

Every other admin action in the platform had a working endpoint and no way to reach it
without curl: creating a department, placing someone in one, changing a role, naming a
department head, inviting people, deactivating a leaver. This is that surface.

## What's here

| Page | Covers |
| --- | --- |
| `/` | Where you sit, plus departments left without a head |
| `/departments` | List, create, and your role in each |
| `/departments/[id]` | Rename, head, roster (search/filter/role/remove), invites, delete |
| `/users` | Every account: search, deactivate/reactivate, platform admin, hard delete |
| `/account` | Your own name, password, and sign-out-everywhere |

Login, `forgot-password`, `reset-password` and `invites/accept` come from `packages/ui`
and are not duplicated here.

## Three distinctions the UI is built to keep straight

These are separate things that all sound like "admin", and conflating them is the easiest
way to get permissions wrong:

- **Department head** (`departments.head_user_id`) — the one named person who runs a
  department. Naming one grants nothing by itself. Platform-admin only to set, and the API
  requires the person to already hold the `admin` role in that department.
- **`admin` role in a department** — can administer *that* department: place people,
  invite, change roles, file repositories in Pulse.
- **Platform admin** (`users.is_platform_admin`) — spans the whole workspace. The only
  role that can create departments or read the full people directory.

## Deliberate omissions

- **Teams.** Identity models them, but reporting hangs off repositories instead
  (`docs/decisions/2026-07-30-repo-centric-reporting.md`), so teams are parked and get no
  management UI. `team_id` is carried through where the API returns it and otherwise left
  alone.
- **Adding an existing account to a department** is platform-admin only, because searching
  every account is (`GET /platform/users`). A department admin invites by email instead,
  which is the designed path — and accepting the invite is also what proves the person owns
  that address.
- **Deletion** is offered only where the API allows it: a department with no members, and
  an account that was never onboarded. Everything else deactivates. When the API refuses,
  its reason is shown rather than a generic failure.
