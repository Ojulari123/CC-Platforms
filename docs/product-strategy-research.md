# Product strategy research — Meridian (Pulse, Forge, and what comes next)

**Status:** complete. Opinionated on purpose — it commits to a recommendation.
**Date of research:** 2026-08-17. Non-obvious claims carry a source URL and the date the source was read or published.
**Audience:** the developer deciding what to build next, and whether anyone will pay for it.

Read "What I could not verify" before acting on anything in Part A.5 or B.2 — one load-bearing
assumption in both is untested.

---

## Executive summary

**Forge is not worth saving as a no-code ML product. Kill that framing this week.** The category's own
leaders left it while Forge was being planned: Obviously.AI — the closest analogue to Forge's pitch —
rebranded to Zams in Feb 2025 and dropped no-code ML entirely for AI sales agents; Google retired the
Vertex AI brand on 22 Apr 2026 and had already shut down AutoML Text (Jun 2025) and AutoML Video
(Jul 2025); Akkio narrowed to media agencies; Pecan cut ~25% of staff and narrowed to demand
forecasting; DataRobot cut 26% then 7% of staff and re-pitched as agents. Meanwhile AWS rents the
exact thing Forge is trying to build for **$1.90/hour** with 750 free hours and no seat commitment.
There is no price, no moat, and no buyer at the end of that build.

**What to do instead, in one sentence each:**

1. **Reposition Forge as "Assurance": a regulatory submission workspace.** Keep the service, keep the
   dataset upload, throw away the ML framing. Assurance does what Pulse does — pull data, compile a
   decision artefact, route it to a named approver, refuse self-approval, keep the evidence — pointed
   at Nigeria's mandatory recurring filings (NUPRC NPMS monthly production, NEITI Hydrocarbon Flows
   templates, NCDMB Nigerian Content plans). It sits *beside* CypherCrescent's SEPAL rather than
   competing with it, and no incumbent ships Nigerian regulator templates.
2. **Do not build a third app. Build one module.** Point Pulse's existing GitHub sync and approval
   engine at SOC 2 control CC8.1 and sell audit-ready change-management evidence. GitHub keeps audit
   logs for 90 days; auditors want twelve months. Vanta and Drata charge $7.5k–$60k/yr for platforms
   built on this class of problem. Incremental build: ~3–5 weeks, because both halves already exist.
3. **Price Pulse as a flat annual per-organisation contract, not per seat.** The category is
   per-contributor — LinearB publishes $29 and $59/contributor/mo with 30- and 50-seat minimums,
   Swarmia €42/dev/mo, Jellyfish's median contract is $35,920/yr — but those seat floors exist because
   the smallest viable customer in engineering analytics is about 30 engineers. Below that, per-seat
   maths produces a number not worth invoicing.

**The single hardest truth in this document:** Pulse's principled refusal to score individual
engineers is correct, defensible, and **not a differentiator**. Swarmia already owns that position
and publishes essays about it. What is actually unusual about Pulse is the **named-lead approval
decision with self-approval refused** — that is an auditable control, and controls are what people
buy. Lead with the sign-off, keep the no-scoring stance as the thing that stops the tool getting
killed politically once engineers find out it exists.

**And on money: Nigeria is where the product gets validated, not where it gets funded.** A $1,000/yr
subscription went from ~₦471,000 to ~₦1.53m in naira terms since early 2023; USD self-serve SaaS has
"very limited uptake outside the largest enterprises" because of CBN restrictions and FX
availability; and indigenous oil-service firms routinely fund work themselves long before payment
arrives. Treat CypherCrescent as tenant zero and reference customer; the paying tier is
large operators and the international arms of service firms.

---

## Part A — Is Forge salvageable, and as what?

### A.1 Who owns no-code/low-code ML, and at what price

The first thing worth reporting is what happened when I went looking for pricing pages. **Most of the
category no longer publishes prices, and several of the companies no longer sell no-code ML at all.**

| Vendor | Status as of Aug 2026 | Price |
|---|---|---|
| Obviously.AI | **Rebranded to Zams in Feb 2025 and abandoned no-code ML** for AI sales agents | Legacy pricing page still lists Free (10k rows) / Startup (1M rows) / SMB (100M rows) / Enterprise, all paid tiers **contact-sales, no number shown** |
| Akkio | Still alive, repositioned as "Enterprise AI Analytics Platform **for media agencies**" | All pricing behind contact-sales. Historic self-serve was ~$49/user/mo |
| Pecan AI | Alive, pivoted to GenAI demand forecasting; **cut ~25% of staff** | Contact-sales |
| DataRobot | Alive, pivoted to agentic AI. **26% layoff 2023, further 7% 2024** | Contact-sales |
| Google Vertex AI AutoML | **The Vertex AI brand was retired on 22 Apr 2026** and folded into Gemini Enterprise Agent Platform. AutoML Text shut down 15 Jun 2025; AutoML Video shut down 31 Jul 2025; Vertex AI Vision deprecated 15 Jun 2026, EOL 30 Sep 2026 | Usage-based |
| AWS SageMaker Canvas | Alive | **$1.90/hour** of workspace session time, plus training compute, plus Bedrock usage if used |
| Dataiku | Alive, healthy, enterprise | No public price. Buyer-reported median **~$26,000/yr**; commonly quoted as starting ~$4,000/mo and reaching six figures |
| Alteryx | **Taken private for $4.4bn** by Clearlake + Insight, closed 19 Mar 2024 | — |
| KNIME | Alive, open-core desktop-free model | — |

**Evidence:**

- The Vertex AI rebrand is real and dated. Google's own product page is now titled
  "Gemini Enterprise Agent Platform (formerly Vertex AI)"
  ([cloud.google.com](https://cloud.google.com/products/gemini-enterprise-agent-platform), read
  2026-08-17), and the platform was announced as the replacement for Vertex AI on **22 Apr 2026**
  ([Wikipedia: Gemini Enterprise Agent Platform](https://en.wikipedia.org/wiki/Gemini_Enterprise_Agent_Platform)).
  The AutoML shutdown dates come from Google's own deprecation notes: AutoML Text usable "until
  June 15, 2025", AutoML Video deprecated 31 Jul 2024 with shutdown 31 Jul 2025, Vertex AI Vision
  deprecated 15 Jun 2026 / EOL 30 Sep 2026
  ([Vertex AI deprecations](https://cloud.google.com/vertex-ai/docs/deprecations),
  [Vision release notes](https://docs.cloud.google.com/vision-ai/docs/release-notes)).
  **The brief's suspicion was correct, and it is a category signal, not a URL glitch.** Google did
  not just rename a product; it deleted the no-code-model-training framing and replaced it with
  "build agents."
- Obviously.AI → Zams: announced by founder Nirman Dave, Feb 2025
  ([zams.com/blog/introducing-zams](https://zams.com/blog/introducing-zams);
  [LinkedIn announcement](https://www.linkedin.com/posts/nirmandave_big-news-obviously-ai-is-now-zams-activity-7295145622993584128-V8St);
  [Crunchbase, "Zams (prev. Obviously AI)"](https://www.crunchbase.com/organization/zams)).
  This is the single most on-the-nose datapoint in Part A: **the company that most closely matched
  what Forge aspires to be looked at the market and left it.**
- Pecan AI cut roughly a quarter of its employees
  ([Calcalist / Ctech](https://www.calcalistech.com/ctechnews/article/hkrgrqvqo)) and its 2025–26
  launches are vertical forecasting products (DemandForecast.ai, Aug 2025;
  "Predictive AI Agent", Jan 2026) rather than general no-code ML
  ([PR Newswire](https://www.prnewswire.com/news-releases/pecan-ai-launches-demandforecastai-to-fix-the-trillion-dollar-forecasting-gap-with-genai-powered-supply-chain-insights-302540298.html)).
- DataRobot: 26% workforce cut in 2023, a further 7% of ~1,400 staff in 2024
  ([TechTarget](https://www.techtarget.com/searchenterpriseai/news/252524275/Troubled-AI-vendor-DataRobot-hit-by-more-layoffs);
  [The Information](https://www.theinformation.com/briefings/ai-startup-datarobot-lays-off-7-in-cost-cutting-move)).
  Valuation went from $6.3bn (Series G, Jul 2021) to mutual-fund marks a small fraction of cost
  basis — BlackRock marked its Series F position at ~$852k against a $3.0m cost basis as of
  31 Dec 2025 ([Sacra](https://sacra.com/c/datarobot/)). ARR was ~$285m in 2024, so the business
  is real; the *valuation* of AutoML as a category is what collapsed.
- Alteryx take-private: $48.25/share, $4.4bn including debt, announced Dec 2023, closed 19 Mar 2024
  ([Alteryx investor relations](https://investor.alteryx.com/news/news-details/2023/Alteryx-Enters-into-Definitive-Agreement-to-Be-Acquired-by-Clearlake-Capital-Group-and-Insight-Partners-for-4.4-Billion/)).
  Going private at a 59% premium to an already-depressed price is not a growth story.
- SageMaker Canvas at $1.90/session-hour
  ([AWS Canvas pricing](https://aws.amazon.com/sagemaker/ai/canvas/pricing/)) is the number that
  matters most for Forge's economics: **a hyperscaler will rent the exact thing Forge is trying to
  build for under two dollars an hour, with no seat minimum and a 750-hour free trial.**

### A.2 Did the LLM era kill the category?

It didn't kill it. It did something worse for a newcomer: it **hollowed out the middle** and moved
all remaining value to the two ends — free open source at the bottom, governed enterprise platforms
at the top. Forge's current design sits precisely in the vanished middle.

The most useful single source is Thomas Dinsmore's "Is AutoML Dead?", 18 Mar 2026
([thomaswdinsmore.substack.com](https://thomaswdinsmore.substack.com/p/is-automl-dead)). Dinsmore
tracked the nine AutoML vendors named in Forrester's May 2019 report and reported the seven-year
outcomes: DMway ceased operations in 2022; Bell Integrator sold off with a skeleton crew; Big Squid
acquired by Qlik; Squark acquired in a distressed sale; DataRobot and H2O.ai both repositioned away
from AutoML toward MLOps and governance. His argument for *why* is the part that should decide
Forge's fate:

> "They weren't getting better models. If DataRobot or Driverless AI built better models than
> AutoGluon, the vendors would have published benchmarks."

That is a claim about **the absence of a technical moat**, and it applies with far more force to a
one-developer product than to DataRobot. Dinsmore's conclusion — commercial AutoML is dead, open
source AutoML thrives — is one analyst's view and is stated more strongly than the rest of the
literature, so treat the specific phrase "dead" as opinion. The vendor outcomes he lists are
checkable facts, and the ones I spot-checked (DataRobot, Alteryx) hold up.

Where the category *did* survive, it survived by becoming one of three things, none of which is
"upload a CSV and pick a model":

1. **A step inside an agent platform.** Google, DataRobot, and Pecan all now lead with agents.
2. **A library, free.** AutoGluon, FLAML, and similar now absorb LLM fine-tuning as just another
   model type ([open-source AutoML 2026 survey](https://mljar.com/blog/open-source-automl-projects-in-2026/)).
3. **A vertical.** Akkio narrowed to media agencies; Pecan narrowed to demand forecasting. Both
   went from horizontal to a named industry with a named metric. **This is the survivable path and
   it is the one available to Forge.**

Conflict worth naming: content-marketing sources ("AutoML in 2026: train models without writing
code", DataCamp's framework roundup) still present no-code ML as a live, growing buyer category.
They are SEO listicles with no purchasing data behind them. I weight the vendor outcomes, the
shutdown dates, and the pricing-page disappearances over that framing.

### A.3 The honest verdict

**Forge, as a no-code AI/ML workspace, is not worth saving. Retire the framing.**

Not because the code is bad, and not because one developer can't build a workflow canvas. Because the
thing at the end of that build has no buyer:

1. **The category's own leaders left it.** Obviously.AI — the closest analogue to Forge's pitch —
   rebranded and abandoned no-code ML in Feb 2025. Google retired the brand that carried AutoML in
   Apr 2026 and shut down three AutoML product lines outright. Akkio and Pecan both narrowed to a
   single vertical. DataRobot cut a third of its staff across two years and re-pitched as agents.
   When four of the five best-funded players exit or narrow within 18 months, a new entrant is not
   early — it is late.
2. **The floor is free and the ceiling is governance.** AutoGluon and FLAML give away better models
   than a bespoke implementation will produce, and Dinsmore's point stands: no vendor ever published
   benchmarks showing otherwise. Above that, what enterprises pay Dataiku ~$26k/yr median for is
   lineage, access control, deployment, and audit — years of work.
3. **The nearest substitute is $1.90/hour.** SageMaker Canvas needs no seat commitment and gives
   away 750 hours. Forge cannot be cheaper, and cannot be more capable.
4. **Forge's remaining distance to parity is enormous.** Today it accepts a CSV up to 5 MB and
   previews it (`services/forge/app/routes/datasets.py`, `services/forge/app/services/datasets.py`).
   The backlog lists the workflow canvas, training, and scoring as not started
   (`docs/backlog.md`, "Forge, Week 6: visual ML workflows"). That is not a last mile; it is the
   whole race, against opponents who already lost it.

There is one honest counter-argument and it should be recorded: *Forge does not need to beat the
market, it only needs to serve CypherCrescent.* That is true, and it is exactly why the answer is
not "delete the service." It is **"keep the service, keep the dataset primitive, change what the
product is."** See A.5.

### A.4 The adjacent defensible thing — and the trap to avoid

**First, the trap, because it is the obvious idea and it is wrong.** The instinct is "Forge becomes
petroleum-engineering ML for CypherCrescent." Don't.

CypherCrescent's flagship commercial product is **SEPAL**, and SEPAL already is that. It is a
cloud-based well-and-reservoir-management suite integrating production, reservoir, geology,
petrophysical and well-intervention data in one application, with a Well Schematic Management
module, a Drilling and Intervention Activity Planner, and a proprietary computation engine
(**SEPAL Solver**) used for well performance analysis, reservoir simulation, and production
forecasting ([cyphercrescent.co.uk/products/show/sepal-suite](https://www.cyphercrescent.co.uk/products/show/sepal-suite);
[cyphercrescent.com/sepal-solver](https://cyphercrescent.com/sepal-solver);
[BusinessDay on SEPAL well surveillance](https://businessday.ng/energy/oilandgas/article/cyphercrescents-sepal-delivers-oil-well-surveillance-solutions/)).
The company has an NNPC partnership around production improvement
([Guardian Nigeria](https://guardian.ng/energy/nnpc-partners-cyphercrescent-to-boost-oil-production/);
[Tribune](https://tribuneonlineng.com/nnpc-cypher-crescent-partnership-boost-production/)).

So a petroleum-analytics Forge would (a) duplicate the employer's own revenue product, (b) be judged
against a team with a decade of domain depth and a maths engine, and (c) be built by the one person
in the building with the least reservoir engineering. **Any Forge repositioning must sit beside
SEPAL, not on top of it.**

**Second, what the sector actually pays for.** Two things stood out, and only one of them is
crowded.

*Crowded: production data management.* Peloton (ProdView), Quorum, Enverus, and P2 own this, all
contact-sales, and ProdView explicitly ships "pre-built report templates for state oil and gas
commissions, federal agencies, and environmental regulators"
([peloton.com/products/production-data-lifecycle/prodview](https://www.peloton.com/products/production-data-lifecycle/prodview)).
Quorum has consolidated the North American upstream segment through acquisitions. Market-size
estimates for oil-and-gas data management software are wildly inconsistent across analyst firms —
$34.2bn (2024) → $156.3bn (2034) at 16.4% CAGR from one, $18.45bn (2024) → $31.63bn (2035) at 5.02%
from another ([Global Insight Services](https://www.globalinsightservices.com/reports/oil-and-gas-data-management-software-market/);
[Market Research Future](https://www.marketresearchfuture.com/reports/oil-and-gas-data-management-software-market-26684)).
A 3x spread between "market size" reports is itself a finding: **treat all of these numbers as
unusable for decisions.** They are sold to people who want a big number in a slide.

*Uncrowded, and Nigeria-specific: the regulatory submission itself.* Nigerian operators face a
recurring, mandatory, deadline-driven reporting load to four separate bodies, and the tooling gap is
in **assembling, checking, approving and evidencing the submission** — not in the underlying
engineering:

- **NUPRC / NPMS.** The National Production Monitoring System is an electronic platform that
  "replaced the paper-based report"; all oil producing companies submit production data through the
  portal, monthly, feeding royalty calculation and national production figures
  ([nuprc.gov.ng/npms](https://www.nuprc.gov.ng/npms);
  [NUPRC NPMS page](https://www.nuprc.gov.ng/national-production-monitoring-system-npms/)).
  Monthly volume reporting is mandated, with electronic submittals
  ([Global Law Experts, Nigeria O&G lifecycle compliance](https://globallawexperts.com/from-exploration-to-decommissioning-a-guide-to-regulatory-compliance-in-nigerias-oil-and-gas-lifecycle/)).
- **NEITI.** Covered entities receive data collection templates and submit through NEITI's Audit
  Management System; audits reconcile the companies' **Hydrocarbon Flows Template** against
  NUPRC-reconciled sign-off documents ([neiti.gov.ng](https://neiti.gov.ng/);
  [NEITI 2023 Oil & Gas Industry Audit, Sept 2024](https://eiti.org/sites/default/files/2024-09/Final%20Report_NEITI_OGA_2023_Final_26_Sept_2024.pdf)).
  Note the shape: *template in, reconciled sign-off attached, submitted, audited.* That is a
  four-step approval artefact, which is exactly the pattern this platform already implements.
- **NCDMB / NOGICD Act.** Every operator must submit a Nigerian Content Plan under ss. 7–8 of the
  Act, and any project or contract of **$1m or above** requires an Employment and Training Plan
  approved by the Board. The portal (NOGIC JQS) has 11,445 registered companies including 115
  operators. Non-compliance risks "project withdrawal, suspension and criminal prosecution," and
  **expired or misapplied Nigerian Content Equipment Certificates cause automatic disqualification
  from tenders** ([NCDMB Lagos midstream workshop](https://ncdmb.gov.ng/ncdmb-holds-lagos-midstream-workshop-charges-operators-on-compliance-new-policies/);
  [Azaka Associates, NOGICD guide](https://azaka-associates.com/navigating-local-content-compliance-under-the-nogicd-act/)).
  "A certificate expiring quietly costs you a tender" is about as clean a paid pain as exists.
- **NMDPRA** for midstream/downstream licensing and HSE alignment
  ([Supportdesk, Jan 2026](https://supportdesk.ng/2026/01/23/navigating-nuprc-and-nmdpra-compliance-guide/)).

**Adjacent paid category with published prices, for calibration:** EHS/compliance software. Intelex
Essentials starts at **$49/user/mo**, small-business deployments from **$500/mo**, 1,000+ users
"upwards of $10,000/mo"; Cority from **$600/mo**, implementations $5,000–$50,000; enterprise EHS
platforms $30,000–$200,000+/yr
([PricingNow on Intelex](https://pricingnow.com/question/intelex-pricing/);
[SmartQHSE, Best EHS Software 2026](https://www.smartqhse.com/safety-blog/best-ehs-software-2026)).
So: **compliance workflow software is a category where a $10k–$50k/yr contract is normal and
unremarkable.** That is a survivable number for one developer. No-code ML is not.

### A.5 Repositioning options for Forge

Three options, in order of my confidence.

---

#### Option 1 (recommended) — Forge becomes **Assurance**: the regulatory submission workspace

**What it becomes.** The place a recurring mandatory submission is assembled, checked, approved by a
named person, filed, and evidenced. Concretely: upload or pull the period's data → validate it
against a stored template schema for the target body (NUPRC NPMS, NEITI Hydrocarbon Flows, NCDMB
content plan) → see exactly which rows and fields fail → generate the submission artefact →
route to a named approver who cannot approve their own submission → keep an immutable, timestamped
record of who signed what, with the input data attached.

**Who buys it.** The person accountable for the filing: a Regulatory Compliance / Government
Relations manager or Production Accountant at an operator, or the compliance lead at a service firm
carrying NCDMB obligations. Not an engineering manager, not a data scientist. This is a named role
with a personal, career-level exposure to a missed deadline.

**Why it wins.** Three reasons, in order of strength:
1. **It is the pattern the platform already proved.** Pulse's whole architecture is
   *pull data → generate a decision artefact → route to a named approver → refuse self-approval*.
   Assurance is that engine pointed at a different input. The approval workflow, the identity
   service, the named-lead model, the PDF generation (`services/pulse/app/services/pdf.py`), and the
   notification chain already exist and are already tested.
2. **It sits beside SEPAL rather than against it.** SEPAL produces the numbers; Assurance files
   them and proves who signed off. It can consume SEPAL output as an input — a complement, and a
   plausible upsell into an existing customer base rather than a new sales motion.
3. **Incumbents cover the wrong regulators.** ProdView ships templates for US state commissions and
   federal agencies. Nobody's shipped template set is NUPRC/NEITI/NCDMB-shaped. Localisation is a
   genuine moat here in a way that "better models" never was.

**What must be built.** A template/schema registry (a regulator form is a column spec plus
validation rules); a validation engine reporting per-row and per-field failures; artefact
generation; the approval routing (mostly liftable from Pulse); an audit log designed to be shown to
an auditor. Forge's existing dataset upload, preview, ownership and pagination are step one and
survive intact. **The 5 MB cap must go** — a monthly production submission will exceed it.

**Evidence.** NPMS mandatory monthly electronic submission; NEITI template + reconciled sign-off
workflow; NOGICD Act s.7–8 plans and the $1m Employment and Training Plan threshold; NCEC expiry
causing tender disqualification; EHS-adjacent compliance software clearing $10k–$50k/yr. All cited
in A.4.

**Risk.** Regulator formats are not published as clean machine-readable specs, and they change.
Every template is manual reverse-engineering work, and if a format changes and Assurance produces an
invalid filing, the liability conversation is unpleasant. Mitigate by positioning as
*prepare-check-approve-evidence*, explicitly **not** as an accredited filing channel.

---

#### Option 2 — Forge becomes **the tabular Q&A layer over data the company already has**

**What it becomes.** Upload or connect a dataset; ask questions in English; get answers with the
query shown. Forge's current CSV primitive plus an LLM.

**Who buys it.** Nobody, separately. This is a feature, not a product.

**Why it might still be worth doing.** It is cheap — days, not months — and it is the single most
requested thing non-technical staff ask of any data tool.

**Why it probably loses.** Excel has Copilot, ChatGPT reads CSVs, and every BI vendor shipped this
in 2024–25. There is no defensible position and no price. **Build it as a feature inside Assurance
("why did this submission fail validation?") if at all. Do not make it the product.**

---

#### Option 3 — Retire Forge as a product; keep the service as a shared capability

**What it becomes.** The `forge` service stops being a product surface and becomes the platform's
dataset/file-ingestion capability that Assurance and Pulse both call. The Forge frontend is retired
or folded into the Assurance UI.

**Why it might win.** It is the lowest-risk, lowest-work option, and it removes an on-screen product
that honestly admits it does nothing. Two credible products beat one credible product plus one
placeholder.

**Cost.** Loses the "two products on one identity service" story, which was the original
architectural demonstration. That story is worth something internally, so Option 1 (which preserves
it) is preferable if there is time.

---

**Recommendation: Option 1, with Option 2's Q&A as a later feature inside it, and Option 3 as the
fallback if the regulatory-template research turns out to be a wall.** The first concrete step is
not code: it is getting one real NUPRC NPMS or NEITI template in hand and confirming it can be
expressed as a schema. If that fails, take Option 3.

---

## Part B — What third app, if any?

The reusable asset is not "an ML platform" or even "GitHub integration." It is this sequence, which
Pulse implements end to end and which is genuinely uncommon in small products:

> **pull data from a system people already use → compile it into a decision artefact → route it to a
> named accountable human → record an approve/reject decision → refuse self-approval → keep the
> evidence.**

Anything that fits that sentence is cheap for this platform to build and expensive for a generic SaaS
to bolt on. Five candidates, ranked by expected value for one developer.

---

### B.1 — **Evidence**: turn GitHub history into audit-ready change-management records
*(Strongest. Build this as a Pulse module, not a third app.)*

**The need.** SOC 2 control CC8.1 requires the entity to authorise, approve and implement changes.
"For most SaaS companies, GitHub is where the change-management control lives," and at audit time
"an auditor will pull a sample of merged pull requests and check that each went through required
review and protected branches"
([Strac, GitHub SOC 2 compliance, 2026](https://www.strac.io/blog/github-soc-2-compliance)).
The specific, dated pain: **GitHub retains audit logs for only 90 days while auditors require a full
year of evidence**, so logs must be streamed externally — otherwise teams are "screenshotting the
week before fieldwork"
([Strac](https://www.strac.io/blog/github-soc-2-compliance);
[GitProtect, 5 GitHub practices to pass SOC 2 and ISO 27001](https://gitprotect.io/blog/5-github-practices-to-pass-a-security-audit-for-soc2-and-iso-27001/)).

**Evidence it is paid for.** The compliance-automation category exists on exactly this problem and
charges flat annual fees: Vanta observed $7,500–$56,781/yr (median ~$20,000), Drata $9,649–$60,000/yr
(median ~$24,869), startup entry $3,000–$6,000/yr
([soc2auditors.org, Jul 2026](https://soc2auditors.org/insights/drata-pricing/)). A narrow product
doing only change-management evidence already exists (EvidentTrail markets "turn GitHub pull requests
and reviews into formal change records automatically",
[evidenttrail.com/solutions](https://evidenttrail.com/solutions)) — which is simultaneously proof of
demand and proof you are not first.

**Buyer.** Whoever owns the audit: a CTO at a 20–80 person software company, or a compliance/security
lead. Notably **not** an engineering manager, which means it does not collide with the
developer-metrics political problem at all.

**Why this platform has an edge.** Pulse already syncs GitHub commits, PRs, issues and reviews
(`services/pulse/app/services/github_client.py`, `sync.py`), already has a named-approver model with
self-approval refused, already generates PDFs (`services/pulse/app/services/pdf.py`), and already
has an identity service with roles. **The incremental build is a control mapping, a retention
guarantee, and an export.** This is the cheapest real product in this document.

**Build cost (one developer, extrapolated from the existing codebase — not a cited figure):**
roughly **3–5 weeks** for a defensible v1: durable long-retention storage of PR/review events, a
CC8.1-shaped report per period, an auditor-facing export, and evidence that the record cannot be
retroactively edited.

**Honest risk.** Vanta and Drata cover this as one control among a hundred, and buyers prefer one
platform over five point tools. Selling "just the change-management control" means either being much
cheaper, or being the tool for companies that already failed that specific control. Also: this
market is global and English-speaking, meaning no local-currency advantage and no local moat.

---

### B.2 — **Assurance**: the Nigerian regulatory submission workspace
*(Best fit for the company. This is Forge's repositioning from A.5, listed here because it is
equally valid as "the second real product.")*

**The need, evidence, and buyer:** see A.4 and A.5. Mandatory monthly NPMS electronic submission;
NEITI template-plus-sign-off audits; NOGICD Act Nigerian Content Plans and $1m Employment and
Training Plans; NCEC expiry causing automatic tender disqualification.

**The timing signal I did not expect to find.** Nigeria's 2025/2026 licensing round awarded 37 blocks
to **31 companies, overwhelmingly indigenous, with Shell, TotalEnergies, ExxonMobil, Eni and Equinor
absent from the winners' list**
([WithinNigeria, 23 Jul 2026](https://www.withinnigeria.com/2026/07/23/who-recently-won-nigerias-37-oil-blocks-licensing-full-list-of-31-companies-locations-and-what-happens-next/);
[CED Magazine, 23 Jul 2026](https://cedmagazineng.com/2026/07/23/indigenous-firms-dominate-oil-block-winners-as-federal-govt-targets-259m-signature-bonuses);
[NUPRC 2025 Licensing Round Plan](https://br2025.nuprc.gov.ng/media/3kii2exi/nigeria-2025-licencing-round-plan.pdf)).
**That is a cohort of new licensees, right now, who acquire full NUPRC/NEITI/NCDMB reporting
obligations and have no incumbent compliance tooling and no IOC parent's systems to inherit.** They
are also exactly CypherCrescent's addressable market, which means an existing sales channel.

**Build cost:** **8–12 weeks** for one regulator's submission flow end to end, most of it spent on
template fidelity rather than code (extrapolation).

**Honest risk.** Template drift and liability, as in A.5. Second risk: these new licensees are
cash-constrained and slow-paying (see C.4), so revenue arrives late even when the deal closes.

---

### B.3 — **Certification and permit expiry register with approval-to-renew**

**The need.** In Nigerian oil and gas, an expired certificate is a lost tender: NCDMB confirms
"expired or misapplied NCECs will lead to automatic disqualification from tenders"
([Azaka Associates](https://azaka-associates.com/navigating-local-content-compliance-under-the-nogicd-act/)),
and operators must hold NUPRC/NMDPRA permits, ISO 45001 and HSE certifications on live status
([Global Law Experts](https://globallawexperts.com/from-exploration-to-decommissioning-a-guide-to-regulatory-compliance-in-nigerias-oil-and-gas-lifecycle/);
[NUPRC safety guidelines](https://www.nuprc.gov.ng/safety-environment/)).

**Evidence it is paid for, with real prices.** This is a small but genuinely transacted category:
Remindax runs **$49/mo to $499/mo**; VendorProof paid plans from **$12/mo** with a free tier of 10
vendors; MyCOI tiers around **$200–$400/mo**; contractor-prequalification platforms like ComplyFlow
sell document-authenticity plus expiry monitoring
([Remindax roundup, 2026](https://blog.remindax.com/top-certification-expiration-tracking-software/);
[Certificial comparison, 2026](https://www.certificial.com/blog-post/we-compared-7-best-coi-tracking-software-in-depth-feedback-and-review);
[ComplyFlow](https://www.complyflow.com/enterprise/company-prequalification-and-compliance-software)).

**Buyer.** Contracts/tendering manager, or QA/HSE manager.

**Why this platform has an edge.** Almost none, technically — it is a table with dates and a cron
job. Its edge is being *inside* the same login as Assurance and *pre-loaded with the Nigerian
certificate types* (NCEC, NOGIC JQS registration, NUPRC permits) that no US COI tool knows about.

**Build cost:** **2–3 weeks** as a module. Do not build it standalone.

**Honest risk.** The price ceiling is genuinely low ($50–$500/mo), and the honest alternative is a
spreadsheet with calendar reminders, which is free and works. **This is a feature that closes an
Assurance deal, not a product.**

---

### B.4 — Monthly client project report for engineering consultancies, with client sign-off

**The need.** Consultancies bill against monthly progress reports that a client representative must
accept. Today that is Word documents and email threads, and disputes about what was agreed are what
delays payment — which matters acutely in a sector where indigenous service firms already
"mobilise equipment, manpower, logistics, materials, and working capital long before payments are
received" ([Africa Oil+Gas Report, Apr 2026](https://africaoilgasreport.com/2026/04/in-the-news/beyond-compliance-the-quiet-threat-to-nigerias-local-content-success/)).

**Why it fits the pattern.** Pull from the systems the work already lives in → compile the monthly
report → route to the client's named representative → record acceptance → attach it to the invoice.
Pulse is already 70% of this; the only new concept is an **external** approver.

**Buyer.** The consultancy's project or commercial manager. CypherCrescent itself is one, which
makes it testable in-house immediately.

**Build cost:** **4–6 weeks**, dominated by external-user access (scoped magic-link identities for
client approvers) — which is real identity-service work, not cosmetic.

**Honest risk.** This is professional-services automation, a category with entrenched incumbents
(Kantata, Certinia, plus every accounting suite). Also: letting external parties into the identity
service is a security surface expansion, and the backlog already flags that tokens still live in
`localStorage` (`docs/backlog.md`) — that must be fixed before any external user gets a login.

---

### B.5 — E-invoicing compliance for the Nigerian FIRS/NRS mandate
*(Highest apparent urgency, and I recommend against it.)*

**The need is undeniably real and dated.** Nigeria's National e-Invoicing and Electronic Fiscal
System rolled out for large taxpayers from **1 Nov 2025** (extended from Aug 2025) and for all
VAT-registered businesses including SMEs from **1 Jan 2026**, with a compliance deadline for large
taxpayers of **31 Jul 2026**. Businesses must onboard to the NRS **Merchant Buyer Solution**,
integrate through **approved Access Point Providers or Systems Integrators**, and transmit invoices
carrying a valid **Invoice Reference Number**
([VATupdate, 9 Sep 2025](https://www.vatupdate.com/2025/09/09/firs-extends-e-invoicing-compliance-deadline-for-large-nigerian-taxpayers-to-november-2025/);
[Nairametrics, 19 Jul 2026](http://nairametrics.com/2026/07/19/nrs-sets-july-31-deadline-for-large-taxpayers-e-invoicing-adoption/);
[Mondaq, NRS compliance reminder](https://www.mondaq.com/nigeria/tax-authorities/1820316/nrs-issues-compliance-reminder-for-large-taxpayers-under-the-e-invoicing-electronic-fiscal-system-efs-regime);
[EY tax alert](https://www.ey.com/en_gl/technical/tax-alerts/nigerias-federal-inland-revenue-service-rolls-out-e-invoicing-platform)).

**Why not to build it.** Three reasons: (1) the transmission path is **gated by government
accreditation** as an Access Point Provider — you cannot ship this from a laptop; (2) the deadline has
largely already passed, so the land-grab window is closed and incumbents (tax software vendors,
ERP integrators, the big four) have taken it; (3) it is finance/tax software, not engineering
software — no domain adjacency, no reuse of Pulse's pattern beyond superficial resemblance.

**Record it as evidence about the market, not as a plan.** It proves Nigerian firms *do* buy
compliance software under regulatory pressure, which supports B.2.

---

### Part B verdict

**Do not build a third app. Build B.1 as a Pulse module and B.2 as Forge's replacement, with B.3 as
a feature inside B.2.** The platform's problem is not too few products; it is one product that
works and one that doesn't. Adding a third surface before the second one is real makes the honest
"this isn't built yet" screens multiply.

---

## Part C — Making money

### C.1 and C.2 — Engineering reporting is a real paid category, and it is priced per developer

Yes. This is the clearest "someone will pay" finding in the whole document, and it is priced in a way
a single developer can quote against.

**Published rate cards (fetched directly from vendor pricing pages, 2026-08-17):**

| Vendor | Price | Terms |
|---|---|---|
| **LinearB** | **$29/contributor/mo** (Essentials), **$59/contributor/mo** (Enterprise), both billed annually | Essentials has a **30 billable-user minimum**; Enterprise a 50-user minimum. No free tier, 45-day trial ([linearb.io/pricing](https://linearb.io/pricing)) |
| **Swarmia** | Free under 10 developers; Lite ~€20/dev/mo; **Standard €42/dev/mo billed annually (€49 monthly)** | Self-serve, published ([swarmia.com/pricing](https://swarmia.com/pricing/); figures via [Pensero comparison](https://pensero.ai/blog/linearb-vs-swarmia) and [Vendr](https://www.vendr.com/marketplace/swarmia), both read 2026-08-17 — I could not get the raw pricing page to render, see "could not verify") |
| **Jellyfish** | No list price. **$35,920 median annual contract across 91 recorded purchases**, deals from ~$16,500; effective ~$49/contributor/mo at the top of the band | Contact sales ([Vendr](https://www.vendr.com/marketplace/jellyfish); [CodePulse analysis](https://codepulsehq.com/guides/jellyfish-pricing-review)) |
| **DX** | No list price, enterprise contracts | ([Vendr](https://www.vendr.com/marketplace/dx)) |

Cross-check from actual transactions: Swarmia's median annual contract is **$14,695** (range
$7,465–$26,536), and a verified 60-developer deal came in at **$27,000/yr, about $450/developer/year**
([Vendr, read 2026-08-17](https://www.vendr.com/marketplace/swarmia)).

**What this tells you about Pulse's pricing shape.** The category has converged on
**per-contributor-per-month with a seat floor**, landing between **$25 and $50 per developer per month**,
and real contracts settle at **$300–$600 per developer per year** after discounting. There is a free
tier below ~10 developers because nobody can sell to a 6-person team profitably. LinearB's 30-seat
minimum is the honest admission: **the smallest viable customer in this category is about 30
engineers.** That is a hard constraint on Pulse-as-a-product and the single most important number in
Part C.

Note the alternative shapes that exist for the "internal tool turned product" pattern, since Pulse
does not have to copy per-seat: compliance-automation tools (Vanta, Drata) sell **flat annual
contracts** — observed Vanta $7,500–$56,781/yr (median ~$20,000), Drata $9,649–$60,000/yr (median
~$24,869), with startup entry points quoted at $6,000/yr and $3,000/yr respectively
([soc2auditors.org, Jul 2026](https://soc2auditors.org/insights/drata-pricing/)). A flat annual
"per organisation" price decoupled from headcount is the better fit for a first customer with 20–40
engineers, because per-seat maths at that size produces a number too small to be worth invoicing.

### C.3 The developer-productivity-measurement backlash — and whether Pulse's restraint is worth money

The backlash is real, well-documented, and Pulse's design is on the right side of it. **Whether that
converts into purchases is a different question, and the honest answer is: it is a
qualification filter, not a reason to buy.**

**The backlash, documented:**

- McKinsey published a developer-productivity measurement framework in **Aug 2023**, claiming ~20
  companies already used it. Gergely Orosz and Kent Beck published a joint rebuttal on
  **29 Aug 2023** across both their newsletters
  ([newsletter.pragmaticengineer.com](https://newsletter.pragmaticengineer.com/p/measuring-developer-productivity);
  [newsletter.kentbeck.com](https://newsletter.kentbeck.com/p/measuring-developer-productivity)).
  Their central charge: nearly all of McKinsey's metrics "measure effort or output" rather than
  outcomes, and the framework is "absurdly naive"; they concluded it would "most likely do far more
  harm than good to organizations." A follow-up Part 2 and wide coverage in LeadDev followed.
- On DORA and SPACE: DORA's own creator, Nicole Forsgren, frames DORA as "an implementation of
  SPACE" and warns that any single measured output gets gamed once developers know it is measured;
  senior engineers legitimately show low PR counts because they spend time unblocking others,
  mentoring, and doing architecture ([Pragmatic Engineer interview with
  Forsgren](https://newsletter.pragmaticengineer.com/p/developer-productivity-with-dr-nicole);
  [DX on SPACE](https://getdx.com/blog/space-metrics/)). The consistent expert position is
  *team-level aggregate, constellation of metrics, never individual ranking.*
- The commercial proof that this is a live buyer conversation: Swarmia — a company that sells this
  software — published "So, you'd like to stack rank your developers?" on **26 Sep 2025**, opening
  with: *"Sometimes people approach using software engineering intelligence tools with the mindset
  of 'just tell me who's my worst developer.'"*
  ([swarmia.com/blog](https://www.swarmia.com/blog/dont-stack-rank-your-developers/)).

**Read that last quote carefully, because it cuts both ways.** Swarmia is telling you that buyers
*do* walk in asking for individual rankings. Swarmia refuses, and has built "we fix the system, not
measure individuals harder" into its brand identity
([swarmia.com](https://www.swarmia.com/)). So:

- **Pulse's no-scoring stance is table stakes at the credible end of the market, not a
  differentiator.** Swarmia already occupies the "ethical engineering metrics" position and got
  there first, with a marketing budget.
- **It does have real purchasing consequence in one direction: it protects the deal from dying.**
  The failure mode in this category is engineers finding out they are being individually scored and
  the tool getting killed politically. A tool that cannot rank individuals survives that meeting.
  That is a *retention and adoption* argument, not a *why we bought it* argument.
- **The thing buyers actually pay for is the artefact and the workflow**, not the ethics.
  Pulse's genuinely unusual features are the **named-lead human approval decision** and the
  **refusal to allow self-approval** — that is an auditable control, not a metrics philosophy.
  Nobody in the LinearB/Swarmia/Jellyfish set leads with an approval workflow. **Position Pulse as
  the report-and-sign-off system, and let the no-scoring stance be the reason it does not get
  sabotaged internally.**

**Extrapolation, labelled as such:** I found no survey or procurement document showing buyers
*requiring* "does not score individuals" as a purchase criterion. My read that it functions as a
deal-protector rather than a deal-maker is inference from Swarmia's positioning plus the McKinsey
episode, not a cited finding.

### C.4 Selling B2B SaaS in Nigeria and Africa

Viable, but not as a dollar-priced self-serve SaaS. The constraints are currency and collections,
not demand.

- **FX has repriced every dollar subscription.** A $1,000/yr service that cost about ₦471,000 in
  early 2023 costs roughly ₦1.53m now — a ~225% increase in naira terms
  ([BusinessDay NG](https://businessday.ng/technology/article/mtn-challenges-aws-google-with-naira-priced-cloud-services/)).
  Every Nigerian buyer has spent three years being trained to hate dollar-denominated software.
- **USD subscriptions have very limited uptake outside the largest enterprises**, because SMEs and
  mid-market firms hit CBN restrictions, card limits, and FX availability; the recommended entry
  route is naira invoicing through a local entity, collected via Paystack or Flutterwave
  ([Zozzah, SaaS market entry in Nigeria](https://zozzah.com/blog/saas-market-entry-nigeria)).
  The same source notes official CBN, parallel, and processor rates commonly sit 5–10% apart, so
  **naira pricing means you eat FX risk on every renewal.**
- The hyperscalers have already conceded the point: **AWS began accepting naira payments** and MTN
  launched naira-priced cloud specifically to attack that pain
  ([thecondia.com](https://thecondia.com/aws-naira-payments-nigeria-cloud-market/);
  [BusinessDay](https://businessday.ng/technology/article/mtn-challenges-aws-google-with-naira-priced-cloud-services/)).
  If AWS needs local-currency billing to sell in Nigeria, a one-person product certainly does.
- **Collections are the real killer in oil and gas services specifically.** Indigenous service
  companies routinely work on **contractor-financed terms, mobilising people and working capital
  long before payment arrives** ([Africa Oil+Gas Report, Apr
  2026](https://africaoilgasreport.com/2026/04/in-the-news/beyond-compliance-the-quiet-threat-to-nigerias-local-content-success/)).
  Selling annual software subscriptions into a sector with that payment culture means long DSO and
  aggressive discounting for upfront payment.

**Practical conclusion for pricing.** Price in USD, invoice in naira at a fixed rate reviewed
annually, collect annually in advance via Paystack/Flutterwave, and treat CypherCrescent as tenant
zero and reference customer rather than as the market. If the product is ever meant to earn real
money, the buyers are the **IOC and large-indigenous operator tier and the international arms of
service firms**, who can transact in dollars — not the SME tier.

---

## What I could not verify

Listed so nobody treats these as settled.

**Pricing I could not get from a primary source:**

- **Swarmia's exact rate card.** `swarmia.com/pricing` would not render its pricing table through the
  fetch tool (only nav and footer came back) on two attempts. The €20 / €42 / €49 figures come from
  a third-party comparison and Vendr, not from Swarmia. The Vendr *contract* data ($14,695 median,
  $27,000 for 60 developers) is independent of that and is the number I'd trust.
- **Obviously.AI / Zams paid-tier prices.** The legacy pricing page still lists tiers and their row
  limits but shows no monetary figures for any paid plan. I could not determine whether the page is
  maintained or a leftover from before the Zams rebrand — worth noting that a live pricing page for
  a product the company says it no longer sells is itself ambiguous.
- **Akkio, Pecan, Dataiku, DataRobot, Peloton, Quorum, Enverus, Jellyfish, DX, Vanta, Drata** — all
  contact-sales. Every figure I give for these is buyer-reported or aggregator-derived (Vendr,
  PriceLevel, soc2auditors.org), never a vendor rate card. Aggregator medians are directionally
  useful and individually unreliable.
- **What Nigerian operators actually pay for compliance or production software.** I found no
  contract values, no tender awards with figures, and no budget disclosures. The EHS numbers
  (Intelex $49/user/mo, Cority $600/mo, enterprise $30k–$200k/yr) are US/global list prices and I
  have **no evidence they transfer to Nigerian buyers** — given the FX findings in C.4, they
  probably don't at full price.

**Claims I could not confirm:**

- **Code Climate Velocity's current status.** Searches returned only competitor "alternatives to"
  pages, which is weakly suggestive of a sunset but proves nothing. Haystack, Waydev and Sleuth are
  all still referenced as live in 2026 comparisons; I found no acquisition or shutdown news for any
  of them and did not confirm they are healthy either.
- **Whether any buyer has ever required "does not score individuals" as a purchase criterion.** No
  survey, RFP, or procurement document found. My C.3 conclusion that it protects deals rather than
  wins them is labelled extrapolation.
- **Whether NUPRC NPMS, NEITI and NCDMB templates can actually be expressed as machine-readable
  schemas.** This is the load-bearing assumption under the entire Assurance recommendation and I
  could not test it: NPMS is behind an operator login, and the NEITI templates I found were embedded
  in PDF audit reports rather than published as blank forms. **Verify this before writing code.**
  If the templates are free-form Excel with per-company variation, Assurance is much harder than
  A.5 implies and Option 3 (retire Forge) becomes correct.
- **Whether NUPRC operates a separate "Petroleum Revenue Management System" alongside NPMS.** One
  secondary source (Global Law Experts) refers to electronic submittals via PRMS; NUPRC's own pages
  describe NPMS. These may be the same system, two systems, or one renamed. Unresolved.
- **Whether CypherCrescent's leadership would sanction a compliance product**, given it is adjacent
  to SEPAL's customer base. This is a conversation, not a research question, but it gates everything
  in A.5 and B.2.
- **Oil-and-gas data-management market size.** Analyst estimates for 2024 ranged from $18.45bn to
  $34.2bn and 2034–35 forecasts from $31.63bn to $156.3bn — a roughly 3x and 5x spread. I could not
  reconcile them and do not believe any of them. Do not cite these numbers to anyone.
- **A specific "GAPLite" CypherCrescent product** referenced in my initial search: no evidence it
  exists. The product line I could confirm is SEPAL (Suite, WRM, Solver, Drilling & Intervention
  Activity Planner).

**Where sources conflict, and how I resolved it:**

- *Is no-code ML a live buyer category?* SEO listicles (DataCamp, GROWAI, buildmvpfast) say yes and
  growing; vendor outcomes, product shutdown dates, and disappeared pricing pages say the buyer
  market collapsed. **I sided with the vendor outcomes.** Content marketing about a category is not
  evidence of purchasing in it.
- *Is AutoML "dead"?* Dinsmore (Mar 2026) says commercial AutoML is dead outright; the open-source
  survey literature says it evolved into LLM-driven agents and remains technically vital. **Both are
  right about different things** — the libraries thrive, the businesses selling access to them do
  not. That distinction is the whole finding.
- *Obviously.AI's status.* Crunchbase, the founder's own announcement, and the Zams blog all confirm
  the rebrand and pivot; the old pricing page is still live. **I treated the company's own
  announcement as authoritative.**

**Build-cost estimates in Part B (3–5 weeks, 8–12 weeks, 2–3 weeks, 4–6 weeks) are my extrapolation
from reading this codebase, not cited benchmarks.** They assume one developer, existing Pulse
patterns reused, and no external-integration surprises.

---

## Method note

Research was done with web search and page fetches on 2026-08-17. No Firecrawl CLI was present on
this machine, so vendor pages were fetched directly; three pricing pages (Swarmia, Google Cloud
product page, LinearB's marketing shell) returned partial content, and where that happened it is
flagged above. Repository claims cite file paths in this repo rather than URLs.
