import { describe, expect, it } from "vitest";
import type { VueWrapper } from "@vue/test-utils";
import type { PersonaResponse, ReportResponse } from "~/types/api";
import { formatDate } from "~/utils/format";
import { apiError, flush, mountPage } from "./pageHarness";
import type { ApiCall } from "./pageHarness";
import { makeMember, makePersona, makePreset, makeReport, makeRepo, makeSubject, makeUser } from "./fixtures";

/* /reports/adhoc is a long form in front of a slow, rate-limited, chargeable request.
   Two things therefore matter more than anything else on it: it must not send something
   the API is going to refuse, and it must never lose what was typed into it. */

const ME = makeUser({ id: 1042, first_name: "Ada", last_name: "Nwosu" });
const REPOS = [makeRepo({ id: 4, full_name: "acme/pulse-api" })];
const TEAMMATES = [makeMember({ user_id: 1043, first_name: "Tunde", last_name: "Balogun" })];

const PERSONAS = [
  makePreset({ id: 1, name: "Concise" }),
  makePersona({ id: 21, name: "Weekly note", is_default: true }),
  makePersona({ id: 22, name: "For the board", audience: "executive" }),
];

interface State {
  personas: PersonaResponse[];
  created: ReportResponse;
  /** Thrown by POST /reports/adhoc instead of returning a report. */
  generateError?: unknown;
}

function stub(over: Partial<State> = {}) {
  const state: State = {
    personas: PERSONAS,
    created: makeReport({ id: 900, kind: "adhoc", status: "draft" }),
    ...over,
  };

  const bodies: Record<string, unknown>[] = [];

  function api(call: ApiCall): unknown {
    const { path, method, body } = call;

    if (path === "/personas" && method === "GET") {
      return { items: state.personas, total: state.personas.length, limit: 100, offset: 0 };
    }
    if (path === "/reports/adhoc" && method === "POST") {
      bodies.push(body as Record<string, unknown>);
      if (state.generateError) throw state.generateError;
      return state.created;
    }
    throw new Error(`unhandled ${method} ${path}`);
  }

  return { state, api, bodies };
}

function open(over: Partial<State> = {}, options: Record<string, unknown> = {}) {
  const { state, api, bodies } = stub(over);
  return mountPage({
    api,
    me: ME,
    repositories: REPOS,
    teammates: TEAMMATES,
    page: "adhoc",
    ...options,
  }).then((page) => ({ ...page, state, bodies }));
}

function selectNamed(wrapper: VueWrapper, label: string, index = 0) {
  const found = wrapper.findAllComponents({ name: "Select" }).filter((c) => c.props("label") === label);
  if (!found[index]) throw new Error(`no <Select label="${label}"> #${index} on the page`);
  return found[index]!;
}

/** Fill the form in with one valid Pulse-user contributor and a sane range. */
async function fillOne(wrapper: VueWrapper) {
  selectNamed(wrapper, "Which person this section is about").vm.$emit("update:modelValue", "1042");
  await wrapper.get('[data-test="range-start"]').setValue("2026-08-01");
  await wrapper.get('[data-test="range-end"]').setValue("2026-08-20");
  await flush();
}

describe("/reports/adhoc · the repository", () => {
  it("offers a tracked repository or a typed name, never both at once", async () => {
    const { wrapper } = await open();

    expect(wrapper.find('[data-test="repo-select"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="repo-input"]').exists()).toBe(false);

    await wrapper.get('[data-test="mode-live"]').setValue();
    await flush();

    expect(wrapper.find('[data-test="repo-select"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="repo-input"]').exists()).toBe(true);
  });

  it("says which mode reads synced data and which one goes to GitHub", async () => {
    const { wrapper } = await open();
    const text = wrapper.text();
    expect(text).toMatch(/already synced/i);
    expect(text).toMatch(/fetched from GitHub during the request/i);
  });

  it("sends repo_id in one mode and repo_full_name in the other, never both", async () => {
    const tracked = await open();
    await fillOne(tracked.wrapper);
    await tracked.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();

    expect(tracked.bodies[0]).toMatchObject({ repo_id: 4 });
    expect(tracked.bodies[0]).not.toHaveProperty("repo_full_name");

    const live = await open();
    await live.wrapper.get('[data-test="mode-live"]').setValue();
    await live.wrapper.get('[data-test="repo-input"]').setValue("cyphercrescent/pulse");
    await fillOne(live.wrapper);
    await live.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();

    expect(live.bodies[0]).toMatchObject({ repo_full_name: "cyphercrescent/pulse" });
    expect(live.bodies[0]).not.toHaveProperty("repo_id");
  });

  it("refuses junk in place of owner/name before the API has to", async () => {
    const { wrapper, bodies } = await open();
    await wrapper.get('[data-test="mode-live"]').setValue();
    await fillOne(wrapper);

    for (const junk of ["not a repo", "acme", "acme/", "/pulse", "-acme/pulse", "acme/pulse."]) {
      await wrapper.get('[data-test="repo-input"]').setValue(junk);
      await flush();
      expect(wrapper.find('[data-test="repo-invalid"]').exists()).toBe(true);
      expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeDefined();
    }

    // A github.com URL or a deep link is a repository somebody pasted, so it is reduced
    // rather than refused — the same rule /chat already applies to the same field.
    for (const pasted of ["https://github.com/acme/pulse-api", "github.com/acme/pulse-api/tree/main/app", "git@github.com:acme/pulse-api.git"]) {
      await wrapper.get('[data-test="repo-input"]').setValue(pasted);
      await flush();
      expect(wrapper.find('[data-test="repo-invalid"]').exists()).toBe(false);
      expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeUndefined();
    }

    await wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(bodies[0]).toMatchObject({ repo_full_name: "acme/pulse-api" });
  });
});

describe("/reports/adhoc · the contributors", () => {
  it("will not send a report with nobody in it", async () => {
    const { wrapper } = await open();

    expect(wrapper.findAll('[data-test="subject-row"]')).toHaveLength(1);
    expect(wrapper.get('[data-test="subject-count"]').text()).toContain("0 of 10");
    expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-test="problems"]').text()).toMatch(/at least one contributor/i);
  });

  it("stops at ten, which is the API's own cap", async () => {
    const { wrapper } = await open();

    for (let i = 0; i < 12; i += 1) {
      const add = wrapper.get('[data-test="subject-add"]');
      if (add.attributes("disabled") !== undefined) break;
      await add.trigger("click");
      await flush();
    }

    expect(wrapper.findAll('[data-test="subject-row"]')).toHaveLength(10);
    expect(wrapper.get('[data-test="subject-add"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-test="subject-cap"]').text()).toContain("10 is the most");
  });

  it("keeps at least one row on screen, so the form never empties itself", async () => {
    const { wrapper } = await open();
    expect(wrapper.get('[data-test="subject-remove"]').attributes("disabled")).toBeDefined();

    await wrapper.get('[data-test="subject-add"]').trigger("click");
    await flush();
    await wrapper.findAll('[data-test="subject-remove"]')[1]!.trigger("click");
    await flush();

    expect(wrapper.findAll('[data-test="subject-row"]')).toHaveLength(1);
  });

  it("sends a Pulse person as a user_id and an outside collaborator as a github_login", async () => {
    const { wrapper, bodies } = await open();

    selectNamed(wrapper, "Which person this section is about").vm.$emit("update:modelValue", "1043");
    await wrapper.get('[data-test="subject-add"]').trigger("click");
    await flush();

    selectNamed(wrapper, "Whether this contributor has a Pulse account", 1).vm.$emit("update:modelValue", "github");
    await flush();
    await wrapper.get('[data-test="subject-login"]').setValue("octocat");
    await wrapper.get('[data-test="range-start"]').setValue("2026-08-01");
    await wrapper.get('[data-test="range-end"]').setValue("2026-08-20");
    await flush();

    await wrapper.get('[data-test="generate"]').trigger("click");
    await flush();

    expect(bodies[0]!.subjects).toEqual([{ user_id: 1043 }, { github_login: "octocat" }]);
  });

  it("does not count a row that is still empty", async () => {
    const { wrapper } = await open();
    await fillOne(wrapper);
    await wrapper.get('[data-test="subject-add"]').trigger("click");
    await flush();

    expect(wrapper.findAll('[data-test="subject-row"]')).toHaveLength(2);
    expect(wrapper.get('[data-test="subject-count"]').text()).toContain("1 of 10");
  });
});

describe("/reports/adhoc · the range", () => {
  it("allows exactly 180 days and refuses 181", async () => {
    const { wrapper } = await open();
    await fillOne(wrapper);

    await wrapper.get('[data-test="range-start"]').setValue("2026-01-01");
    await wrapper.get('[data-test="range-end"]').setValue("2026-06-30"); // 180 days
    await flush();
    expect(wrapper.find('[data-test="range-error"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="range-span"]').text()).toContain("the longest a report covers");
    expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeUndefined();

    await wrapper.get('[data-test="range-end"]').setValue("2026-07-01"); // 181
    await flush();
    expect(wrapper.get('[data-test="range-error"]').text()).toContain("at most 180 days");
    expect(wrapper.get('[data-test="range-error"]').text()).toContain("1 day too long");
    expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeDefined();
  });

  it("refuses an end date before the start date", async () => {
    const { wrapper } = await open();
    await fillOne(wrapper);
    await wrapper.get('[data-test="range-start"]').setValue("2026-08-20");
    await wrapper.get('[data-test="range-end"]').setValue("2026-08-01");
    await flush();

    expect(wrapper.get('[data-test="range-error"]').text()).toMatch(/end date is before the start date/i);
    expect(wrapper.get('[data-test="generate"]').attributes("disabled")).toBeDefined();
  });
});

describe("/reports/adhoc · the persona", () => {
  it("pre-fills the user's default", async () => {
    const { wrapper } = await open();
    expect(selectNamed(wrapper, "Which persona writes this report").props("modelValue")).toBe("21");
    expect(wrapper.get('[data-test="persona-scope-note"]').text()).toMatch(/Pre-filled with your default, Weekly note/);
  });

  it("overrides for this report only, and never writes the choice back as the default", async () => {
    const { wrapper, request, bodies } = await open();
    await fillOne(wrapper);

    selectNamed(wrapper, "Which persona writes this report").vm.$emit("update:modelValue", "22");
    await flush();

    const note = wrapper.get('[data-test="persona-scope-note"]').text();
    expect(note).toMatch(/this report only/i);
    expect(note).toContain("Weekly note");

    await wrapper.get('[data-test="generate"]').trigger("click");
    await flush();

    expect(bodies[0]).toMatchObject({ persona_id: 22 });
    // Nothing on this page may change the stored default.
    const wrote = request.mock.calls.some(([path, opts]) =>
      String(path).endsWith("/default") || ["PUT", "PATCH", "POST"].includes((opts as { method?: string })?.method ?? "") && String(path).startsWith("/personas"),
    );
    expect(wrote).toBe(false);
  });

  it("falls back to the built-in preset when the user has no default of their own", async () => {
    const { wrapper } = await open({ personas: [makePreset({ id: 1, name: "Concise" }), makePersona({ id: 22, name: "For the board" })] });
    expect(selectNamed(wrapper, "Which persona writes this report").props("modelValue")).toBe("1");
  });
});

describe("/reports/adhoc · generating", () => {
  it("shows a real waiting state and goes to the report on success", async () => {
    const { wrapper, push } = await open();
    await fillOne(wrapper);

    await wrapper.get('[data-test="generate"]').trigger("click");
    await nextTick();
    expect(wrapper.find('[data-test="waiting"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="waiting"]').text()).toMatch(/takes a while/i);

    await flush();
    expect(push).toHaveBeenCalledWith("/reports/900");
  });

  it("keeps every field when a generation fails", async () => {
    const { wrapper } = await open({ generateError: apiError(502, "boom") });

    await wrapper.get('[data-test="mode-live"]').setValue();
    await wrapper.get('[data-test="repo-input"]').setValue("acme/pulse-api");
    selectNamed(wrapper, "Whether this contributor has a Pulse account").vm.$emit("update:modelValue", "github");
    await flush();
    await wrapper.get('[data-test="subject-login"]').setValue("octocat");
    await wrapper.get('[data-test="range-start"]').setValue("2026-08-01");
    await wrapper.get('[data-test="range-end"]').setValue("2026-08-20");
    await flush();

    await wrapper.get('[data-test="generate"]').trigger("click");
    await flush();

    expect(wrapper.find('[data-test="failure"]').exists()).toBe(true);
    expect((wrapper.get('[data-test="repo-input"]').element as HTMLInputElement).value).toBe("acme/pulse-api");
    expect((wrapper.get('[data-test="subject-login"]').element as HTMLInputElement).value).toBe("octocat");
    expect((wrapper.get('[data-test="range-start"]').element as HTMLInputElement).value).toBe("2026-08-01");
    expect((wrapper.get('[data-test="range-end"]').element as HTMLInputElement).value).toBe("2026-08-20");
    expect(wrapper.get('[data-test="failure"]').text()).toMatch(/nothing above was cleared/i);
  });

  it("tells a private repository, a bad request, each rate limit and a dead provider apart", async () => {
    const forbidden = await open({
      generateError: apiError(403, "Pulse could not read acme/secret with your GitHub connection."),
    });
    await fillOne(forbidden.wrapper);
    await forbidden.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(forbidden.wrapper.get('[data-test="failure"]').text()).toContain("could not read acme/secret");
    expect(forbidden.wrapper.find('[data-test="connect-github"]').exists()).toBe(true);
    expect(forbidden.wrapper.get('[data-test="connect-github"]').attributes("href")).toBe("/sync");

    const invalid = await open({
      generateError: apiError(422, "Pulse doesn't know the GitHub login for user #77"),
    });
    await fillOne(invalid.wrapper);
    await invalid.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(invalid.wrapper.get('[data-test="failure"]').text()).toContain("doesn't know the GitHub login");
    expect(invalid.wrapper.find('[data-test="connect-github"]').exists()).toBe(false);

    // The hourly limit is raised by slowapi, whose body is {"error": …} and carries no
    // detail at all — which is exactly how it is told apart from the token budget.
    const hourly = await open({ generateError: apiError(429) });
    await fillOne(hourly.wrapper);
    await hourly.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(hourly.wrapper.get('[data-test="failure"]').text()).toMatch(/10 custom reports in an hour/i);

    const budget = await open({
      generateError: apiError(429, "You have used 60,000 of your 60,000 daily AI tokens. The allowance resets at 00:00 UTC."),
    });
    await fillOne(budget.wrapper);
    await budget.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(budget.wrapper.get('[data-test="failure"]').text()).toContain("daily AI tokens");
    expect(budget.wrapper.get('[data-test="failure"]').text()).not.toMatch(/an hour/i);

    const dead = await open({ generateError: apiError(502, "Report generation is unavailable right now.") });
    await fillOne(dead.wrapper);
    await dead.wrapper.get('[data-test="generate"]').trigger("click");
    await flush();
    expect(dead.wrapper.get('[data-test="failure"]').text()).toMatch(/AI provider did not answer/i);
  });
});

/* ── the report the form produces ──────────────────────────────────────────── */

const ADHOC = makeReport({
  id: 900,
  kind: "adhoc",
  status: "draft",
  author_user_id: 1042,
  repo_id: null,
  repo_full_name: "acme/untracked",
  week_start: null,
  range_start: "2026-06-01",
  range_end: "2026-08-20",
  persona_id: 22,
  summary_manager: "octocat\nShipped the parser.\n\nTunde Balogun\nReviewed the parser.",
  subjects: [
    makeSubject({
      id: 2,
      position: 1,
      subject_user_id: 1043,
      subject: { user_id: 1043, first_name: "Tunde", last_name: "Balogun", avatar_url: null, is_active: true },
      section: "Reviewed the parser.",
    }),
    makeSubject({
      id: 1,
      position: 0,
      subject_user_id: null,
      subject: null,
      subject_github_login: "octocat",
      section: "Shipped the parser.",
    }),
  ],
});

function openReport(report: ReportResponse, options: Record<string, unknown> = {}) {
  function api(call: ApiCall): unknown {
    const { path, method } = call;
    if (path === `/reports/${report.id}` && method === "GET") return report;
    if (path === `/reports/${report.id}/approvals`) return { items: [], total: 0, limit: 100, offset: 0 };
    if (path === `/reports/${report.id}/comments`) return { items: [], total: 0, limit: 100, offset: 0 };
    if (path === `/reports/${report.id}/submit`) return { ...report, status: "submitted" };
    if (path === "/personas") return { items: PERSONAS, total: PERSONAS.length, limit: 100, offset: 0 };
    if (path.startsWith("/activity/")) throw new Error(`the custom-report page must not ask for ${path}`);
    throw new Error(`unhandled ${method} ${path}`);
  }
  return mountPage({
    api,
    me: ME,
    repositories: REPOS,
    page: "report",
    params: { id: String(report.id) },
    ...options,
  });
}

describe("/reports/[id] · a custom report", () => {
  it("gives every contributor their own section, headed by name, in position order", async () => {
    // The subjects deliberately arrive out of order: position is what the reader is owed.
    const { wrapper } = await openReport(ADHOC);

    const headings = wrapper.findAll('[data-test="section-name"]').map((h) => h.text());
    expect(headings).toEqual(["octocat", "Tunde Balogun"]);

    const sections = wrapper.findAll('[data-test="section"]');
    expect(sections).toHaveLength(2);
    expect(sections[0]!.text()).toContain("Shipped the parser.");
    expect(sections[0]!.text()).not.toContain("Reviewed the parser.");
    expect(sections[1]!.text()).toContain("Reviewed the parser.");
    expect(sections[1]!.text()).not.toContain("Shipped the parser.");
  });

  it("never renders the merged summary as a fourth editable field", async () => {
    const { wrapper } = await openReport(ADHOC);
    // summary_manager is the two sections joined; showing it too would print both
    // people's work under one heading, which is the whole failure to avoid.
    expect(wrapper.text()).not.toContain("For the lead");
    expect(wrapper.text()).toContain("Executive summary");
  });

  it("says out loud that a merge is credited to whoever merged it", async () => {
    const { wrapper } = await openReport(ADHOC);
    const note = wrapper.get('[data-test="attribution-note"]');
    expect(note.text()).toMatch(/GitHub credits a merge to whoever merged it/i);
    expect(note.text()).toMatch(/more than one person/i);
    expect(note.text()).toMatch(/not a measure of productivity/i);
    // Visible prose, not a title attribute nobody opens.
    expect(note.attributes("title")).toBeUndefined();
  });

  it("shows the kind, the range, an untracked repository's name and the persona used", async () => {
    const { wrapper } = await openReport(ADHOC);

    // "adhoc" is the API's word and stays in the API. The heading is what a person reads.
    expect(wrapper.get('[data-test="report-kind"]').text()).toBe("Custom report");
    expect(wrapper.get('[data-test="report-scope"]').text()).toContain("acme/untracked");
    expect(wrapper.get('[data-test="report-scope"]').text()).toContain("not tracked by Pulse");
    // Locale-formatted, so the assertion is on the two dates the page was given.
    expect(wrapper.get('[data-test="report-scope"]').text()).toContain(
      `${formatDate("2026-06-01")} → ${formatDate("2026-08-20")}`,
    );
    expect(wrapper.get('[data-test="report-persona"]').text()).toContain("For the board");
  });

  it("submits a custom-report draft into the same approval flow", async () => {
    const { wrapper, request } = await openReport(ADHOC);

    const submit = wrapper.findAll("button").find((b) => b.text() === "Submit for review")!;
    expect(submit).toBeDefined();
    await submit.trigger("click");
    await flush();

    expect(request.mock.calls.some(([path, opts]) => path === "/reports/900/submit" && (opts as { method?: string })?.method === "POST")).toBe(true);
  });

  it("leaves a weekly report exactly as it was", async () => {
    const weekly = makeReport({ id: 341, kind: "weekly", week_start: "2026-08-03", author_user_id: 1042, status: "draft" });
    const { wrapper } = await mountPage({
      api: (call: ApiCall) => {
        if (call.path === "/reports/341") return weekly;
        if (call.path.startsWith("/reports/341/")) return { items: [], total: 0, limit: 100, offset: 0 };
        if (call.path === "/personas") return { items: PERSONAS, total: 3, limit: 100, offset: 0 };
        if (call.path.startsWith("/activity/")) {
          return {
            user_id: 1042, user: null, since: "2026-08-03",
            counts: { commits: 3, pull_requests: 1, reviews: 0, issues: 0 },
            recent_commits: [], recent_pull_requests: [], recent_reviews: [], recent_issues: [],
          };
        }
        throw new Error(`unhandled ${call.method} ${call.path}`);
      },
      me: ME,
      repositories: REPOS,
      page: "report",
      params: { id: "341" },
    });

    expect(wrapper.text()).toContain("Weekly report");
    expect(wrapper.text()).toContain("Week of");
    expect(wrapper.text()).toContain("For the lead");
    expect(wrapper.find('[data-test="sections"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="attribution-note"]').exists()).toBe(false);
  });
});
