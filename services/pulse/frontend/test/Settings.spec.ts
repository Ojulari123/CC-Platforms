import { describe, expect, it } from "vitest";
import type { VueWrapper } from "@vue/test-utils";
import type {
  BudgetResponse,
  CredentialResponse,
  EffectiveBudgetResponse,
  EffectiveCredentialResponse,
  PersonaResponse,
} from "~/types/api";
import { apiError, flush, mountPage } from "./pageHarness";
import type { ApiCall } from "./pageHarness";
import { makeBudget, makeCredential, makeEffective, makeEffectiveBudget, makePersona, makePreset, makeUser } from "./fixtures";

/* /settings holds the two things nobody else can set for you: how your reports read, and
   which API key pays for them. Most of what is asserted here is about the second one —
   a key the page shows back, logs, or leaves in a URL is a leak, and the only way to
   know it does none of those is to look. */

const ME = makeUser({ id: 1042, memberships: [] });
const ADMIN = makeUser({
  id: 1042,
  memberships: [{ dept_id: 3, dept_name: "Engineering", team_id: null, team_name: null, role: "admin" }],
});
const MEMBER = makeUser({
  id: 1042,
  memberships: [{ dept_id: 3, dept_name: "Engineering", team_id: null, team_name: null, role: "member" }],
});

const PRESETS = [
  makePreset({ id: 1, name: "Concise", length: "brief" }),
  makePreset({ id: 2, name: "Executive", audience: "executive" }),
  makePreset({ id: 3, name: "Technical Depth", technical_depth: "high" }),
];

interface State {
  personas: PersonaResponse[];
  credentials: CredentialResponse[];
  effective: EffectiveCredentialResponse;
  budgets: BudgetResponse[];
  effectiveBudget: EffectiveBudgetResponse;
  /** Thrown by PUT /settings/credentials instead of saving. */
  upsertError?: unknown;
  /** Thrown by PUT /settings/credentials/budgets instead of saving. */
  budgetError?: unknown;
  personaError?: unknown;
  defaultError?: unknown;
}

function stub(over: Partial<State> = {}) {
  const state: State = {
    personas: [...PRESETS],
    credentials: [],
    effective: makeEffective(),
    budgets: [],
    effectiveBudget: makeEffectiveBudget(),
    ...over,
  };

  let nextId = 500;

  function api(call: ApiCall): unknown {
    const { path, method, body } = call;

    if (path === "/personas" && method === "GET") {
      return { items: state.personas, total: state.personas.length, limit: 100, offset: 0 };
    }
    if (path === "/personas" && method === "POST") {
      if (state.personaError) throw state.personaError;
      const created = makePersona({ id: (nextId += 1), ...(body as object) });
      state.personas = [...state.personas, created];
      return created;
    }

    const one = /^\/personas\/(\d+)$/.exec(path);
    if (one && method === "PATCH") {
      if (state.personaError) throw state.personaError;
      const id = Number(one[1]);
      state.personas = state.personas.map((p) => (p.id === id ? { ...p, ...(body as object) } : p));
      return state.personas.find((p) => p.id === id);
    }
    if (one && method === "DELETE") {
      state.personas = state.personas.filter((p) => p.id !== Number(one[1]));
      return undefined;
    }

    const asDefault = /^\/personas\/(\d+)\/default$/.exec(path);
    if (asDefault && method === "PUT") {
      if (state.defaultError) throw state.defaultError;
      const id = Number(asDefault[1]);
      // The API clears the previous default in the same transaction; so does this.
      state.personas = state.personas.map((p) => ({
        ...p,
        is_default: p.owner_user_id !== null && p.id === id,
      }));
      return state.personas.find((p) => p.id === id);
    }

    // Declared before the credential routes: "budgets" would otherwise be read as an id.
    if (path === "/settings/credentials/budgets/effective") return state.effectiveBudget;
    if (path === "/settings/credentials/budgets" && method === "GET") return { items: state.budgets };
    if (path === "/settings/credentials/budgets" && method === "PUT") {
      if (state.budgetError) throw state.budgetError;
      const sent = body as { scope: string; daily_token_cap: number; owner_user_id?: number };
      const saved = makeBudget({
        id: state.budgets[0]?.id ?? (nextId += 1),
        scope: sent.scope,
        owner_user_id: sent.owner_user_id ?? null,
        daily_token_cap: sent.daily_token_cap,
      });
      state.budgets = [saved];
      state.effectiveBudget = { ...state.effectiveBudget, daily_token_cap: saved.daily_token_cap, source: "user" };
      return saved;
    }
    const budget = /^\/settings\/credentials\/budgets\/(\d+)$/.exec(path);
    if (budget && method === "DELETE") {
      state.budgets = state.budgets.filter((b) => b.id !== Number(budget[1]));
      state.effectiveBudget = {
        ...state.effectiveBudget,
        daily_token_cap: state.effectiveBudget.inherited_cap,
        source: state.effectiveBudget.inherited_source,
      };
      return undefined;
    }

    if (path === "/settings/credentials" && method === "GET") return { items: state.credentials };
    if (path === "/settings/credentials/effective") return state.effective;
    if (path === "/settings/credentials" && method === "PUT") {
      if (state.upsertError) throw state.upsertError;
      const sent = body as { provider: string; scope: string; key?: string; model: string | null; bypass_token_cap: boolean };
      // Mirrors the service: an absent key updates the existing row and leaves the
      // stored secret (and so its last four) alone.
      const existing = state.credentials.find((c) => c.scope === sent.scope && c.provider === sent.provider);
      if (sent.key === undefined && !existing) throw apiError(422, "An API key is required the first time you set one");
      const saved = makeCredential({
        ...(existing ?? {}),
        id: existing?.id ?? (nextId += 1),
        provider: sent.provider,
        scope: sent.scope,
        model: sent.model,
        bypass_token_cap: sent.bypass_token_cap,
        ...(sent.key === undefined ? {} : { last_four: sent.key.slice(-4) }),
      });
      state.credentials = [saved];
      return saved;
    }
    const credential = /^\/settings\/credentials\/(\d+)$/.exec(path);
    if (credential && method === "DELETE") {
      state.credentials = state.credentials.filter((c) => c.id !== Number(credential[1]));
      return undefined;
    }

    throw new Error(`unhandled ${method} ${path}`);
  }

  return { state, api };
}

function open(over: Partial<State> = {}, options: Record<string, unknown> = {}) {
  const { state, api } = stub(over);
  return mountPage({ api, me: ME, page: "settings", ...options }).then((page) => ({ ...page, state }));
}

function keys(over: Partial<State> = {}, options: Record<string, unknown> = {}) {
  return open(over, { query: { tab: "keys" }, ...options });
}

/** The Select components are a listbox, not a native <select>, so a test drives them the
    way the page does: by the model event, found by the accessible name. */
function selectNamed(wrapper: VueWrapper, label: string) {
  const found = wrapper
    .findAllComponents({ name: "Select" })
    .find((c) => c.props("label") === label);
  if (!found) throw new Error(`no <Select label="${label}"> on the page`);
  return found;
}

describe("/settings · personas", () => {
  it("shows the built-in presets apart from your own", async () => {
    const { wrapper } = await open({ personas: [...PRESETS, makePersona({ id: 21, name: "Weekly note" })] });

    expect(wrapper.findAll('[data-test="preset-row"]')).toHaveLength(3);
    expect(wrapper.findAll('[data-test="persona-row"]')).toHaveLength(1);
    expect(wrapper.find('[data-test="preset-badge"]').text()).toMatch(/built in/i);
  });

  it("offers a preset no edit, delete or make-default control — all three answer 403", async () => {
    const { wrapper } = await open({ personas: [...PRESETS, makePersona({ id: 21 })] });

    for (const row of wrapper.findAll('[data-test="preset-row"]')) {
      expect(row.find('[data-test="persona-edit"]').exists()).toBe(false);
      expect(row.find('[data-test="persona-delete"]').exists()).toBe(false);
      expect(row.find('[data-test="persona-make-default"]').exists()).toBe(false);
      // What it does offer is the one thing the API allows.
      expect(row.find('[data-test="persona-copy"]').exists()).toBe(true);
    }
    // Only the one persona that is actually yours carries the editing controls.
    expect(wrapper.findAll('[data-test="persona-edit"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-test="persona-delete"]')).toHaveLength(1);
  });

  it("copies a preset into a new persona of your own rather than editing it", async () => {
    const { wrapper, request } = await open();

    await wrapper.findAll('[data-test="persona-copy"]')[1]!.trigger("click");
    await flush();

    expect((wrapper.get('[data-test="persona-name"]').element as HTMLInputElement).value).toBe("Executive (mine)");

    await wrapper.get('[data-test="persona-save"]').trigger("click");
    await flush();

    const post = request.mock.calls.find(([path, opts]) => path === "/personas" && (opts as { method?: string })?.method === "POST");
    expect(post).toBeDefined();
    expect((post![1] as { body: Record<string, unknown> }).body).toMatchObject({
      name: "Executive (mine)",
      audience: "executive",
    });
    // Nothing was sent at the preset itself.
    const touchedPreset = request.mock.calls.some(([path]) => String(path).startsWith("/personas/2"));
    expect(touchedPreset).toBe(false);
  });

  /* The tab's own headline. Which persona writes your reports is the thing you open this
     screen to find out, so it is asserted the same way the API-key answer below is. */
  it("names the persona a report will actually be written with", async () => {
    const mine = await open({ personas: [...PRESETS, makePersona({ id: 21, name: "Weekly note", is_default: true })] });
    expect(mine.wrapper.get('[data-test="persona-effective"]').text()).toMatch(/written as Weekly note/i);

    const fallback = await open();
    expect(fallback.wrapper.get('[data-test="persona-effective"]').text()).toMatch(/built-in Concise preset/i);
  });

  // A database that never ran the preset seed returns an empty page; the dial line under
  // the headline reads off a persona that is not there.
  it("still renders when the API returns no personas at all", async () => {
    const { wrapper } = await open({ personas: [] });
    expect(wrapper.get('[data-test="persona-effective"]').text()).toMatch(/built-in Concise preset/i);
    expect(wrapper.findAll('[data-test="preset-row"]')).toHaveLength(0);
  });

  it("sets exactly one default, and shows it before the refetch lands", async () => {
    const { wrapper, request } = await open({
      personas: [
        ...PRESETS,
        makePersona({ id: 21, name: "Weekly note", is_default: true }),
        makePersona({ id: 22, name: "For the board" }),
      ],
    });

    expect(wrapper.findAll('[data-test="persona-default-badge"]')).toHaveLength(1);

    // The only "Make default" on screen belongs to the persona that is not the default.
    const buttons = wrapper.findAll('[data-test="persona-make-default"]');
    expect(buttons).toHaveLength(1);
    await buttons[0]!.trigger("click");
    await flush();

    expect(request.mock.calls.some(([path, opts]) => path === "/personas/22/default" && (opts as { method?: string })?.method === "PUT")).toBe(true);

    const badges = wrapper.findAll('[data-test="persona-default-badge"]');
    expect(badges).toHaveLength(1);
    const rows = wrapper.findAll('[data-test="persona-row"]');
    expect(rows.find((r) => r.find('[data-test="persona-default-badge"]').exists())!.text()).toContain("For the board");
  });

  it("says in plain words what the four dials produce, and follows a change to them", async () => {
    const { wrapper } = await open();

    await wrapper.get('[data-test="persona-new"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="persona-preview"]').text()).toContain("A short page");

    selectNamed(wrapper, "Length").vm.$emit("update:modelValue", "brief");
    selectNamed(wrapper, "Technical depth").vm.$emit("update:modelValue", "high");
    await flush();

    const preview = wrapper.get('[data-test="persona-preview"]').text();
    expect(preview).toContain("A few sentences");
    expect(preview).toContain("going down to specific changes");
  });

  it("puts a delete behind the shared dialog and keeps the persona until it is confirmed", async () => {
    const { wrapper, state } = await open({ personas: [...PRESETS, makePersona({ id: 21, name: "Weekly note" })] });

    await wrapper.get('[data-test="persona-delete"]').trigger("click");
    await flush();

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(state.personas.some((p) => p.id === 21)).toBe(true);

    (document.querySelector('[data-test="persona-delete-confirm"]') as HTMLElement).click();
    await flush();

    expect(state.personas.some((p) => p.id === 21)).toBe(false);
  });

  it("keeps everything typed when the API refuses a persona", async () => {
    const { wrapper } = await open({ personaError: apiError(409, "You already have a persona called Weekly note") });

    await wrapper.get('[data-test="persona-new"]').trigger("click");
    await wrapper.get('[data-test="persona-name"]').setValue("Weekly note");
    await wrapper.get('[data-test="persona-instructions"]').setValue("Name the pull request.");
    await wrapper.get('[data-test="persona-save"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="persona-error"]').text()).toContain("already have a persona");
    expect(wrapper.find('[data-test="persona-form"]').exists()).toBe(true);
    expect((wrapper.get('[data-test="persona-name"]').element as HTMLInputElement).value).toBe("Weekly note");
    expect((wrapper.get('[data-test="persona-instructions"]').element as HTMLTextAreaElement).value).toBe("Name the pull request.");
  });
});

describe("/settings · api keys", () => {
  const SECRET = "sk-ant-supersecret-0000-abcd";

  it("names which of the four sources a report will actually be billed to", async () => {
    const cases: [EffectiveCredentialResponse["source"], RegExp][] = [
      ["user", /your personal key/i],
      ["department", /your department's key/i],
      ["platform", /the platform key/i],
      ["none", /no key is set/i],
    ];
    for (const [source, copy] of cases) {
      const { wrapper } = await keys({ effective: makeEffective({ source }) });
      expect(wrapper.get('[data-test="effective"]').text()).toMatch(copy);
    }
  });

  it("shows a saved key as its last four digits and nothing more", async () => {
    const { wrapper } = await keys({
      credentials: [makeCredential({ last_four: "9f2c", provider: "anthropic", model: "claude-sonnet-4-5" })],
    });

    const row = wrapper.get('[data-test="credential-row"]');
    expect(row.find('[data-test="last-four"]').text()).toContain("9f2c");
    expect(row.text()).toContain("Anthropic");
    expect(row.text()).toContain("claude-sonnet-4-5");
  });

  it("sends the key in the body, never in a query string, and clears it once it is saved", async () => {
    const { wrapper, request } = await keys();

    await wrapper.get('[data-test="key-input"]').setValue(SECRET);
    await wrapper.get('[data-test="key-save"]').trigger("click");
    await flush();

    const put = request.mock.calls.find(([path, opts]) => path === "/settings/credentials" && (opts as { method?: string })?.method === "PUT")!;
    const opts = put[1] as { body: Record<string, unknown>; query?: unknown };
    expect(opts.body.key).toBe(SECRET);
    expect(opts.query).toBeUndefined();
    // Nothing else the page ever asks for may carry it either.
    for (const [path, o] of request.mock.calls) {
      expect(String(path)).not.toContain(SECRET);
      expect(JSON.stringify((o as { query?: unknown })?.query ?? null)).not.toContain(SECRET);
    }

    expect(wrapper.html()).not.toContain(SECRET);
    expect((wrapper.get('[data-test="key-input"]').element as HTMLInputElement).value).toBe("");
  });

  it("keeps the form and explains itself when a key is refused with a 422", async () => {
    const { wrapper } = await keys({
      upsertError: apiError(422, "That key was refused by anthropic"),
    });

    await wrapper.get('[data-test="key-model"]').setValue("claude-sonnet-4-5");
    await wrapper.get('[data-test="key-input"]').setValue(SECRET);
    await wrapper.get('[data-test="key-save"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="key-error"]').text()).toContain("refused");
    // The form is still standing, with what was typed into it.
    expect(wrapper.find('[data-test="key-input"]').exists()).toBe(true);
    expect((wrapper.get('[data-test="key-model"]').element as HTMLInputElement).value).toBe("claude-sonnet-4-5");
    // And the key is still not rendered anywhere, refused or not.
    expect(wrapper.html()).not.toContain(SECRET);
  });

  it("never types the key into the page as a readable field", async () => {
    const { wrapper } = await keys();
    expect(wrapper.get('[data-test="key-input"]').attributes("type")).toBe("password");
    expect(wrapper.get('[data-test="key-input"]').attributes("autocomplete")).toBe("off");
  });

  it("offers department scope to an admin of a department and to nobody else", async () => {
    const asAdmin = await keys({}, { me: ADMIN });
    expect(selectNamed(asAdmin.wrapper, "Who this key is for").props("options")).toEqual([
      { value: "user", label: "Just me" },
      { value: "department", label: "My department" },
    ]);

    const asMember = await keys({}, { me: MEMBER });
    expect(selectNamed(asMember.wrapper, "Who this key is for").props("options")).toEqual([
      { value: "user", label: "Just me" },
    ]);
    expect(asMember.wrapper.text()).toMatch(/needs you to be an admin of it/i);
  });

  it("sends a department key with the department it is for", async () => {
    const { wrapper, request } = await keys({}, { me: ADMIN });

    selectNamed(wrapper, "Who this key is for").vm.$emit("update:modelValue", "department");
    await flush();
    selectNamed(wrapper, "Which department this key is for").vm.$emit("update:modelValue", "3");
    await wrapper.get('[data-test="key-input"]').setValue(SECRET);
    await wrapper.get('[data-test="key-save"]').trigger("click");
    await flush();

    const put = request.mock.calls.find(([path, opts]) => path === "/settings/credentials" && (opts as { method?: string })?.method === "PUT")!;
    expect((put[1] as { body: Record<string, unknown> }).body).toMatchObject({ scope: "department", dept_id: 3 });
  });

  it("says honestly that the bypass never applies to the platform key", async () => {
    const { wrapper } = await keys();
    const label = wrapper.get('[data-test="bypass-toggle"]').element.closest("label")!;
    expect(label.textContent).toMatch(/only ever applies to a key you or your department supplied/i);
    expect(label.textContent).toMatch(/platform key are capped/i);
  });

  it("carries the bypass through to the request", async () => {
    const { wrapper, request } = await keys();

    await wrapper.get('[data-test="bypass-toggle"]').setValue(true);
    await wrapper.get('[data-test="key-input"]').setValue(SECRET);
    await wrapper.get('[data-test="key-save"]').trigger("click");
    await flush();

    const put = request.mock.calls.find(([path, opts]) => path === "/settings/credentials" && (opts as { method?: string })?.method === "PUT")!;
    expect((put[1] as { body: Record<string, unknown> }).body).toMatchObject({ bypass_token_cap: true });
  });

  it("flips the token cap straight from the row, with no key re-entered", async () => {
    const { wrapper, request, state } = await keys({
      credentials: [makeCredential({ id: 5, provider: "anthropic", model: "claude-sonnet-4-5", last_four: "9f2c" })],
    });

    const row = wrapper.get('[data-test="credential-row"]');
    expect(row.get('[data-test="credential-cap-label"]').text()).toMatch(/token cap applies/i);

    await row.get('[data-test="credential-cap-toggle"]').setValue(true);
    await flush();

    const put = request.mock.calls.find(([path, opts]) => path === "/settings/credentials" && (opts as { method?: string })?.method === "PUT")!;
    const sent = (put[1] as { body: Record<string, unknown> }).body;
    expect(sent).toMatchObject({ scope: "user", provider: "anthropic", bypass_token_cap: true });
    // The whole point: no secret is asked for and none is sent.
    expect("key" in sent).toBe(false);

    expect(state.credentials[0]!.bypass_token_cap).toBe(true);
    expect(state.credentials[0]!.last_four).toBe("9f2c");
    expect(wrapper.get('[data-test="credential-cap-label"]').text()).toMatch(/token cap bypassed/i);
  });

  it("turns the cap back on from the row too", async () => {
    const { wrapper, state } = await keys({
      credentials: [makeCredential({ id: 5, bypass_token_cap: true })],
    });

    expect(wrapper.get('[data-test="credential-cap-label"]').text()).toMatch(/token cap bypassed/i);
    await wrapper.get('[data-test="credential-cap-toggle"]').setValue(false);
    await flush();

    expect(state.credentials[0]!.bypass_token_cap).toBe(false);
    expect(wrapper.get('[data-test="credential-cap-label"]').text()).toMatch(/token cap applies/i);
  });

  it("carries a department key's dept_id through the row toggle", async () => {
    const { wrapper, request } = await keys(
      { credentials: [makeCredential({ id: 6, scope: "department", dept_id: 3, owner_user_id: null })] },
      { me: ADMIN },
    );

    await wrapper.get('[data-test="credential-cap-toggle"]').setValue(true);
    await flush();

    const put = request.mock.calls.find(([path, opts]) => path === "/settings/credentials" && (opts as { method?: string })?.method === "PUT")!;
    expect((put[1] as { body: Record<string, unknown> }).body).toMatchObject({ scope: "department", dept_id: 3, bypass_token_cap: true });
  });

  it("says what went wrong when the cap cannot be changed, rather than silently reverting", async () => {
    const { wrapper } = await keys({
      credentials: [makeCredential({ id: 5 })],
      upsertError: apiError(403, "nope"),
    });

    await wrapper.get('[data-test="credential-cap-toggle"]').setValue(true);
    await flush();

    expect(wrapper.get('[data-test="key-error"]').text()).toMatch(/cannot change the cap/i);
    expect(wrapper.get('[data-test="credential-cap-label"]').text()).toMatch(/token cap applies/i);
  });

  it("puts removing a key behind the shared dialog", async () => {
    const { wrapper, state } = await keys({ credentials: [makeCredential({ id: 5 })] });

    await wrapper.get('[data-test="credential-delete"]').trigger("click");
    await flush();
    expect(state.credentials).toHaveLength(1);

    (document.querySelector('[data-test="credential-delete-confirm"]') as HTMLElement).click();
    await flush();
    expect(state.credentials).toHaveLength(0);
  });
});

describe("/settings · the daily AI allowance", () => {
  it("says what the limit is and where it came from", async () => {
    const { wrapper } = await keys({
      effectiveBudget: makeEffectiveBudget({ daily_token_cap: 200000, source: "platform_default" }),
    });

    const panel = wrapper.get('[data-test="budget"]');
    expect(panel.text()).toContain("200,000");
    expect(wrapper.get('[data-test="budget-source"]').text()).toMatch(/platform default/i);
  });

  it("names the fallback when the limit is your own row", async () => {
    const { wrapper } = await keys({
      budgets: [makeBudget({ id: 11, daily_token_cap: 500000 })],
      effectiveBudget: makeEffectiveBudget({
        daily_token_cap: 500000,
        source: "user",
        inherited_cap: 200000,
        inherited_source: "platform_default",
      }),
    });

    const source = wrapper.get('[data-test="budget-source"]').text();
    expect(source).toMatch(/a limit set for you/i);
    expect(source).toContain("200,000");
  });

  it("calls a cap of 0 no limit rather than printing zero tokens", async () => {
    const { wrapper } = await keys({
      effectiveBudget: makeEffectiveBudget({ daily_token_cap: 0, source: "user", may_raise: true }),
    });

    expect(wrapper.get('[data-test="budget"]').text()).toMatch(/no daily ai limit/i);
    expect(wrapper.get('[data-test="budget"]').text()).not.toMatch(/\b0 tokens\b/);
  });

  /* may_raise false is somebody drawing on the platform key. You may only lift a limit on
     spend you are paying for, so the control would answer 403 and is not offered. */
  describe("when may_raise is false", () => {
    const LOCKED = makeEffectiveBudget({
      daily_token_cap: 200000, source: "platform_default", may_raise: false, show_figures: false,
    });

    it("shows the limit and explains it rather than offering a control", async () => {
      const { wrapper } = await keys({ effectiveBudget: LOCKED });

      expect(wrapper.get('[data-test="budget"]').text()).toContain("200,000");
      expect(wrapper.get('[data-test="cap-locked"]').text()).toMatch(/not yours to raise/i);
      expect(wrapper.find('[data-test="cap-edit"]').exists()).toBe(false);
      expect(wrapper.find('[data-test="cap-input"]').exists()).toBe(false);
      expect(wrapper.find('[data-test="cap-clear"]').exists()).toBe(false);
    });

    /* Same rule the API's own refusals follow: a token count is the model vendor's unit
       of accounting, and on the platform key it is somebody else's money being counted. */
    it("keeps today's token figure to whoever is paying for it", async () => {
      const locked = await keys({ effectiveBudget: LOCKED });
      expect(locked.wrapper.find('[data-test="budget-used"]').exists()).toBe(false);

      const paying = await keys({
        effectiveBudget: makeEffectiveBudget({ tokens_used_today: 12500, may_raise: true }),
      });
      expect(paying.wrapper.get('[data-test="budget-used"]').text()).toContain("12,500");
    });

    /* A user under a department key. The department's money is being spent on them, so
       the figures are theirs to see, but the cap is not theirs to raise. The two answers
       come from separate fields for exactly this case. */
    it("shows the figures without a raise control when show_figures is true", async () => {
      const { wrapper } = await keys({
        effectiveBudget: makeEffectiveBudget({
          daily_token_cap: 900000, source: "department", inherited_cap: 900000, inherited_source: "department",
          tokens_used_today: 12500, may_raise: false, show_figures: true,
        }),
      });

      expect(wrapper.get('[data-test="budget-used"]').text()).toContain("12,500");
      expect(wrapper.get('[data-test="cap-locked"]').text()).toMatch(/not yours to raise/i);
      expect(wrapper.find('[data-test="cap-edit"]').exists()).toBe(false);
      expect(wrapper.find('[data-test="cap-input"]').exists()).toBe(false);
      expect(wrapper.find('[data-test="cap-clear"]').exists()).toBe(false);
    });
  });

  describe("when may_raise is true", () => {
    it("saves a new limit at the user scope", async () => {
      const { wrapper, request } = await keys({
        effectiveBudget: makeEffectiveBudget({ daily_token_cap: 200000, may_raise: true }),
      });

      await wrapper.get('[data-test="cap-edit"]').trigger("click");
      await wrapper.get('[data-test="cap-input"]').setValue("400000");
      await wrapper.get('[data-test="cap-save"]').trigger("click");
      await flush();

      const put = request.mock.calls.find(
        ([path, opts]) => path === "/settings/credentials/budgets" && (opts as { method?: string })?.method === "PUT",
      );
      expect(put?.[1]).toMatchObject({ method: "PUT", body: { scope: "user", daily_token_cap: 400000 } });
      expect(wrapper.get('[data-test="budget"]').text()).toContain("400,000");
    });

    it("offers giving the inherited limit back only when there is a row of your own", async () => {
      const withoutOwn = await keys({ effectiveBudget: makeEffectiveBudget({ may_raise: true }) });
      expect(withoutOwn.wrapper.find('[data-test="cap-clear"]').exists()).toBe(false);
      expect(withoutOwn.wrapper.get('[data-test="cap-edit"]').text()).toBe("Set your own limit");

      const withOwn = await keys({
        budgets: [makeBudget({ id: 11 })],
        effectiveBudget: makeEffectiveBudget({ source: "user", may_raise: true }),
      });
      expect(withOwn.wrapper.get('[data-test="cap-edit"]').text()).toBe("Change your limit");

      await withOwn.wrapper.get('[data-test="cap-clear"]').trigger("click");
      await flush();
      expect(withOwn.request.mock.calls.some(([path, opts]) =>
        path === "/settings/credentials/budgets/11" && (opts as { method?: string })?.method === "DELETE")).toBe(true);
    });

    // The API's 403 explains itself; the page shows that rather than a sentence of its own.
    it("shows the API's refusal when a raise is turned down", async () => {
      const detail =
        "The allowance you inherit is 200,000 tokens a day, and raising it means spending more of somebody else's money.";
      const { wrapper } = await keys({
        effectiveBudget: makeEffectiveBudget({ may_raise: true }),
        budgetError: apiError(403, detail),
      });

      await wrapper.get('[data-test="cap-edit"]').trigger("click");
      await wrapper.get('[data-test="cap-input"]').setValue("900000");
      await wrapper.get('[data-test="cap-save"]').trigger("click");
      await flush();

      expect(wrapper.get('[data-test="cap-error"]').text()).toBe(detail);
    });
  });
});
