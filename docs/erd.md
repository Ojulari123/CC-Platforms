# Entity-Relationship Diagram

**Scope:** the platform's database design, kept current with the code.

Three databases, because of the core rule *"products own their own data and
reference identity by id"* (see `CLAUDE.md`):

1. **Identity DB** — `services/identity`. **Built & migrated `0001`–`0010`.**
   People, departments, teams, memberships, sessions, invites, password resets,
   and (migration `0008`) **service clients** for service-to-service auth.
2. **Pulse DB** — `services/pulse`. **Built & migrated `0001`–`0006`.** Two
   domains: the **reporting** domain (reports, approvals, comments, plus the
   Week-4 `llm_usage` ledger) and the **GitHub sync** domain (connected accounts,
   repos, commits, PRs, reviews, issues, sync runs). Reporting is **repo-centric**
   (session 05): a report is about a repo, and each repo has a department, a lead,
   and a deputy. Week 4 (session 06) adds AI-drafted summaries — `reports` gains
   `generated_at` — and a token-usage ledger (`llm_usage`). Since then, `0005`
   dropped `commits.additions`/`deletions` (declared but never populated: GitHub's
   commit-list endpoint doesn't return line counts) and `0006` added
   `reports.prompt_version`.
3. **Forge DB** — `services/forge`. **Built & migrated `0001`–`0002`.** Product 2
   (no-code ML). One table so far: **datasets** (uploaded + bundled sample CSVs),
   with the CSV content stored in the row.

> **Cross-service references are by id, not foreign keys.** Pulse stores
> `author_user_id`, `dept_id`, `lead_user_id`, etc. as plain integers pointing at
> rows in the identity DB. **No database-level FK crosses the service boundary** —
> the two services have separate databases and deploy independently. Below, real
> (enforced) FKs are drawn as relationships; cross-service links are only noted in
> the column comments as "→ identity.X (by id)".

---

## Identity database

```mermaid
erDiagram
    users ||--o{ memberships : "belongs via"
    departments ||--o{ memberships : "scopes"
    teams ||--o{ memberships : "rosters (nullable)"
    departments ||--o{ teams : "contains"
    users ||--o{ refresh_tokens : "issues"
    users ||--o{ password_reset_tokens : "requests"
    departments ||--o{ invites : "into"
    teams ||--o{ invites : "optionally onto"
    users ||--o{ invites : "sent by"
    users |o--o{ teams : "leads (manager_user_id)"
    users |o--o{ departments : "heads (head_user_id)"

    users {
        int id PK
        string email UK "lowercased, indexed"
        string password_hash "bcrypt, <=72 bytes input"
        string first_name
        string last_name
        string avatar_url "nullable"
        bool is_active "default true"
        bool email_verified "default false"
        bool is_platform_admin "runs whole workspace"
        int token_version "bumped to kill all sessions"
        timestamptz onboarded_at "nullable, first department placement, never cleared"
        timestamptz created_at
        timestamptz updated_at
    }
    departments {
        int id PK
        string name
        string slug UK
        int head_user_id FK "->users, SET NULL, nullable"
        timestamptz created_at
        timestamptz updated_at
    }
    teams {
        int id PK
        int dept_id FK "->departments, CASCADE"
        string name
        string slug "unique per (dept_id, slug)"
        int manager_user_id FK "->users, SET NULL, nullable"
        timestamptz created_at
        timestamptz updated_at
    }
    memberships {
        int id PK
        int user_id FK "->users, CASCADE"
        int dept_id FK "->departments, CASCADE"
        int team_id FK "->teams, SET NULL, nullable"
        string role "admin | manager | engineer"
        timestamptz created_at
        timestamptz updated_at
    }
    refresh_tokens {
        int id PK
        string token_hash UK "sha256, raw never stored"
        int user_id FK "->users, CASCADE"
        string family_id "reuse nukes the family"
        timestamptz expires_at
        bool is_revoked "default false"
        string replaced_by "next token hash, nullable"
        timestamptz created_at
    }
    invites {
        int id PK
        int dept_id FK "->departments, CASCADE"
        string email
        string role "admin | manager | engineer"
        int team_id FK "->teams, SET NULL, nullable"
        string token_hash UK "sha256, raw only in email"
        int invited_by FK "->users, SET NULL, nullable"
        timestamptz expires_at
        timestamptz accepted_at "nullable; set on accept"
        timestamptz created_at
    }
    password_reset_tokens {
        int id PK
        int user_id FK "->users, CASCADE"
        string token_hash UK "sha256, raw only in email"
        timestamptz expires_at
        timestamptz used_at "nullable; single-use"
        timestamptz created_at
    }
    service_clients {
        int id PK
        string client_id UK "e.g. 'pulse', indexed"
        string client_secret_hash "bcrypt, raw never stored"
        string scopes "space-delimited, e.g. 'users:read:email'"
        bool is_active "default true; revocable without delete"
        timestamptz created_at
        timestamptz updated_at
    }
```

> **`service_clients` is standalone** (no relationship to `users`). It's a
> non-human caller — another service (Pulse) authenticating as itself via OAuth2
> client-credentials to mint a scoped service token. The `pulse` row is seeded on
> startup from `PULSE_CLIENT_SECRET`. Migration `0008`.

> **Teams are parked.** The boss's session-05 call is repos, not teams. The team
> model above is still built and tested but no longer drives Pulse reporting; it's
> retained, not deleted (see the "how to delete teams" runbook in
> `docs/decisions/2026-07-30-repo-centric-reporting.md`).

---

## Pulse database — GitHub sync domain

```mermaid
erDiagram
    repositories ||--o{ commits : "has"
    repositories ||--o{ pull_requests : "has"
    repositories ||--o{ issues : "has"
    repositories ||--o{ sync_runs : "logged against"
    pull_requests ||--o{ reviews : "reviewed by"

    github_accounts {
        int id PK
        int user_id UK "-> identity.users (by id); one per person"
        bigint github_user_id UK
        string github_login
        text access_token_encrypted "Fernet, never plaintext"
        string scopes "nullable"
        timestamptz connected_at
        timestamptz created_at
        timestamptz updated_at
    }
    repositories {
        int id PK
        bigint github_repo_id UK
        string full_name "owner/name, indexed"
        string owner
        string name
        bool private "default false"
        bool is_tracked "default true"
        string default_branch "nullable"
        timestamptz last_synced_at "nullable; incremental cursor"
        int dept_id "-> identity.departments (by id, nullable)"
        int lead_user_id "-> identity.users (by id, nullable)"
        int deputy_user_id "-> identity.users (by id, nullable)"
        timestamptz created_at
        timestamptz updated_at
    }
    commits {
        int id PK
        int repo_id FK "->repositories, CASCADE"
        string sha "unique per (repo_id, sha)"
        int author_user_id "-> identity.users (by id, nullable)"
        string author_github_login "nullable"
        text message "nullable"
        string url "nullable"
        timestamptz committed_at
        timestamptz created_at
    }
    pull_requests {
        int id PK
        int repo_id FK "->repositories, CASCADE"
        bigint github_pr_id UK
        int number "unique per (repo_id, number)"
        text title "nullable"
        string state "open | closed"
        bool merged "default false"
        int author_user_id "-> identity.users (by id, nullable)"
        string author_github_login "nullable"
        timestamptz gh_created_at "nullable"
        timestamptz gh_updated_at "nullable"
        timestamptz merged_at "nullable"
        string url "nullable"
        timestamptz created_at
    }
    reviews {
        int id PK
        int pull_request_id FK "->pull_requests, CASCADE"
        bigint github_review_id UK
        int reviewer_user_id "-> identity.users (by id, nullable)"
        string reviewer_github_login "nullable"
        string state "approved | changes_requested | commented | dismissed"
        timestamptz submitted_at "nullable"
        string url "nullable"
        timestamptz created_at
    }
    issues {
        int id PK
        int repo_id FK "->repositories, CASCADE"
        bigint github_issue_id UK
        int number "unique per (repo_id, number)"
        text title "nullable"
        string state "open | closed"
        int author_user_id "-> identity.users (by id, nullable)"
        string author_github_login "nullable"
        timestamptz gh_created_at "nullable"
        timestamptz closed_at "nullable"
        string url "nullable"
        timestamptz created_at
    }
    sync_runs {
        int id PK
        int repo_id FK "->repositories, CASCADE, nullable"
        string status "running | success | error"
        text detail "nullable"
        timestamptz started_at
        timestamptz finished_at "nullable"
    }
```

---

## Pulse database — reporting domain

```mermaid
erDiagram
    repositories ||--o{ reports : "reported on"
    reports ||--o{ approvals : "append-only history"
    reports ||--o{ comments : "flat, no threads"

    repositories {
        int id PK
        string full_name
        int dept_id "-> identity.departments (by id)"
        int lead_user_id "-> identity.users (by id) — approver"
        int deputy_user_id "-> identity.users (by id) — approver"
    }
    reports {
        int id PK
        int author_user_id "-> identity.users (by id)"
        int repo_id FK "->repositories, CASCADE"
        int dept_id "-> identity.departments (by id, nullable; from the repo)"
        date week_start "the Monday of the report week"
        string status "draft|submitted|changes_requested|approved|rejected"
        text summary_manager "AI-drafted, editable (Week 4)"
        text summary_exec "AI-drafted, editable (Week 4)"
        text next_week_goals "AI-drafted, editable (Week 4)"
        timestamptz generated_at "nullable; set when AI-drafted, null if hand-written (Week 4)"
        string prompt_version "nullable; PROMPT_VERSION at draft time, null if hand-written"
        timestamptz created_at
        timestamptz updated_at
    }
    llm_usage {
        int id PK
        int report_id "-> reports.id (by id, nullable; NOT an FK, survives report deletion)"
        int user_id "-> identity.users (by id); who triggered the generation"
        int tokens "total tokens for the generation call"
        timestamptz created_at
    }
    approvals {
        int id PK
        int report_id FK "->reports, CASCADE"
        int actor_user_id "-> identity.users (by id)"
        string action "submitted|approved|rejected|changes_requested"
        text note "nullable"
        timestamptz created_at "append-only; rows never updated"
    }
    comments {
        int id PK
        int report_id FK "->reports, CASCADE"
        int author_user_id "-> identity.users (by id)"
        text body
        timestamptz created_at
        timestamptz edited_at "nullable"
    }
```

**How reporting works (session-05 decisions):**

- A report is about a **repo**: **one report per (author, repo, week)** — the
  unique key `(author_user_id, repo_id, week_start)`. Working in two repos in a
  week means two reports.
- A repo belongs to a **department** and has a **lead + deputy**, both referenced
  by identity user id. **Both approve** its reports (co-approvers); a department
  admin or platform admin may also approve (override).
- **Read:** author → own · lead/deputy → their repo · department admin → the
  department · platform admin → all.
- Assigning a repo's dept/lead/deputy is done by a department admin (of that dept)
  or a platform admin; **lead ≠ deputy**. A repo with no lead/deputy yet still
  accepts reports (they wait in `submitted`).

---

## Forge database

Product 2 (no-code ML). One table so far. People are referenced by identity
`user_id` only — **no FK crosses into identity**.

```mermaid
erDiagram
    datasets {
        int id PK
        int owner_user_id "-> identity.users (by id, nullable; NULL for samples), indexed"
        bool is_sample "default false; samples are owner-less and visible to all"
        string name
        string original_filename "nullable"
        text content "the raw CSV text — stored in the row, not on disk"
        text columns "JSON-encoded list of header column names"
        int row_count "data rows, excluding the header"
        timestamptz created_at
        timestamptz updated_at
    }
```

> **`uq_sample_name` — partial unique index** on `name` WHERE `is_sample`
> (migration `0002`). Stops two workers booting at once from double-seeding a
> bundled sample; user uploads are excluded by the predicate, so duplicate private
> dataset names stay allowed. A caller sees their own datasets plus every sample and
> nothing else (enforced in `app/services/datasets.py`, not the schema).

---

## Constraints that matter (enforced)

**Identity:** `users.email` · `departments.slug` · `refresh_tokens.token_hash` ·
`invites.token_hash` · `password_reset_tokens.token_hash` · `service_clients.client_id`
all unique. `memberships (user_id, dept_id)` unique. `teams (dept_id, slug)` unique.
`manager_user_id` / `head_user_id` have no uniqueness (one person may lead many).

**Forge:** `datasets` has the **partial** unique index `uq_sample_name` (`name`
WHERE `is_sample`) — sample names are unique; user-upload names are not constrained.

**Pulse:** `repositories.github_repo_id`, `pull_requests.github_pr_id`,
`reviews.github_review_id`, `issues.github_issue_id`,
`github_accounts.user_id`, `github_accounts.github_user_id` all unique.
`commits (repo_id, sha)`, `pull_requests (repo_id, number)`,
`issues (repo_id, number)`, and `reports (author_user_id, repo_id, week_start)`
unique. `lead_user_id` / `deputy_user_id` have no uniqueness (one person may
lead/deputise many repos).

---

## Design decisions behind this schema

- Identity structure (departments, teams, roles, platform admins, one-team-per-
  person): `docs/decisions/2026-07-23-identity-structure.md`.
- Repo-centric reporting (repos replace teams; lead + deputy both approve):
  `docs/decisions/2026-07-30-repo-centric-reporting.md` — **supersedes** the
  team-based approval flow.
