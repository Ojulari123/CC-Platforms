import { describe, expect, it } from "vitest";
import type { JournalResponse, RollupResponse } from "~/types/api";
import { apiError, flush, mountPage } from "./pageHarness";
import type { ApiCall } from "./pageHarness";
import { makeJournal, makeRepo, makeRollup, makeUser } from "./fixtures";

/* The journal is the one screen where a person types something they cannot get back from
   anywhere else, so most of what is asserted here is about not losing it. */

const ME = makeUser({ id: 1042 });
const REPOS = [makeRepo({ id: 4, full_name: "acme/pulse-api", lead_user_id: 1042 })];

interface State {
  entries: JournalResponse[];
  rollup: RollupResponse | null;
  /** Thrown by POST "" instead of accepting the entry. */
  postError?: unknown;
  /** Thrown by POST /rollup instead of writing one. */
  generateError?: unknown;
  /** Thrown by GET /rollup instead of answering. */
  rollupError?: unknown;
  patchError?: unknown;
  deleteError?: unknown;
  /** What /activity/me answers for this repository — the API's own write predicate. */
  counts: { commits: number; pull_requests: number; reviews: number; issues: number };
}

function stub(over: Partial<State> = {}) {
  const state: State = {
    entries: [makeJournal()],
    rollup: null,
    counts: { commits: 3, pull_requests: 1, reviews: 0, issues: 0 },
    ...over,
  };

  let nextId = 100;

  function api(call: ApiCall): unknown {
    const { path, method } = call;

    if (path === "/activity/me") {
      return {
        user_id: ME.id,
        user: null,
        since: null,
        counts: state.counts,
        recent_commits: [],
        recent_pull_requests: [],
        recent_reviews: [],
        recent_issues: [],
      };
    }

    const journals = /^\/github\/repositories\/(\d+)\/journals$/.exec(path);
    if (journals && method === "GET") {
      const limit = Number(call.query?.limit ?? 20);
      const offset = Number(call.query?.offset ?? 0);
      return {
        items: state.entries.slice(offset, offset + limit),
        total: state.entries.length,
        limit,
        offset,
      };
    }
    if (journals && method === "POST") {
      if (state.postError) throw state.postError;
      const created = makeJournal({
        id: (nextId += 1),
        repo_id: Number(journals[1]),
        body: (call.body as { body: string }).body,
        created_at: "2026-08-21T09:00:00Z",
      });
      state.entries = [created, ...state.entries];
      return created;
    }

    const rollup = /^\/github\/repositories\/(\d+)\/journals\/rollup$/.exec(path);
    if (rollup && method === "GET") {
      if (state.rollupError) throw state.rollupError;
      // 200 with a null inside it. A 404 from this endpoint means the repository is not
      // visible to you, which is a different answer with a different screen behind it.
      return { rollup: state.rollup };
    }
    if (rollup && method === "POST") {
      if (state.generateError) throw state.generateError;
      state.rollup = makeRollup({ summary: "Fresh readout." });
      return state.rollup;
    }

    const entry = /^\/github\/repositories\/(\d+)\/journals\/(\d+)$/.exec(path);
    if (entry && method === "PATCH") {
      if (state.patchError) throw state.patchError;
      const id = Number(entry[2]);
      state.entries = state.entries.map((row) =>
        row.id === id
          ? { ...row, body: (call.body as { body: string }).body, edited_at: "2026-08-21T11:00:00Z" }
          : row,
      );
      return state.entries.find((row) => row.id === id);
    }
    if (entry && method === "DELETE") {
      if (state.deleteError) throw state.deleteError;
      state.entries = state.entries.filter((row) => row.id !== Number(entry[2]));
      return undefined;
    }

    throw new Error(`unhandled ${method} ${path}`);
  }

  return { state, api };
}

function open(over: Partial<State> = {}, options: Record<string, unknown> = {}) {
  const { state, api } = stub(over);
  return mountPage({ api, me: ME, repositories: REPOS, ...options }).then((page) => ({ ...page, state }));
}

function bodies(wrapper: Awaited<ReturnType<typeof open>>["wrapper"]) {
  return wrapper.findAll('[data-test="entry"]').map((li) => li.find("p.whitespace-pre-wrap").text());
}

function calls(request: Awaited<ReturnType<typeof open>>["request"]) {
  return request.mock.calls.map(([path, opts]) => `${(opts as { method?: string })?.method ?? "GET"} ${path}`);
}

describe("/journal · the feed", () => {
  it("renders the entries in the order the API returned them, newest first", async () => {
    // The server orders by created_at desc; the page must not re-sort behind it.
    const { wrapper } = await open({
      entries: [
        makeJournal({ id: 9, body: "Today", created_at: "2026-08-20T09:00:00Z" }),
        makeJournal({ id: 8, body: "Yesterday", created_at: "2026-08-19T09:00:00Z" }),
        makeJournal({ id: 7, body: "The day before", created_at: "2026-08-18T09:00:00Z" }),
      ],
    });
    expect(bodies(wrapper)).toEqual(["Today", "Yesterday", "The day before"]);
  });

  it("names an author identity could not resolve without inventing one", async () => {
    const { wrapper } = await open({ entries: [makeJournal({ author: null, author_user_id: 88 })] });
    expect(wrapper.text()).toContain("Unknown user (#88)");
  });

  it("keeps line breaks and refuses to let an entry become markup", async () => {
    const body = 'one\ntwo\n<img src=x onerror="alert(1)">';
    const { wrapper } = await open({ entries: [makeJournal({ body })] });

    const paragraph = wrapper.findAll('[data-test="entry"]')[0]!.find("p.whitespace-pre-wrap");
    expect(paragraph.classes()).toContain("whitespace-pre-wrap");
    expect(paragraph.text()).toContain("<img src=x");
    expect(wrapper.find("img").exists()).toBe(false);
  });

  it("says the journal is empty rather than showing an empty list", async () => {
    const { wrapper } = await open({ entries: [] });
    expect(wrapper.find('[data-test="feed"]').exists()).toBe(false);
    expect(wrapper.text()).toMatch(/nothing written yet/i);
  });

  it("does not confirm a repository exists when the API answers 404", async () => {
    const { wrapper } = await mountPage({
      api: () => {
        throw apiError(404, "Repository not found");
      },
      me: ME,
      repositories: REPOS,
    });
    expect(wrapper.text()).toMatch(/not available to you/i);
    expect(wrapper.text()).not.toMatch(/private|forbidden|no permission/i);
  });

  it("pages against total, limit and offset", async () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      makeJournal({ id: 100 - i, body: `entry ${i}` }),
    );
    const { wrapper, request, route } = await open({ entries: many });

    expect(wrapper.findAll('[data-test="entry"]')).toHaveLength(20);
    expect(wrapper.text()).toContain("1–20 of 25");

    await wrapper.get('[data-test="page-older"]').trigger("click");
    await flush();

    expect(route.query.page).toBe("1");
    expect(request.mock.calls.at(-1)?.[1]).toMatchObject({ query: { limit: 20, offset: 20 } });
    expect(wrapper.findAll('[data-test="entry"]')).toHaveLength(5);
  });
});

describe("/journal · the composer", () => {
  it("refuses an empty box and a box holding only spaces", async () => {
    const { wrapper } = await open();
    const post = () => wrapper.get('[data-test="composer-post"]');

    expect(post().attributes("disabled")).toBeDefined();

    await wrapper.get('[data-test="composer"]').setValue("   \n\t  ");
    expect(post().attributes("disabled")).toBeDefined();

    await wrapper.get('[data-test="composer"]').setValue("Blocked on the GitHub token.");
    expect(post().attributes("disabled")).toBeUndefined();
  });

  it("caps the entry at the 10,000 the API accepts, and only counts down near the limit", async () => {
    const { wrapper } = await open();
    const box = wrapper.get('[data-test="composer"]');
    expect(box.attributes("maxlength")).toBe("10000");

    await box.setValue("short");
    expect(wrapper.get('[data-test="composer-count"]').text()).toBe("5 / 10000");

    await box.setValue("x".repeat(9_900));
    expect(wrapper.get('[data-test="composer-count"]').text()).toBe("100 characters left");

    await box.setValue("x".repeat(10_001));
    expect(wrapper.get('[data-test="composer-count"]').text()).toBe("-1 characters left");
    expect(wrapper.get('[data-test="composer-post"]').attributes("disabled")).toBeDefined();
  });

  it("puts a posted entry on the feed without anybody reloading the page", async () => {
    const { wrapper } = await open();

    await wrapper.get('[data-test="composer"]').setValue("Waiting on review for #212.");
    await wrapper.get('[data-test="composer-post"]').trigger("click");
    await flush();

    expect(bodies(wrapper)[0]).toBe("Waiting on review for #212.");
    expect((wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps every word of a refused entry and says why it was refused", async () => {
    const detail =
      "You need to be a member of this repository to post to its journal. Membership means you lead it, deputise on it, administer its department, or have synced GitHub activity in it.";
    const { wrapper } = await open({ postError: apiError(403, detail) });

    const typed = "Blocked on the GitHub token — three days of work in this box.";
    await wrapper.get('[data-test="composer"]').setValue(typed);
    await wrapper.get('[data-test="composer-post"]').trigger("click");
    await flush();

    // The entry is the thing that must survive a permissions error.
    expect((wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value).toBe(typed);
    const alert = wrapper.get('[data-test="composer-error"]');
    expect(alert.attributes("role")).toBe("alert");
    expect(alert.text()).toContain("member of this repository");
    expect(alert.text()).toMatch(/still in the box above/i);
  });

  it("does not offer a composer to somebody who can only read", async () => {
    // Not the lead, not the deputy, no department role, and nothing synced here: the
    // same four tests may_write_on_repo makes.
    const { wrapper } = await open(
      { counts: { commits: 0, pull_requests: 0, reviews: 0, issues: 0 } },
      { me: makeUser({ id: 2001 }), repositories: [makeRepo({ id: 4, lead_user_id: 1042 })] },
    );

    expect(wrapper.find('[data-test="composer"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="read-only"]').text()).toMatch(/read this journal but not write/i);
    expect(wrapper.get('[data-test="rollup-generate"]').attributes("disabled")).toBeDefined();
  });
});

describe("/journal · your own entries", () => {
  it("marks an entry as edited once it has been", async () => {
    const { wrapper } = await open({ entries: [makeJournal({ id: 7, body: "First pass." })] });
    expect(wrapper.find('[data-test="edited"]').exists()).toBe(false);

    await wrapper.get('[data-test="entry-edit"]').trigger("click");
    await wrapper.get('[data-test="entry-editor"]').setValue("Second pass.");
    await wrapper.get('[data-test="entry-save"]').trigger("click");
    await flush();

    expect(bodies(wrapper)).toEqual(["Second pass."]);
    expect(wrapper.get('[data-test="edited"]').text()).toMatch(/edited/i);
  });

  it("offers neither edit nor delete on somebody else's entry", async () => {
    const { wrapper } = await open({ entries: [makeJournal({ author_user_id: 2001 })] });
    expect(wrapper.find('[data-test="entry-edit"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="entry-delete"]').exists()).toBe(false);
  });

  it("asks before deleting, and only fires when the dialog is answered", async () => {
    const { wrapper, request } = await open();

    await wrapper.get('[data-test="entry-delete"]').trigger("click");
    await flush(2);

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(calls(request).some((call) => call.startsWith("DELETE"))).toBe(false);

    (document.querySelector('[data-test="delete-confirm"]') as HTMLElement).click();
    await flush();

    expect(calls(request)).toContain("DELETE /github/repositories/4/journals/7");
    expect(wrapper.findAll('[data-test="entry"]')).toHaveLength(0);
  });

  it("says a 403 on an edit plainly instead of failing quietly", async () => {
    const { wrapper } = await open({ patchError: apiError(403, "You can only edit your own journal entry") });

    await wrapper.get('[data-test="entry-edit"]').trigger("click");
    await wrapper.get('[data-test="entry-editor"]').setValue("Changed.");
    await wrapper.get('[data-test="entry-save"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="entry-error"]').text()).toMatch(/only the person who wrote an entry can change it/i);
  });
});

describe("/journal · the rollup", () => {
  it("invites a first rollup when the API answers 200 with rollup: null", async () => {
    const { wrapper, request } = await open({ rollup: null });

    expect(wrapper.text()).toMatch(/no rollup has been written for this repository yet/i);
    expect(wrapper.find('[data-test="rollup-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="rollup-unreadable"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="rollup-out-of-reach"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="rollup-generate"]').text()).toBe("Generate a rollup");
    // The empty state is an answer, so nothing was caught and nothing was retried.
    expect(calls(request).filter((c) => c.endsWith("/rollup")).length).toBe(1);
  });

  /* The two answers the endpoint can give that are not a rollup, told apart. Empty is
     above; this is the other one, and it must not read as "none written yet". */
  it("says a 404 is a repository you cannot see, not an empty rollup", async () => {
    const { wrapper } = await open({ rollupError: apiError(404, "Repository not found") });

    expect(wrapper.get('[data-test="rollup-out-of-reach"]').text()).toMatch(/not available to you/i);
    expect(wrapper.text()).not.toMatch(/no rollup has been written for this repository yet/i);
  });

  it("keeps a genuine read failure separate from both", async () => {
    const { wrapper } = await open({ rollupError: apiError(500, "boom") });

    expect(wrapper.get('[data-test="rollup-unreadable"]').text()).toMatch(/could not be read/i);
    expect(wrapper.find('[data-test="rollup-out-of-reach"]').exists()).toBe(false);
  });

  it("shows the summary with what it covered, who asked for it and which model wrote it", async () => {
    const { wrapper } = await open({ rollup: makeRollup() });

    const text = wrapper.text();
    expect(text).toContain("The week went on the sync worker and the approval emails.");
    expect(text).toContain("6 entries");
    expect(text).toContain("Ada Nwosu");
    expect(text).toContain("claude-sonnet-4-5");
    expect(wrapper.get('[data-test="rollup-generate"]').text()).toBe("Regenerate");
  });

  it("replaces the summary in place when a new one is generated", async () => {
    const { wrapper } = await open({ rollup: makeRollup() });

    await wrapper.get('[data-test="rollup-generate"]').trigger("click");
    await flush();

    expect(wrapper.text()).toContain("Fresh readout.");
  });

  const distinct: [number, RegExp][] = [
    [422, /nothing to summarise yet/i],
    [502, /AI service did not answer/i],
    [429, /ten rollups in an hour/i],
  ];

  for (const [status, expected] of distinct) {
    it(`explains a ${status} in its own words`, async () => {
      const { wrapper } = await open({ generateError: apiError(status) });

      await wrapper.get('[data-test="rollup-generate"]').trigger("click");
      await flush();

      const alert = wrapper.get('[data-test="rollup-error"]');
      expect(alert.attributes("role")).toBe("alert");
      expect(alert.text()).toMatch(expected);
      for (const [other, pattern] of distinct) {
        if (other !== status) expect(alert.text()).not.toMatch(pattern);
      }
    });
  }
});

describe("/journal · choosing a repository", () => {
  it("puts the first visible repository in the URL so the view is a link", async () => {
    const { route, request } = await open({}, { repositories: [makeRepo({ id: 4 }), makeRepo({ id: 9 })] });

    expect(route.query.repo).toBe("4");
    expect(calls(request)).toContain("GET /github/repositories/4/journals");
  });

  it("reads the repository back out of ?repo= on load", async () => {
    const { request } = await open(
      {},
      { repositories: [makeRepo({ id: 4 }), makeRepo({ id: 9, full_name: "acme/forge-api" })], query: { repo: "9" } },
    );

    expect(calls(request)).toContain("GET /github/repositories/9/journals");
    expect(calls(request)).not.toContain("GET /github/repositories/4/journals");
  });

  it("writes a change of repository back to the query string and refetches", async () => {
    const { wrapper, route, request } = await open(
      {},
      { repositories: [makeRepo({ id: 4 }), makeRepo({ id: 9, full_name: "acme/forge-api" })] },
    );

    const select = wrapper.findAllComponents({ name: "Select" })[0]!;
    select.vm.$emit("update:modelValue", "9");
    await flush();

    expect(route.query.repo).toBe("9");
    expect(calls(request)).toContain("GET /github/repositories/9/journals");
  });
});

describe("/journal · the allowance", () => {
  /* The API decides the wording: a person on the platform key is told their allowance is
     spent, whoever is paying gets the figures. The page renders what it was sent rather
     than writing its own sentence out of the numbers. */
  const wordings = [
    "You have used today's AI allowance. The allowance resets at 00:00 UTC.",
    "This is larger than the AI allowance you have left today. The allowance resets at 00:00 UTC.",
    "You have used 1,259,779 of your 200,000 daily AI tokens. The allowance resets at 00:00 UTC.",
    "This needs about 500,000 tokens and you have 199,900 of your 200,000 daily AI tokens left. The allowance resets at 00:00 UTC.",
  ];

  for (const detail of wordings) {
    it(`renders "${detail.slice(0, 32)}…" exactly as sent`, async () => {
      const { wrapper } = await open({ generateError: apiError(429, detail) });

      await wrapper.get('[data-test="rollup-generate"]').trigger("click");
      await flush();

      expect(wrapper.get('[data-test="rollup-error"]').text()).toBe(detail);
    });
  }

  // slowapi's own 429 carries no `detail` at all, so that one is the hourly limit.
  it("falls back to the hourly limit when a 429 carries no message", async () => {
    const { wrapper } = await open({ generateError: apiError(429) });

    await wrapper.get('[data-test="rollup-generate"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="rollup-error"]').text()).toMatch(/ten rollups in an hour/i);
  });
});
