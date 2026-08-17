# What to build and sell — North America edition

**Status:** complete for Parts 1 and 2; Part 3 is complete on business mechanics and pricing, and
deliberately incomplete on the Canadian public-sector angle (see "What I could not verify").
Opinionated on purpose — it commits to a ranked recommendation.
**Date of research:** 2026-08-17. Non-obvious claims carry a source URL and the date it was read.
**Audience:** the developer deciding what to build next, and whether anyone will pay for it.
**Supersedes the geography of** `docs/product-strategy-research.md`. That brief concluded the play was
Nigerian oil-and-gas regulatory filing. Out of scope: the developer is in Canada and is selling into
North America.

---

## Executive summary

**The headline is uncomfortable and I am going to state it before the ranking: the
"ingest → artefact → approval → evidence" pattern is excellent engineering and a bad place to
compete, because it is the entire product category of Vanta and Drata, and they sell it to a
20–200 person company for $7,500–$15,000 a year with a hundred other controls attached.** Of the
eight ideas researched here (the prior brief's flagship plus seven others), **six are dead on
contact**, one is conditional on a customer conversation that has not happened, and one is worth
building. Nothing in the SOC 2 orbit is a clean solo win.

**Part 1's idea — "Evidence", GitHub history as SOC 2 CC8.1 records — is dead. Do not build it.**
Its premise is factually wrong and its niche is already free:
- GitHub Enterprise Cloud retains audit logs for **180 days, not 90** — and pull requests, reviews
  and approvals (the data CC8.1 actually needs) have **no documented expiry at all**. The retention
  problem the product was to be sold on mostly does not exist.
- **Vanta already ships it**, evaluating each merged PR for approval-by-someone-other-than-the-author,
  with documented justification for exceptions, and **retains history for 13 months** — deliberately
  one month past a 12-month audit window.
- **EvidentTrail already sells the exact feature list**, on the GitHub Marketplace, **for free** during
  early access.

### Ranked recommendation

1. **Employee offboarding evidence — "prove every access was actually revoked when someone left."**
   The only candidate where this codebase has a real, already-written head start:
   `services/pulse/app/services/leavers.py` is a working deprovisioning engine that is safe under
   partial identity-service failure, which is the part most teams get wrong. The problem is
   documented and concrete (a former Cash App employee reached data on 8.2 million customers months
   after termination), and the compliance requirement is explicit across SOC 2/ISO 27001/HIPAA/NIST.
   Crucially, **this is the one candidate with a published price to aim at**: Nudge Security charges
   **$750/month ($9,000/yr) for up to 150 users**, or $5/user/month above that, all features included
   — a primary-source rate card, and a budget line that sits outside compliance-platform spend.
   Scope to six connectors (Google Workspace, Microsoft 365, Okta, GitHub, AWS, Slack), not sixty.
   **Estimated 5–8 weeks.**
   **The catch, stated plainly:** Nudge and Reco already ship offboarding at that price, Reco
   advertises 225+ connectors, and Stitchflow already markets the audit-evidence framing
   ("provable for auditors: who ran what, when, and what changed"). **The surviving wedge is narrow
   and specific: Stitchflow's audit evidence has 90-day retention by default, against a twelve-month
   SOC 2 observation window.** Retention and immutability across a full audit period is the claim —
   which is, satisfyingly, the argument that turned out to be false for GitHub in Part 1 and true
   here. It is a real opening and a small one; a funded competitor can change a retention default in
   an afternoon. **This is the best of eight options, not a safe one.**

2. **Access certification / user access reviews — only for a vertical whose systems have no APIs.**
   It fits the existing identity and approval code almost perfectly, the market is real
   ($25k–$150k/yr mid-market), and the manual pain is genuine. **But the connectors are the product,
   not the workflow** — and the workflow half is exactly the half this platform has. Vanta bundles
   access reviews, claims 90% time reduction, and already supports CSV upload for non-integrated
   systems. Horizontally, unwinnable. The narrow version — credit unions, hospitals, municipalities
   running line-of-business software that will never have an API — may be winnable, but it needs a
   design partner before a line of code.

3. **Watch Ontario Bill 194 / EDSTA; do not build on it yet.** In force since 29 Jan 2025, with PIA
   and breach-notification duties from 1 Jul 2025, mandating cyber security programmes and AI-use
   regulation across Ontario ministries, agencies, police boards, transit commissions, school boards
   and children's aid societies. **The substantive obligations are still undefined pending
   regulations** — you cannot build against rules that do not exist. When they publish, this is a
   genuine Ontario opening that US vendors will not prioritise. Set a calendar reminder.

4. **Everything else: killed.** SaaS-licence/shadow-IT management (wrong shape, $2.50/employee/mo
   ceiling), vendor risk reviews (a ~$11.2k/yr Vanta add-on; the value is content, not workflow),
   ITIL/infrastructure change approvals (a standard ITSM module at ~$22/agent/mo), DR test evidence
   (annual — no subscription can survive that frequency), incident post-mortem/CAPA (mature category,
   wrong buyer), ISO 42001 (both suites already support it).

### One prerequisite that applies to every option

**There is no audit log.** `docs/meridian-frontend-spec.md` §8.4 says so plainly, while the landing
and sign-in copy already promise "one audit trail" and the Sessions screen renders a security-events
rail with no backing table. Every candidate in Part 2 is an *evidence* product whose central claim is
a record that cannot be altered after the fact. **Building an append-only, tamper-evident audit log
is a precondition, not a feature** — add 1–2 weeks to every estimate below, and fix the copy in the
meantime.

### The gate I would put on all of this

**Do not write code for #1 or #2 until one named person at one real company says the chore is theirs
and describes it unprompted.** The research can tell you which markets are occupied — it cannot tell
you which of offboarding or access review a specific IT manager will pay for, and the two candidates
are close enough that guessing is a coin flip with two months of work riding on it. Three weeks of
outreach is cheaper than eight weeks of the wrong build.

### The uncomfortable strategic read

The pattern this platform implements well is a **commodity in the SOC 2 market and a differentiator
nowhere it has been pointed yet.** If none of the above finds a buyer, the honest fallback is not a
fourth product — it is that **Pulse is the only finished thing here and finishing beats starting.**
A solo developer with one working product and two unfinished ones does not need a fifth idea.

---

## Part 1 — "Evidence": GitHub history as SOC 2 CC8.1 change-management records

### 1.1 The 90-day retention claim is WRONG

The prior brief's load-bearing fact — "GitHub retains audit logs for only 90 days" — does not survive
contact with GitHub's own documentation.

It was sourced from vendor blog posts (Strac, GitProtect), not from GitHub. GitHub Enterprise Cloud's
own docs say:

> "The audit log lists events triggered by activities that affect your enterprise within the last
> **180 days**." and "The audit log retains **Git events for seven days**."

([GitHub Docs — Audit log for an enterprise](https://docs.github.com/en/enterprise-cloud@latest/admin/concepts/security-and-compliance/audit-log-for-an-enterprise), read 2026-08-17)

Two corrections fall out of this:

1. **180 days, not 90.** The gap to a 12-month audit window is six months, not nine.
2. **Git events are 7 days**, which is a *worse* retention story than the brief claimed — but it is
   the wrong data anyway. Git events are raw pushes. CC8.1 evidence is **pull requests, reviews and
   approvals**, which live in the GitHub REST/GraphQL API as ordinary repository objects with **no
   documented expiry at all**. A PR merged three years ago is still fetchable.

That second point is the one that matters. **The retention problem the product was supposed to solve
largely does not exist for the data the control actually needs.** Anyone can page the pull-request
API back twelve months whenever they like — which is exactly what Pulse already does.

On GitHub Enterprise Server, retention is configurable and audit logs are retained indefinitely
unless an enterprise owner sets a different period
([GitHub Enterprise Server 3.17 docs](https://docs.github.com/en/enterprise-server@3.17/admin/concepts/security-and-compliance/audit-log-for-an-enterprise)).
Enterprise Cloud customers can also stream audit and Git events to external storage indefinitely
(same Enterprise Cloud doc: "You can stream audit and Git events data from GitHub to an external data
management system").

### 1.2 What auditors actually accept for CC8.1

The requirement is not exotic, and audit-side sources describe it consistently:

- Auditors "sample production deployments during the observation period and trace each one back to
  the originating PR," verifying the PR was not self-merged, that at least one other person approved,
  that CI passed, and that deployment followed approval
  ([soc2auditors.org — A Practical Guide to SOC 2 Change Management Controls](https://soc2auditors.org/insights/soc-2-change-management-controls/), read 2026-08-17).
- **Separation of author and approver is the core principle** — the writer of a change must not be
  its only approver ([AuditPath — SOC 2 Change Management: CC8.1 Requirements Explained](https://www.auditpath.io/blog/soc2-change-management)).
- Acceptable evidence per sampled change: the code diff, a linked ticket, reviewer approval, and
  passing CI checks before merge ([RiscLens — SOC 2 Evidence for Change Management](https://risclens.com/soc-2-evidence/change-management)).
- The auditor-side framing is that auditors value organised, verifiable proof over sophisticated
  tooling. There is no accreditation moat and no evidence format the incumbent tools fail to produce.

**This is a real control with a real annual chore attached.** The problem is who already does it.

### 1.3 The incumbents already do this, and do it well

This is where the idea dies. I checked the vendors' own help documentation, not their marketing.

**Vanta** ships two distinct pieces of exactly this product:

- An **Application Changes Reviewed test** that reads GitHub branch-protection settings on the
  production branch (configurable via a `vanta_production_branch_name` property) and passes only when
  "Require a pull request before merging" and "Require approvals" are enabled with a threshold of ≥1
  ([Vanta Help Center](https://help.vanta.com/en/articles/11345528-application-changes-reviewed-test-github), read 2026-08-17).
- A **Code Changes** feature that evaluates each merged pull request individually to confirm it was
  "approved by someone other than the author," or carries a documented justification for merging
  without approval, across all connected repos
  ([Vanta Help Center — Code Changes in Vanta](https://help.vanta.com/en/articles/12498226-code-changes-in-vanta), read 2026-08-17).

**And the retention wedge is already closed by the incumbent.** Vanta's own doc states:
"Historical changes are retained for **past 13 months**." Thirteen months is deliberately one month
more than a twelve-month audit window. Vanta solved the exact problem this product was to be sold on,
and sized the solution to the audit period.

**Drata** does the same: its GitHub integration "continuously validate[s] access control, code
review, and change management practices," automating evidence collection for SDLC controls and
capturing pull-request approval data as compliance evidence
([Drata Help Center — GitHub Integration Guide](https://help.drata.com/en/articles/4663377-github-integration-guide), read 2026-08-17).

So: **yes, they already ingest GitHub PR/review data and produce this evidence automatically, with
author-≠-approver logic, exception justification, and >12-month retention.** By the kill criterion
set for this research — "if they do it well, this idea is dead" — it is dead.

### 1.4 The point-tool slot is occupied *and* the product there is free

Two narrow competitors already sit in precisely this niche:

- **EvidentTrail** — automates SOC 2 and ISO 27001 change-management evidence from GitHub,
  generating "audit-ready evidence packs in 60 seconds," capturing PR reviews and approvals for
  CC8.1, branch-protection snapshots for ISO 27001 A.8.32, CI check results, exception tracking and
  drift detection, exportable as PDF/CSV/JSON with read-only auditor share links
  ([evidenttrail.com/features](https://evidenttrail.com/features); listed on the
  [GitHub Marketplace](https://github.com/marketplace/evidenttrail), read 2026-08-17).
  **It is free during Early Access**, with pricing "introduced later."
- **Audit Trail** ([audit-trail.net](https://www.audit-trail.net/)) — "compliance infrastructure for
  engineering teams," same slot.

That feature list is, item for item, the product the prior brief proposed building in 3–5 weeks. It
already exists, it is on the GitHub Marketplace, and **its price is currently zero.**

### 1.5 Pricing context — why the wedge has no money in it

Entry pricing for the compliance platforms this would have to displace or undercut:

| Vendor | Entry price (SOC 2, small company) | Top of range |
|---|---|---|
| Drata | $7,500–$15,000/yr (Foundation, single framework, <50 employees) | $100,000+/yr |
| Secureframe | ~$7,500–$20,000/yr (Fundamentals) | $80,000+/yr |
| Vanta | ~$10,000/yr (Core, SOC 2 only) | $80,000–$120,000+/yr |

(From [secureleap.tech Vanta pricing 2026](https://www.secureleap.tech/blog/vanta-review-pricing-top-alternatives-for-compliance-automation),
[secureleap.tech Secureframe pricing 2026](https://www.secureleap.tech/blog/secureframe-review-pricing-top-alternatives-for-compliance-automation),
and [cavanex.com 2026 comparison](https://cavanex.com/blog/soc-2-compliance-platforms-compared-2026), all read
2026-08-17. **None of these vendors publishes a rate card** — these are buyer-reported and aggregator
figures. Directional only.)

The arithmetic that kills it: a buyer already paying Vanta ~$10k/yr gets change-management evidence
included. Selling them a separate tool for the same control means pricing it as an impulse buy —
$50–$150/mo — against a competitor charging nothing. That is a business needing hundreds of customers
to pay one salary, in a market where the buyer's default answer is "it's already in Vanta."

### 1.6 Is there a wedge for a point tool at all? No — and the trend is against it

The brief asked specifically for evidence of buyers choosing point tools over suites in compliance.
**I looked and found the opposite, though the source quality here is poor and I want to be honest
about that.**

What I found: the 2026 commentary is uniformly consolidation-directional — "enterprise buyers
increasingly favor consolidated solutions over point-solution providers without differentiated
technology," organisations "managing compliance separately… using spreadsheets and point tools can
consolidate onto a GRC platform (Vanta, Drata, OneTrust) that maps evidence across multiple
frameworks simultaneously," and the driver is tool-sprawl fatigue rather than cost
([visioneerit.com](https://www.visioneerit.com/blog/cybersecurity-vendor-consolidation);
[cyberneurix.com](https://blogs.cyberneurix.com/blog/security-tool-consolidation-2026/), read 2026-08-17).

**Source health warning:** every result on this question was a vendor or MSP blog. There is no
analyst survey or procurement dataset behind any of it, and consolidation narratives are exactly what
platform vendors and their channel partners publish. **I found no counter-evidence of buyers
deliberately choosing compliance point tools — but I also found no rigorous evidence of the
consolidation claim.** What I would actually rest weight on is the harder structural fact: the
multi-framework evidence-mapping argument is real and mechanical. A buyer pursuing SOC 2 *and*
ISO 27001 gets each control mapped once across both inside a suite. A point tool covering one control
in one framework cannot offer that, at any price.

Combined with a free incumbent in the niche, that closes the question.

### 1.7 Verdict

**Kill it. Do not build Evidence.** The stated premise (90-day retention) is factually wrong, the
data it depends on has no expiry problem, the platform incumbents ship the feature with 13-month
retention, and the point-tool niche already has two entrants, one of them free.

---

## Part 2 — Other candidates

### 2.0a Reality check on the platform's assets — read before costing anything

Two things in this repo materially change the estimates below, and one of them is bad news.

**The good:** `services/pulse/app/services/leavers.py` is a real deprovisioning engine, and it is
careful in the way that matters. Its docstring names the failure mode it was written to avoid —
treating "identity didn't answer" as "everyone left" — and it preserves attribution on past work
after revoking the live credential. That is the hard, non-obvious half of an offboarding product,
already written and already tested.

**The bad, and it is load-bearing: there is no audit log.** `docs/meridian-frontend-spec.md` §8.4 is
blunt about it — the word "audit" appears in three places of marketing copy ("one permission model,
one audit trail"; a landing-page trust item; the same list on sign-in), the Sessions screen renders a
security-events rail "that has no backing table and no endpoint," and **"Nothing of this exists."**

Every product in Part 2 is an *evidence* product. Auditors want "immutable logs with timestamps,
digital signatures, and before/after system states that can't be modified retroactively" (Zluri, SOX
ITGC). **An append-only, tamper-evident audit log is therefore not a nice-to-have for any of these —
it is the product's core claim, and it is the single largest unbuilt dependency.** Add 1–2 weeks to
every build estimate in this section, and treat §8.4's warning as a prerequisite rather than a
backlog item.

**One more correction to an assumption in the brief.** The identity service's twelve-capability model
and the `/access` screen (spec §4.18) are about *this platform's own* permissions — who may approve a
report, file a repo, rename a department — computed read-only from token claims. They are a fine
access-*visibility* feature and **not a head start on access certification for a customer's estate**,
which is a different data model entirely. This is the concrete reason 2.1 ranks below 2.2.

### 2.0b The finding that governs everything below

I researched seven candidates. **Six of them are already inside Vanta or Drata for $7,500–$15,000/yr,
or owned by a mid-market specialist charging $25,000–$150,000/yr, or both.** That is not a coincidence
and it is the most important structural fact in this document:

> The compliance-automation platforms have spent five years absorbing exactly the
> "ingest → artefact → approval → evidence" pattern this platform is good at. That pattern is their
> entire product category. Building a point tool with that shape aimed at SOC 2 buyers means picking
> a fight on the incumbent's home ground, at a price they can bundle to zero.

So the filter I applied to every candidate is not "is the pain real" — the pain is real in all seven.
It is: **is there a buyer who is not already paying Vanta?** That question kills most of the list.

**Mid-market identity-governance pricing, for calibration:** Lumos, Zluri, ConductorOne and Opal
"typically land between $25,000 and $150,000 per year"; SMB-tier tools such as AccessOwl and
JumpCloud run "$4 to $15 per user per month"; Zluri specifically is reported at $4–$8/user/mo
([flamingo.run, 15 Access Request Management Tools 2026](https://www.flamingo.run/blog/access-request-management-system), read 2026-08-17
— **secondary source, no vendor rate card; ConductorOne, Lumos and Opal all gate pricing behind sales**).

---

### 2.1 User access reviews / access certification — the hypothesis to test hardest

**Verdict: real market, real money, genuinely the best fit for the code — and still the hardest of
these to win, for one specific reason. Worth pursuing only in the narrow form described at the end.**

**The need is unambiguous and well documented.**

- SOX has no statutory frequency, but "because public companies report financials quarterly, auditors
  expect access review frequency to match: quarterly, at minimum, for systems in SOX scope"
  ([Zluri, SOX User Access Review](https://www.zluri.com/blog/sox-user-access-review), read 2026-08-17).
- The manual reality: "IT teams run quarterly access reviews using exported spreadsheets, with
  managers approving access over email and the spreadsheet getting filed," and **"Excel files with
  manager email replies don't satisfy Big 4 auditors"** ([Zluri, SOX ITGC](https://www.zluri.com/blog/sox-itgc)).
- Quantified pain: one financial firm managing 200+ SaaS applications "reported spending over a week
  consolidating reports every quarter, totaling more than 30 days" (same source).
- What auditors demand: "immutable logs with timestamps, digital signatures, and before/after system
  states that can't be modified retroactively" (same source).

  *Source caution: Zluri sells access-review software. These are vendor-sourced pain statements, and
  the "30 days" figure is a single unnamed customer anecdote. I could not find an independent survey
  quantifying access-review effort. Treat the direction as sound and the numbers as marketing.*

**Why it fits the existing code better than anything else here.** The identity service already models
users, departments, teams, memberships and roles with a twelve-capability permission model; Pulse
already routes an artefact to a named approver and refuses self-approval; PDF and email already
exist. An access-review campaign is: snapshot the access list → fan it out to the right manager →
collect approve/revoke decisions → refuse self-attestation → freeze the record. **Structurally this
is Pulse with a different noun.**

**Why that is not enough — the killer.** The value in an access-review product is **not the campaign
workflow. It is the connectors.** The product's job is to know what access exists in Okta, AWS IAM,
Google Workspace, Salesforce, GitHub, Snowflake, NetSuite, Jira and forty more. The existing identity
service models *this platform's own* users — it has no bearing on the customer's estate. So the
reusable asset covers the cheap half of the product and none of the expensive half.

Vanta has "the deepest integration library in the category"
([axipro.co, Vanta Review 2026](https://axipro.co/vanta-review-2026/)), and it **already handles the
non-integrated long tail**: its own documentation instructs users to "Upload access files from
non-integrated systems" and accept "manual evidence of remediation"
([Vanta — How do you perform quarterly access reviews](https://www.vanta.com/resources/how-do-you-perform-quarterly-access-reviews), read 2026-08-17;
see also [Vanta Help Center — access review for tools not integrated with Vanta](https://help.vanta.com/en/articles/11345424-how-to-initiate-an-access-review-for-tools-not-integrated-with-vanta)).
Vanta claims it will "reduce the time and cost of an access review up to 90%."

**The one genuine crack, and who is pointing at it.** Zluri argues: "The biggest risk in
Vanta-centered access reviews is that you review the applications Vanta knows about and leave
unreviewed access in the applications it doesn't… A Vanta-based access review covers your known
application estate, not your actual application estate"
([Zluri, Vanta user access reviews](https://www.zluri.com/eye-on-identity/vanta-user-access-reviews-strategy-tips)).
**Weigh this carefully: that is a competitor's attack line, not neutral analysis**, and Vanta's CSV
path exists precisely to answer it. It is a real seam, but it is a known, defended one.

**Buyer and budget.** IT/security lead or controller at a pre-IPO or SOX-scoped company. Budget
exists — the mid-market band is $25k–$150k/yr — but that budget sits with buyers big enough to want
connectors, and the buyers small enough to accept a CSV-driven tool are the ones already inside a
$10k Vanta contract that includes it.

**Build cost (extrapolation from this codebase, not a cited figure):** 4–6 weeks for a credible
CSV-in campaign engine with manager routing, delegation, revocation tracking and a frozen evidence
pack. **Six months-plus** for enough connectors to compete with anyone. The first number is
achievable and insufficient; the second is not achievable solo.

**Honest risk:** you would be selling the half of the product that the incumbent gives away, to a
buyer who already owns it.

**The only version I would consider:** not "access reviews" horizontally, but access reviews for a
**named vertical whose critical systems have no APIs and that Vanta does not sell into** — e.g.
Canadian credit unions, hospitals, or municipalities running line-of-business software with no
integration story, where the review is genuinely a spreadsheet today and always will be. That is a
different business (services-heavy, slow sales cycle) and it needs a customer conversation before a
line of code.

---

### 2.2 Employee offboarding evidence — proving every access was actually revoked

**Verdict: the crispest problem statement of the seven, and the one where this codebase has a real,
already-written head start. Ranked #1 overall, with caveats.**

**The need.** Deprovisioning failure is a documented, recurring control failure with a named public
example I verified independently. **On 10 December 2021 a former Block/Cash App employee downloaded
reports containing US customer data.** They had held legitimate access to those reports in their
previous role; the access was used "without permission after their employment ended." **8.2 million
current and former customers were notified**, and Block did not disclose publicly until an SEC filing
on **4 April 2022** — nearly four months later
([GovInfoSecurity](https://www.govinfosecurity.com/cash-app-warns-82-million-customers-insider-breach-a-18860);
[Security Affairs](https://securityaffairs.com/129892/data-breach/block-cash-app-data-breach.html), read 2026-08-17).

That is the perfect sales anecdote for this product and it is real: **not a hack, not a phishing
campaign — an offboarding step that did not happen, at a company with a large security team.**

The structural cause is well described:
The structural cause is specific and technical: "Disabling a user in the identity provider does not
automatically revoke third-party app grants, personal access tokens, or live browser sessions, which
often retain their original permissions independently and can continue accessing mail, files, and
APIs long after the employee is gone" (same source).

The compliance angle is the part that matters commercially: "There's often no evidence that each step
was completed, by whom, and when… without completion records, the process might as well not have
happened from an audit perspective." SOC 2, ISO 27001, HIPAA and NIST SP 800-53 all require
demonstrable timely deprovisioning with audit-ready evidence per removal action (same source).

*Source caution: nhimg.org is an industry/vendor-adjacent publication. The Cash App breach is
independently well documented; the "studies consistently show" claims in that article are
unattributed and I did not find the underlying studies. Do not quote a percentage.*

**Why this platform has a genuine edge — and this is the strongest such claim in the document.**
`services/pulse/app/services/leavers.py` already implements the hard part of this control, and
implements it with the failure mode that actually bites. Its own docstring:

> "The failure mode this file exists to avoid: reading 'identity didn't answer' as 'everyone left'.
> Departure is only ever inferred from something identity said… A chunk identity failed to answer
> contributes to neither, so an outage (total or partial) can't delete a row."

That is a deprovisioning engine that is safe under partial identity-service failure, with attribution
preserved after credential revocation. **Most teams get this wrong.** The pattern generalises
directly: identity says a person left → each connected system is checked → revocation is executed or
flagged → the record is frozen and signed off by a named person.

**What already exists in the market — and this is the best price evidence in the whole document.**
SaaS-offboarding automation is a populated category (Nudge Security, Reco, DoControl, Stitchflow,
InvGate, plus every SaaS-management platform), and Vanta/Drata both flag "terminated or
department-changed employees" as risky accounts within access reviews
([Vanta access reviews page](https://www.vanta.com/resources/how-do-you-perform-quarterly-access-reviews)).

**Nudge Security publishes an actual rate card** — rare in this research, and it is a primary source
([nudgesecurity.com/pricing](https://www.nudgesecurity.com/pricing), read 2026-08-17):

| Plan | Size | Price |
|---|---|---|
| Essential | up to 150 users | **$750/month billed annually** (= $9,000/yr) |
| Growth | 150–1,500 users | **$5/user/month billed annually** |
| Enterprise | 1,500+ | custom |

Priced on active workspace users with mailboxes, typically 1.2–1.5 per employee. **All features
included at every tier, with a free trial**, and "Employee Offboarding" with an automated
"offboarding playbook" to "quickly and fully revoke access when an employee leaves or changes roles"
is in the box. Reco is likewise reported at ~$5/active user/mo and advertises **225+ connected
applications** ([reco.ai](https://www.reco.ai/compare/saas-offboarding-automation-tools)); DoControl's
average annual contract is reported at ~$72,000 ([Vendr](https://www.vendr.com/marketplace/docontrol)
— aggregator figure).

**Read that table two ways, because it cuts both directions.**

*The good news:* **$9,000/yr for a 150-person company is a published, defensible price for exactly
this problem.** That is the number a solo developer can quote against without guessing, and it is a
liveable contract value — twenty customers is a salary. It also proves the budget line exists and
sits outside the compliance-platform spend.

*The bad news, and it is significant:* a funded competitor already ships offboarding at that price
with everything included and 225+ connectors next door.

**And the "evidence framing" wedge is partly occupied too — I went looking specifically to disprove
my own idea and found Stitchflow.** It positions on exactly the artefact, not the automation:
"Every automation run is timestamped, logged, and recorded (passwords redacted) and kept as audit
evidence," so that "offboarding is not just executed — it's **provable for auditors**: who ran what,
when, and what changed"
([stitchflow.com](https://www.stitchflow.com/blog/best-employee-offboarding-software), read 2026-08-17
— **this is Stitchflow's own blog, so treat the competitive claims as marketing**; the quotes about
their own product are still what they sell).

**One detail in that quote is the actual remaining opening: Stitchflow's audit evidence has
"90-day retention by default."** A SOC 2 Type II observation window is twelve months. **The retention
argument that failed for GitHub in Part 1 is genuinely live here** — the incumbent's own default
keeps evidence for a quarter of the period an auditor will sample. Whether that is configurable on
higher tiers I could not determine, and it is the first thing to check before committing.

So the honest wedge is narrower than "nobody sells the evidence pack": it is **retention and
immutability of the offboarding record across a full audit period**, against competitors who treat
evidence as a log with a short default TTL. That is a defensible product claim. It is also a
detail-level advantage, and a well-funded competitor can change a retention setting in an afternoon.

**Buyer and budget.** IT manager or security lead at a 50–200 person company. Budget line confirmed
at roughly **$5/user/month or $9,000/yr flat at the small end**.

**Build cost (extrapolation):** 5–8 weeks for a defensible v1, dominated by connectors, though far
fewer are needed than for full access reviews — Google Workspace, Microsoft 365, Okta, GitHub, AWS
and Slack cover most of the risk for most companies.

**Honest risk.** Three, in order:
1. **Connectors are still the product.** Six is enough for a first customer and not enough for a
   second one in a different stack.
2. **A funded incumbent at the same price with all features included.** Competing on "our record is
   more auditable" against "ours revokes 225 apps" is a hard first sales call.
3. **It is an after-the-incident purchase.** People buy this having been burned, which makes
   proactive outbound slow.

---

### 2.3 IT asset / SaaS-licence management and shadow-IT discovery

**Verdict: killed. Wrong shape, crowded, and priced too low.**

The category is mature and has published prices: **Torii's Basic plan is $2.50 per employee per
month billed annually**; Zluri is reported at $4–$8/user/mo; Zylo and Productiv sit alongside
([cloudeagle.ai Torii pricing guide](https://www.cloudeagle.ai/blogs/torii-pricing-guide);
[gartsolutions.com Zluri vs Torii vs Zylo 2026](https://gartsolutions.com/zluri-torii-zylo/), both read 2026-08-17;
Torii's per-employee figure is the only one traceable to a specific published plan).

Two reasons to kill it:

1. **It does not fit the pattern.** Shadow-IT discovery is a *data-collection* problem — browser
   extensions, SSO log parsing, expense-feed matching, finance-system integration. There is no
   approval artefact at the centre. The platform's actual strength contributes almost nothing.
2. **At $2.50/employee/mo, a 150-person customer is $4,500/yr** against a product that needs
   finance-system and SSO integrations plus a discovery corpus. The unit economics do not support
   the build.

---

### 2.4 Vendor / third-party risk review cycles

**Verdict: killed. Explicitly a paid add-on inside the incumbent.**

Vanta's VRM module is reported at **~$11,200/yr on top of the base compliance plan**, and
ProcessUnity's SMB package starts at **$25,000**; at the bottom, Risk 365 starts at **$750/yr with
unlimited users** ([complyjet.com, Best Vendor Risk Management Software 2026](https://www.complyjet.com/blog/best-vendor-risk-management-software), read 2026-08-17 — secondary source; OneTrust and Vanta publish no numbers).

That price spread — $750 to $25,000 for nominally the same category — tells you the market is
segmented by depth of content (risk questionnaires, continuous monitoring feeds, breach intelligence),
not by workflow. **The workflow is the cheap part and this platform only has the workflow.** Also:
the industry is moving from annual reviews to continuous monitoring, which is a data-feed business,
not an approval business.

---

### 2.5 Change management beyond code — infrastructure and ITIL-shaped approvals

**Verdict: killed. Owned by ITSM suites at a price a solo dev cannot beat.**

Change-advisory-board workflow — change request forms, risk assessment, CAB scheduling, automated
approval routing — is a standard module in every ITSM product. Freshservice ships it as a dedicated
ITIL-aligned change module; ServiceNow has a built-in CAB Workbench for scheduling meetings,
reviewing changes and logging decisions; entry ITSM pricing in this space runs around **$22/agent/mo
billed annually** ([superblocks.com, 10 ITIL Change Management Software Tools](https://www.superblocks.com/blog/itil-change-management-software);
[manageengine.com, CAB process](https://www.manageengine.com/products/service-desk/it-change-management/cab-change-advisory-board.html), read 2026-08-17).

A company with an IT function almost certainly already has a service desk. Selling a standalone
approval router against a module they already own, bundled at $22/agent/mo, has no wedge.

---

### 2.6 Backup and disaster-recovery test evidence

**Verdict: killed as a product; the honest version is a $0 template.**

The control is real and specific. SOC 2 **A1.3** requires testing recovery procedures; the evidence
auditors want is "logs that show test dates, datasets, RPO/RTO targets, results, who conducted the
test and any remediation actions," plus documented BCPs, records of test execution, post-mortem notes
and proof of successful restores
([WatchDog Security, SOC 2 Type 2 Recovery Plan Testing (A1.3)](https://watchdogsecurity.io/soc2/test-recovery-plan-procedures);
[Konfirmity, SOC 2 Backup Testing](https://www.konfirmity.com/blog/soc-2-backup-testing), read 2026-08-17).
The sharpest framing found: "a backup that has never been restored is an assumption, not a control."

**Why it dies on frequency.** The test happens **annually**, occasionally quarterly. A product used
once or twice a year cannot sustain a subscription, cannot build habit, and will be replaced by a
Confluence page the first time someone questions the invoice. There is no recurring artefact, which
is the one thing this platform's pattern needs.

---

### 2.7 Incident post-mortem and corrective-action records

**Verdict: killed. Mature category, wrong buyer, no reuse.**

Corrective and Preventive Action (CAPA) is an established software category with entrenched
vendors — Intelex, AssurX, EHS Insight, Operandio, Ecesis — shipping root-cause analysis tooling,
action assignment, due-date alerts, evidence attachments, approval workflows and audit trails
([Intelex CAPA](https://www.intelex.com/products/applications/capa-software-corrective-and-preventive-action);
[AssurX CAPA](https://www.assurx.com/corrective-and-preventive-action-software/), read 2026-08-17).
None publishes pricing.

The problem is buyer mismatch: CAPA money sits in manufacturing, life sciences and EHS/quality, not
in an IT department. On the IT side, post-mortems live in incident tools (PagerDuty, incident.io,
Jira) that already own the workflow. Neither buyer is reachable by a solo developer with an approval
engine.

---

### 2.8 Two candidates I found that were not on the list

**(a) Ontario Bill 194 / EDSTA public-sector cyber and AI accountability — a real timing wedge that
is not yet a market. Watch it; do not build on it yet.**

Ontario's *Strengthening Cyber Security and Building Trust in the Public Sector Act, 2024* received
Royal Assent **25 November 2024**. The *Enhancing Digital Security and Trust Act* (EDSTA) and FIPPA
whistleblower amendments came into force **29 January 2025**, with privacy impact assessment
requirements and mandatory breach notification from **1 July 2025**. It covers a wide set of public
sector entities — ministries, agencies, police services boards, transit commissions, children's aid
societies and school boards — and mandates cyber security programmes and regulation of AI system use
([Dentons Data](https://www.dentonsdata.com/ontarios-new-public-sector-cybersecurity-and-ai-law-now-in-force-what-public-and-private-sector-organizations-need-to-know/);
[Fasken](https://www.fasken.com/en/knowledge/2024/12/ontarios-public-sector-cyber-security-legislation-receives-royal-assent);
[Bill 194 at the Legislative Assembly of Ontario](https://www.ola.org/en/legislative-business/bills/parliament-43/session-1/bill-194), read 2026-08-17).

Why not yet: **the substantive obligations are still undefined.** Dentons is explicit that many of
the cyber and AI obligations "are yet to be established by regulations." You cannot build a
compliance product against regulations that do not exist. The commercially interesting note is
downstream: private vendors "should anticipate that public sector organizations will begin the
process of flowing through many of these new requirements in their contracts." **When those
regulations publish, this becomes a genuine Ontario-specific opening that Vanta and Drata will not
prioritise.** Set a reminder; do not write code.

**(b) ISO 42001 / AI management systems — already absorbed by the incumbents.** Both Vanta and Drata
added ISO 42001 support by 2025 ([secureleap.tech](https://www.secureleap.tech/blog/vanta-review-pricing-top-alternatives-for-compliance-automation);
[sprinto.com Drata pricing](https://sprinto.com/blog/drata-pricing/), read 2026-08-17). I saw a widely
repeated claim that "83% of Fortune 500 procurement teams plan to require ISO 42001 alignment by
2027" — it appears only on vendor blogs with no primary source and **I do not believe it. Do not cite
it.** Killed on the same grounds as Part 1: the suites got there first.

---

### 2.9 Part 2 scoreboard

| # | Candidate | Verdict | Killed by |
|---|---|---|---|
| 2.2 | **Offboarding evidence** | **Best of a hard field** | Survived — but Nudge ships offboarding at $9k/yr and Reco has 225+ connectors |
| 2.1 | **Access reviews / certification** | Conditional — vertical only | Connectors are the product; Vanta bundles it and handles CSV |
| 2.8a | Ontario Bill 194 public sector | **Watch, don't build** | Regulations not yet published |
| 2.3 | SaaS-licence / shadow IT | Killed | Wrong shape; $2.50/employee/mo ceiling |
| 2.4 | Vendor risk reviews | Killed | Vanta VRM add-on ~$11.2k/yr; value is content, not workflow |
| 2.5 | ITIL / infrastructure change | Killed | Standard ITSM module at ~$22/agent/mo |
| 2.6 | DR / backup test evidence | Killed | Annual frequency — no subscription |
| 2.7 | Incident post-mortem / CAPA | Killed | Mature category, wrong buyer, no reuse |
| P1 | GitHub CC8.1 evidence | Killed | Premise factually wrong; Vanta ships it with 13-month retention; free competitor |

---

## Part 3 — Selling from Canada

### 3.1 Pricing: what a solo developer can realistically charge

The single most useful anchor found in this research, because it is a **published rate card for a
product adjacent to the #1 recommendation**, sold to exactly the target size band
([nudgesecurity.com/pricing](https://www.nudgesecurity.com/pricing), read 2026-08-17):

- **$750/month billed annually (= $9,000/yr) for up to 150 users**, all features included, free trial
- **$5/user/month billed annually** for 150–1,500 users
- Custom above 1,500

Other published or semi-published points in the same band:

| Product | Published price | Source quality |
|---|---|---|
| Nudge Security Essential | $750/mo (≤150 users) | **Primary** — vendor pricing page |
| Torii Basic | $2.50/employee/mo, annual | Secondary (CloudEagle guide) |
| Zluri | $4–$8/user/mo | Secondary, no rate card |
| AccessOwl / JumpCloud tier | $4–$15/user/mo | Secondary |
| ITSM entry (Freshservice-class) | ~$22/agent/mo, annual | Secondary |
| Drata / Secureframe entry | $7,500–$20,000/yr | Buyer-reported |
| Vanta entry | ~$10,000/yr | Buyer-reported |
| Vanta VRM add-on | ~$11,200/yr | Buyer-reported |
| Mid-market IGA (Lumos/ConductorOne/Opal) | $25,000–$150,000/yr | Secondary |

**The shape that emerges, and it is consistent across every category examined:**

1. **The floor for a serious B2B tool aimed at 20–200 person companies is roughly $6,000–$12,000 per
   year.** Below that, the vendor cannot afford the sales conversation and the buyer does not take
   the product seriously. Nudge's $750/mo minimum is that floor made explicit — note they charge a
   flat minimum rather than let a 40-person company pay $200/mo.
2. **Flat-rate at the small end, per-seat above it.** Nudge switches from flat to per-user at 150.
   This is the right structure to copy: per-seat maths on a 40-person customer produces an invoice
   not worth issuing.
3. **Annual billing, paid up front.** Every published price in the table is "billed annually." For a
   solo developer this is the difference between a business and a hobby: twelve customers at
   $9,000/yr paid annually is $108,000 collected in twelve conversations, not 144 monthly charges.

**Extrapolation, labelled as such:** I would price a first product at **$500–$900/month billed
annually for companies up to ~150 employees**, deliberately anchored just under Nudge, with no free
tier and a 30-day trial. Twenty customers is a salary. I found **no rigorous published benchmark data
on solo/bootstrapped B2B SaaS pricing outcomes** (MicroConf, Indie Hackers and ChartMogul surveys did
not surface with citable figures in this research) — so the $500–$900 figure is inference from the
competitive rate cards above, not a benchmark.

### 3.2 GST/HST — the non-obvious part that catches Canadian founders

**The rule most people get wrong: zero-rated does not mean invisible.**

- The small supplier threshold is **$30,000 CAD** in taxable supplies over four consecutive calendar
  quarters (or in a single quarter). Above it, registration is mandatory
  ([Canada.ca — cross-border threshold amounts](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/gst-hst-businesses/digital-economy-gsthst/find-out-need-register/cross-border-threshold-amounts.html);
  [Canada.ca RC4022 — General Information for GST/HST Registrants](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/rc4022/general-information-gst-hst-registrants.html), read 2026-08-17).
- **Exports of services and intangibles to non-residents are generally zero-rated — taxable at 0%,
  not exempt.** ([Canada.ca GI-034 — Exports of Intangible Personal Property](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/gi-034/exports-intangible-personal-property.html);
  [Canada.ca B-090 — GST/HST and Electronic Commerce](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/b-090/gst-hst-electronic-commerce-2.html)).
- **The trap: zero-rated sales still count toward the $30,000 threshold.** You "count your worldwide
  taxable supplies, including zero-rated sales." So a Canadian developer selling **only** to US
  customers, charging 0% GST/HST on every invoice, **still becomes a mandatory registrant once US
  revenue passes $30,000 CAD.**

**What this means in practice, in plain language.** Selling SaaS to US companies from Ontario:
you charge them nothing in Canadian tax; you charge Ontario customers 13% HST; and once you pass
$30k you must register and file returns even though most of your revenue carries 0%. The upside of
registering — and the reason to consider doing it **voluntarily on day one** — is **input tax
credits**: a registrant recovers the GST/HST paid on business inputs (AWS, laptops, software,
accounting fees). A zero-rated exporter is in the best possible position, collecting nothing and
recovering everything, which typically means a **refund** rather than a payment.

**Flagged as not fully verified:** I could not fetch the CRA "When to register and charge" page
directly (HTTP 403). The threshold and zero-rating conclusions above come from other Canada.ca pages
(RC4022, GI-034, B-090, the digital-economy threshold page), which is still primary-source, but
**confirm the input-tax-credit and voluntary-registration mechanics with an accountant before acting**
— the qualifying conditions for zero-rating an export of services have exceptions I did not test.

### 3.3 Payment rails — Stripe from Canada

Verified from Stripe's own Canadian pricing page ([stripe.com/en-ca/pricing](https://stripe.com/en-ca/pricing), read 2026-08-17):

| Item | Fee |
|---|---|
| Domestic cards | **2.9% + CA$0.30** per successful transaction |
| International cards | **+0.8%** |
| Manually entered cards | +0.5% |
| **Currency conversion** | **+2%** |
| Dispute | CA$15.00 (refunded if won) |
| Bank pre-authorised debits | 1% + CA$0.40, CA$5.00 cap |
| Setup / monthly / hidden fees | None |

**The number that matters for a Canadian selling to Americans is the stacking.** A US customer paying
a USD-denominated invoice by card runs 2.9% + 0.8% international + potentially 2% conversion —
**up to roughly 5.7%** before it reaches a CAD bank account. On a $9,000/yr contract that is
**~$513 per customer per year**, which is real money at twenty customers.

**Two mitigations worth taking seriously, both labelled extrapolation:**
1. **Hold a USD balance and settle in USD** rather than converting each transaction, so conversion
   happens once at a rate you choose. (Stripe supports multi-currency settlement in Canada; I did not
   verify the exact account requirements.)
2. **Invoice annual contracts by bank transfer / ACH rather than card.** Stripe's pre-authorised
   debit path is 1% capped at CA$5.00 — on a $9,000 invoice that is a rounding error versus ~$513.
   **For annual B2B contracts, do not take cards.** This alone is worth more than most pricing
   optimisation.

### 3.3b US sales tax — real, but not an early-stage problem

Being foreign does not exempt you. Since *South Dakota v. Wayfair* (2018), all US states with a sales
tax enforce **economic nexus**: remote sellers must register and collect once a threshold is crossed,
with no physical presence required. As of 2026, **46 states publish a dollar threshold — 41 of them
at $100,000**, two at $250,000 and three at $500,000
([Numeral, Economic Nexus State-by-State Handbook 2026](https://www.numeral.com/blog/economic-nexus);
[TaxCloud, Sales Tax Nexus by State 2026](https://taxcloud.com/blog/sales-tax-nexus-by-state/), read
2026-08-17 — both are sales-tax vendors, i.e. parties with an interest in the problem sounding large).

**Why this is not an early problem, and the arithmetic is the whole argument.** The threshold is
**per state**. A solo developer at $150,000 ARR spread across fifteen customers in ten states has
roughly $15,000 of revenue in each — nowhere near $100,000 anywhere. **Registration obligations
realistically begin when a single state's revenue approaches $100k**, which for a $9,000/yr product
means about eleven customers concentrated in one state. Watch California, New York and Texas first
simply because that is where the customers will cluster.

**Sources conflict on which states tax SaaS and I could not resolve it.** One source lists Washington
among states where "most SaaS" is exempt, which contradicts my understanding that Washington taxes
SaaS as a digital automated service. New York, Texas, Massachusetts, Pennsylvania and Ohio are
commonly listed as taxing SaaS; California generally does not. **Do not rely on any list in this
document** — SaaS taxability is state-specific, changes yearly (Maine expanded digital taxability in
2026), and is exactly what Stripe Tax, Anrok and Avalara exist to track. Buy one of those when the
first state threshold comes into view, not before.

### 3.4 Does being Canadian change the maths?

*Partially verified — see the caveats.*

**Incorporation is cheap and the choice barely matters here.** Federal incorporation through
Corporations Canada is **$200 filed online**; Ontario provincial incorporation is **$300**
([MinuteBox, Methods of Incorporation in Canada 2026](https://www.minutebox.com/blog/the-methods-of-incorporation-in-canada/), read 2026-08-17 — secondary source; confirm current fees on ised-isde.canada.ca and ontario.ca before filing).

One difference worth knowing even though it does not bite a Canadian-resident founder: **Ontario
eliminated its 25% resident-Canadian director requirement effective 5 July 2021**
([Stikeman Elliott](https://stikeman.com/en-ca/kh/canadian-ma-law/obca-amendments-removing-canadian-director-requirement-and-lowering-approval-threshold);
[RSM Canada](https://rsmcanada.com/insights/tax-alerts/2021/canadian-resident-directors-no-longer-needed-for-ontario-corpora.html)),
whereas **the federal CBCA still requires at least 25% resident Canadian directors** (at least one if
there are fewer than four). For a solo Canadian-resident founder both are satisfied trivially; it
only matters if a US co-founder or director is added later, in which case Ontario is the more
flexible vehicle.

**What genuinely does not matter:** Stripe works, USD invoicing works, and US buyers at the 20–200
person size are not running the kind of procurement process that rejects a foreign vendor. This is
not a meaningful handicap.

**What genuinely does matter, ranked:**
1. **The FX and card-fee stack** (3.3) — the only clearly quantified disadvantage, and it is
   solvable by not taking cards.
2. **Data residency questions in security reviews.** A US buyer may ask where data lives; hosting in
   a US region answers it. This is a configuration decision, not a business-model one.
3. **Zero-rated exports are an advantage, not a burden** (3.2) — collecting no tax while recovering
   input tax is better than the US position.

### 3.5 A Canada/Ontario-specific angle — one candidate, and it is early

**The only Ontario-specific opportunity I found with a real statute behind it is Bill 194 / EDSTA,
covered in §2.8a. Its obligations are not yet defined by regulation, so there is no budget yet.**
That is the honest answer: a real regulation, a real future buyer, and nothing to sell today.

**I deliberately did not build a recommendation on PIPEDA or Quebec's Law 25** without evidence of
purchasing. The existence of a privacy statute is not a market; the brief was explicit about this and
it is the right standard.

**What I did not get to, and would want before betting on a public-sector angle:** Ontario Broader
Public Sector Procurement Directive thresholds (do they make a solo vendor's life impossible?),
whether CanadaBuys / ProServices has a realistic route for a one-person company, whether any Canadian
public-sector data-residency rule would exclude Vanta and Drata and create a wedge, and whether
Quebec's CAI has issued Law 25 enforcement actions large enough to move budgets. **These are the four
questions that would decide whether a Canada-specific play exists at all**, and they are listed in
"What I could not verify" rather than answered here. Treat §3.5 as an open question, not a
recommendation.

---

## What I could not verify

Listed so nothing here is mistaken for settled fact.

### Pricing — almost none of it is primary

**Not one of the compliance or identity-governance vendors in this document publishes a rate card.**
Vanta, Drata, Secureframe, Thoropass, ConductorOne, Lumos, Opal, Zluri, Veza, SailPoint, OneTrust,
ProcessUnity, Intelex and AssurX are all contact-sales. Every dollar figure I give for them is
buyer-reported or aggregator-derived (secureleap.tech, cavanex.com, complyjet.com, flamingo.run,
cloudeagle.ai). Aggregator medians are directionally useful and individually unreliable — treat any
single number as ±50%.

The exceptions, traceable to a published plan and the figures I would actually rely on:
**Nudge Security at $750/month up to 150 users and $5/user/month above** (fetched from their own
pricing page — the single best price datapoint here), **Torii Basic at $2.50/employee/month billed
annually**, and **EvidentTrail at $0 during Early Access**.

Reco's ~$5/active user/month is secondary (reco.ai comparison content, not a rate card) and
DoControl's ~$72,000 average annual contract is a Vendr aggregator figure.

### Claims I could not confirm

- **The "13-month retention" figure for Vanta Code Changes** comes from Vanta's own help centre and I
  treat it as authoritative, but I could not confirm whether that retention applies on all plan tiers
  or only above a certain one. If Evidence were being reconsidered, this is the one number to
  re-check — it is load-bearing for the kill.
- **Whether Stitchflow's 90-day evidence retention is configurable.** This is now the load-bearing
  detail under the #1 recommendation, and it came from Stitchflow's own blog rather than a pricing or
  docs page. **Check it first.** If they offer 12-month retention on any paid tier, the wedge in 2.2
  shrinks to framing alone.
- **Whether EvidentTrail has any customers.** Free-during-early-access could mean traction or could
  mean an unlaunched side project. I found a Product Hunt launch and a GitHub Marketplace listing, no
  customer count, no funding, no team page. **A free competitor with no users is a weaker threat than
  I have treated it as** — but the Vanta finding kills the idea independently, so this does not change
  the verdict.
- **Quantified access-review effort.** The "over a week per quarter, more than 30 days total" figure
  is a single unnamed customer anecdote in a Zluri blog post. I found no independent survey measuring
  how long access reviews take or what companies spend on them. Do not put that number in a pitch.
- **The Zluri claim that Vanta-based access reviews miss the real application estate.** This is a
  competitor's attack line. Vanta's own documentation shows a CSV path for non-integrated systems,
  which at least partially answers it. I could not find neutral evidence about how often Vanta
  customers actually find this insufficient. **This is the single most important unverified point in
  Part 2** — if the gap is real and painful, 2.1 is stronger than I have ranked it.
- **Whether buyers ever choose compliance point tools over suites.** I found only vendor and MSP blog
  posts asserting consolidation, and no rigorous survey either way. I rested the conclusion on the
  mechanical multi-framework evidence-mapping argument instead, which does not depend on those
  sources.
- **The "83% of Fortune 500 procurement teams plan to require ISO 42001 alignment by 2027" claim.**
  Widely repeated across vendor blogs with no primary source. **I do not believe it. Do not cite it.**
- **OSFI Guideline B-13** (technology and cyber risk management for federally regulated financial
  institutions, effective 1 Jan 2024) looked like a promising Canadian regulatory wedge. I found the
  guideline and its scope but **no evidence of associated software budget, no procurement data, and
  no indication it applies to provincially regulated credit unions.** Unresolved — worth a follow-up
  if the financial-services vertical is pursued.
- **Ontario Bill 194 in-force detail.** Sources agree on Royal Assent (25 Nov 2024) and the 29 Jan
  2025 / 1 Jul 2025 phases, but they describe the split between FIPPA amendments and EDSTA slightly
  differently. I could not reconcile which specific EDSTA sections are live versus awaiting
  regulation. Read the statute directly before acting on it.
- **Build-cost estimates (4–6 weeks, 5–8 weeks, six months-plus) are my extrapolation** from reading
  this codebase, not cited benchmarks. They assume one developer, existing Pulse and identity
  patterns reused, and no integration surprises — and integration surprises are the entire risk in
  both surviving candidates.

### Part 3 gaps specifically

- **CRA's "When to register and charge GST/HST" page returned HTTP 403** and could not be fetched.
  The $30,000 threshold, the zero-rating of exported services, and the fact that zero-rated sales
  count toward the threshold all come from other Canada.ca pages (RC4022, GI-034, B-090, the
  digital-economy threshold page) — primary-source, but not the page I wanted. **The input-tax-credit
  and voluntary-registration mechanics should be confirmed with an accountant**; zero-rating an export
  of services has qualifying conditions I did not test.
- **Which US states tax SaaS — unresolved, sources conflict.** One source lists Washington as mostly
  exempting SaaS, which contradicts my understanding. Do not use any list in this document.
- **Ontario Broader Public Sector Procurement Directive thresholds** — not researched. Whether a
  solo vendor can realistically sell to Ontario hospitals, universities or school boards is unknown.
- **CanadaBuys / ProServices / federal small-vendor routes** — not researched. No evidence gathered
  on whether micro-vendors actually win federal contracts.
- **Canadian public-sector data-residency requirements and Protected B / CCCS cloud assessment** —
  not researched. **This was the most commercially interesting open question**: if any Canadian
  public-sector rule effectively excludes US SaaS vendors, that is a structural wedge no amount of
  feature work can replicate. Unanswered.
- **Quebec Law 25 enforcement by the CAI** — not researched. I deliberately excluded Law 25 and
  PIPEDA from the recommendations because I found no purchasing evidence, but "I did not look hard"
  is a fairer description than "I looked and found nothing."
- **Stripe multi-currency settlement specifics for Canadian accounts** — the pricing page gave fees,
  not account mechanics. The USD-balance mitigation in §3.3 is extrapolation.
- **SR&ED tax credits and the Canadian small-business tax rate** for a one-person software company —
  not researched. Both could materially change the after-tax maths and neither is reflected here.
- **Bootstrapped/solo B2B SaaS pricing benchmarks** (MicroConf, Indie Hackers, ChartMogul) — no
  citable figures surfaced. The $500–$900/month recommendation in §3.1 is inference from competitor
  rate cards, not benchmark data.

### Where sources conflicted, and how I resolved it

- *GitHub audit log retention:* vendor blogs (Strac, GitProtect) say 90 days; GitHub's own
  documentation says 180 days for Enterprise Cloud, 7 days for Git events, indefinite-by-default on
  Enterprise Server. **I sided with GitHub's documentation.** The prior brief's error came from
  trusting a vendor blog on a question the vendor had an interest in.
- *Whether access-review pain is severe:* every source describing it as severe sells software to fix
  it. Vanta describes the same problem while claiming to have solved it. **I treated the existence of
  the chore as established and every quantification of it as marketing.**
- *Point tools vs suites:* consolidation blogs versus no counter-evidence. **I declined to rest on
  either** and used the structural argument instead.
- *Offboarding tool positioning:* I initially concluded nobody sells the evidence artefact as the
  product, then went looking specifically to disprove myself and found Stitchflow doing exactly that.
  **I revised the claim down** rather than keeping the stronger version. What survived — the 90-day
  default retention gap — is narrower and better evidenced than what I started with.

---

## Method note

Research was done with web search and direct page fetches on 2026-08-17. Where a vendor's own
documentation or pricing page was reachable, I used it and said so; where only aggregators or vendor
blogs existed, I said that too. Three pages refused to serve (CRA "when to register and charge", the
Ontario IPC Bill 194 page, both HTTP 403) and are flagged.

**The methodological lesson from Part 1 is worth keeping.** The prior brief's central factual claim
was sourced from a vendor blog on a question the vendor had a commercial interest in, and it was
wrong by a factor of two in the wrong direction. Every load-bearing fact in this document was chased
to the party who actually owns it — GitHub's docs for GitHub retention, Vanta's help centre for what
Vanta does, Stripe's own pricing page for Stripe's fees, Canada.ca for tax rules. **Where I could not
do that, the claim is marked rather than smoothed over.**

Repository claims cite file paths in this repo rather than URLs.
