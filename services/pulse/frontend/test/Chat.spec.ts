import { describe, expect, it, vi } from "vitest";
import type {
  ChatMessage,
  Conversation,
  GitHubIndexStatus,
  IndexedRepo,
} from "~/types/api";
import { indexTone, REPO_POLL_MS } from "~/utils/chat";
import { apiError, flush, mountPage } from "./pageHarness";
import type { ApiCall } from "./pageHarness";
import {
  makeChatMessage,
  makeCitation,
  makeConversation,
  makeIndexedRepo,
  makeUser,
} from "./fixtures";

/* Two things can go badly wrong on this screen and neither of them is cosmetic: a
   question the person typed can be swallowed by a failed request, and a language model's
   output can be rendered as markup. Most of what is asserted here is about those two. */

const ME = makeUser({ id: 1042 });

interface State {
  repos: IndexedRepo[];
  githubStatus: GitHubIndexStatus;
  conversations: Conversation[];
  messages: ChatMessage[];
  /** The assistant message POST /messages answers with. */
  reply: ChatMessage;
  sendError?: unknown;
  addError?: unknown;
  detailError?: unknown;
}

function stub(over: Partial<State> = {}) {
  const state: State = {
    repos: [makeIndexedRepo()],
    githubStatus: { connected: true, has_repo_scope: true, reconnect_required: false, detail: null },
    conversations: [makeConversation()],
    messages: [
      makeChatMessage({ id: 299, role: "user", content: "Where is the refresh token rotated?", citations: [] }),
      makeChatMessage({ id: 300 }),
    ],
    reply: makeChatMessage({ id: 401, content: "It rotates in rotate()." }),
    ...over,
  };

  let nextId = 900;

  function page<T>(items: T[]) {
    return { items, total: items.length, limit: 100, offset: 0 };
  }

  function api(call: ApiCall): unknown {
    const { path, method } = call;

    if (path === "/chat/repos/github-status") return state.githubStatus;

    if (path === "/github/connect") return { authorize_url: "https://github.test/authorize?first" };
    if (path === "/github/reconnect" && method === "POST") return { authorize_url: "https://github.test/authorize?again" };

    if (path === "/chat/repos/mine" && method === "POST") return { queued: 3 };

    if (path === "/chat/repos" && method === "GET") return page(state.repos);

    if (path === "/chat/repos" && method === "POST") {
      if (state.addError) throw state.addError;
      const queued = makeIndexedRepo({
        id: (nextId += 1),
        repo_id: null,
        is_public: true,
        full_name: (call.body as { full_name: string }).full_name,
        status: "pending",
        commit_sha: null,
        file_count: 0,
        chunk_count: 0,
        started_at: null,
        finished_at: null,
      });
      state.repos = [...state.repos, queued];
      return queued;
    }

    const repo = /^\/chat\/repos\/(\d+)$/.exec(path);
    if (repo && method === "DELETE") {
      state.repos = state.repos.filter((row) => row.id !== Number(repo[1]));
      return undefined;
    }

    if (path === "/chat/conversations" && method === "GET") return page(state.conversations);

    if (path === "/chat/conversations" && method === "POST") {
      const created = makeConversation({ id: (nextId += 1), title: "New conversation" });
      state.conversations = [created, ...state.conversations];
      return created;
    }

    const conversation = /^\/chat\/conversations\/(\d+)$/.exec(path);
    if (conversation && method === "GET") {
      if (state.detailError) throw state.detailError;
      const row = state.conversations.find((c) => c.id === Number(conversation[1]));
      if (!row) throw apiError(404, "Conversation not found");
      return { ...row, messages: state.messages };
    }
    if (conversation && method === "DELETE") {
      state.conversations = state.conversations.filter((c) => c.id !== Number(conversation[1]));
      return undefined;
    }

    const messages = /^\/chat\/conversations\/(\d+)\/messages$/.exec(path);
    if (messages && method === "POST") {
      if (state.sendError) throw state.sendError;
      const asked = makeChatMessage({
        id: (nextId += 1),
        role: "user",
        content: (call.body as { content: string }).content,
        citations: [],
        model: null,
      });
      state.messages = [...state.messages, asked, state.reply];
      return state.reply;
    }

    throw new Error(`unhandled ${method} ${path}`);
  }

  return { state, api };
}

function open(over: Partial<State> = {}, options: Record<string, unknown> = {}) {
  const { state, api } = stub(over);
  return mountPage({ api, me: ME, page: "chat", ...options }).then((mounted) => ({ ...mounted, state }));
}

type Page = Awaited<ReturnType<typeof open>>;

function bubbles(wrapper: Page["wrapper"]) {
  return wrapper.findAll('[data-test="message-content"]').map((p) => p.text());
}

function calls(request: Page["request"]) {
  return request.mock.calls.map(([path, opts]) => `${(opts as { method?: string })?.method ?? "GET"} ${path}`);
}

function countOf(request: Page["request"], wanted: string) {
  return calls(request).filter((one) => one === wanted).length;
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ask(page: Page, question: string) {
  await page.wrapper.get('[data-test="composer"]').setValue(question);
  await page.wrapper.get('[data-test="composer-send"]').trigger("click");
  await flush();
}

describe("/chat · the index", () => {
  it("refuses anything that is not owner/name, and does not send it", async () => {
    const { wrapper, request } = await open();

    await wrapper.get('[data-test="repo-input"]').setValue("just some words");
    await wrapper.get('[data-test="repo-add"]').trigger("click");
    await flush();

    expect(wrapper.get('[data-test="repo-error"]').text()).toMatch(/owner\/name/i);
    expect(calls(request)).not.toContain("POST /chat/repos");
  });

  it("takes a pasted GitHub URL as the repository it names", async () => {
    const { wrapper, request } = await open();

    await wrapper.get('[data-test="repo-input"]').setValue("https://github.com/vercel/next.js/tree/canary/packages");
    await wrapper.get('[data-test="repo-add"]').trigger("click");
    await flush();

    expect(wrapper.find('[data-test="repo-error"]').exists()).toBe(false);
    const post = request.mock.calls.find(([path, opts]) => path === "/chat/repos" && (opts as { method?: string })?.method === "POST");
    expect(post?.[1]).toMatchObject({ body: { full_name: "vercel/next.js" } });
  });

  it("keeps asking while a repository is indexing and stops once it is ready", async () => {
    const { request, state } = await open({ repos: [makeIndexedRepo({ id: 71, status: "pending" })] });

    expect(countOf(request, "GET /chat/repos")).toBe(1);

    await wait(REPO_POLL_MS * 1.4);
    expect(countOf(request, "GET /chat/repos")).toBeGreaterThan(1);

    state.repos = [makeIndexedRepo({ id: 71, status: "ready" })];
    await wait(REPO_POLL_MS * 1.4);
    const settled = countOf(request, "GET /chat/repos");

    // Nothing is moving any more, so the timer has to be gone rather than merely quiet.
    await wait(REPO_POLL_MS * 1.4);
    expect(countOf(request, "GET /chat/repos")).toBe(settled);
  }, 25_000);

  const broken: [IndexedRepo["status"], string][] = [
    ["error", "Repository has 41,000 files, which is over the indexing limit."],
    ["rate_limited", "GitHub rate limit hit while reading the tree. Try again in about 20 minutes."],
  ];

  for (const [status, detail] of broken) {
    it(`shows why a ${status} index did not finish, and offers to try again`, async () => {
      const { wrapper, request } = await open({
        repos: [makeIndexedRepo({ id: 71, full_name: "acme/pulse-api", status, detail })],
      });

      expect(wrapper.get('[data-test="repo-detail"]').text()).toBe(detail);

      await wrapper.get('[data-test="repo-retry"]').trigger("click");
      await flush();

      const post = request.mock.calls.find(([path, opts]) => path === "/chat/repos" && (opts as { method?: string })?.method === "POST");
      expect(post?.[1]).toMatchObject({ body: { full_name: "acme/pulse-api" } });
    });
  }

  it("asks before deleting an index, and only then deletes it", async () => {
    const { wrapper, request } = await open({ repos: [makeIndexedRepo({ id: 71 })] });

    await wrapper.get('[data-test="repo-delete"]').trigger("click");
    await flush(2);

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(calls(request)).not.toContain("DELETE /chat/repos/71");

    (document.querySelector('[data-test="repo-delete-confirm"]') as HTMLElement).click();
    await flush();

    expect(calls(request)).toContain("DELETE /chat/repos/71");
  });

  it("queues the caller's own GitHub repositories in one go", async () => {
    const { wrapper, request, toast } = await open();

    await wrapper.get('[data-test="index-mine"]').trigger("click");
    await flush();

    expect(calls(request)).toContain("POST /chat/repos/mine");
    expect(toast.mock.calls[0]?.[0]).toMatch(/3 repositories queued/i);
  });
});

describe("/chat · the GitHub reconnect notice", () => {
  /* The server's own sentence, whatever it happens to say. This one is deliberately not
     the real RECONNECT_DETAIL: a page that only renders the wording it was built against
     is a page that breaks when somebody fixes a typo upstream. */
  const SERVER_DETAIL = "Some wording the server chose, which this page has never seen before.";

  const NARROW = {
    connected: true,
    has_repo_scope: false,
    reconnect_required: true,
    detail: SERVER_DETAIL,
  };

  it("renders the server's detail rather than a sentence of its own", async () => {
    const { wrapper } = await open({ githubStatus: NARROW });

    expect(wrapper.get('[data-test="github-notice-detail"]').text()).toContain(SERVER_DETAIL);
  });

  it("shows the notice off reconnect_required, not off the prose", async () => {
    // has_repo_scope says no and the detail is the old wording, but the server has said
    // no reconnect is required. The server wins.
    const { wrapper } = await open({
      githubStatus: {
        connected: true,
        has_repo_scope: false,
        reconnect_required: false,
        detail: "Your GitHub connection can't read private repositories.",
      },
    });

    expect(wrapper.find('[data-test="github-notice"]').exists()).toBe(false);
  });

  it("does not block a public repository while it asks", async () => {
    const { wrapper, request } = await open({ githubStatus: NARROW });

    expect(wrapper.get('[data-test="repo-input"]').attributes("disabled")).toBeUndefined();
    await wrapper.get('[data-test="repo-input"]').setValue("torvalds/linux");
    await wrapper.get('[data-test="repo-add"]').trigger("click");
    await flush();
    expect(calls(request)).toContain("POST /chat/repos");
  });

  /* POST /github/reconnect leaves the stored account alone and only hands back a URL, so
     the connection somebody already has keeps working until GitHub confirms the new one.
     /github/connect is for the person who has nothing connected yet. */
  it("asks /github/reconnect for a connection that is only too narrow", async () => {
    const { wrapper, request } = await open({ githubStatus: NARROW });

    await wrapper.get('[data-test="github-connect"]').trigger("click");
    await flush();

    expect(calls(request)).toContain("POST /github/reconnect");
    expect(calls(request)).not.toContain("GET /github/connect");
  });

  it("asks /github/connect when nothing is connected at all", async () => {
    const { wrapper, request } = await open({
      githubStatus: { connected: false, has_repo_scope: false, reconnect_required: false, detail: null },
    });

    const notice = wrapper.get('[data-test="github-notice"]');
    expect(notice.text()).toMatch(/no github account is connected/i);
    expect(wrapper.get('[data-test="github-connect"]').text()).toBe("Connect GitHub");

    await wrapper.get('[data-test="github-connect"]').trigger("click");
    await flush();

    expect(calls(request)).toContain("GET /github/connect");
    expect(calls(request)).not.toContain("POST /github/reconnect");
  });

  it("shows no notice when the connection already reaches private repositories", async () => {
    const { wrapper } = await open();
    expect(wrapper.find('[data-test="github-notice"]').exists()).toBe(false);
  });
});

describe("/chat · indexing refusals", () => {
  /* Indexing draws on the same allowance as everything else, so the same four wordings
     can come back from POST /chat/repos. They are shown as sent here too. */
  const wordings = [
    "You have used today's AI allowance. The allowance resets at 00:00 UTC.",
    "This is larger than the AI allowance you have left today. The allowance resets at 00:00 UTC.",
    "You have used 1,259,779 of your 200,000 daily AI tokens. The allowance resets at 00:00 UTC.",
    "This needs about 500,000 tokens and you have 199,900 of your 200,000 daily AI tokens left. The allowance resets at 00:00 UTC.",
  ];

  for (const detail of wordings) {
    it(`renders "${detail.slice(0, 32)}…" as sent`, async () => {
      const { wrapper } = await open({ addError: apiError(429, detail) });

      await wrapper.get('[data-test="repo-input"]').setValue("torvalds/linux");
      await wrapper.get('[data-test="repo-add"]').trigger("click");
      await flush();

      expect(wrapper.get('[data-test="repo-error"]').text()).toBe(detail);
    });
  }
});

describe("/chat · a paused index", () => {
  const PAUSED_DETAIL =
    "You have used today's AI allowance. The allowance resets at 00:00 UTC. 118 file(s) are already indexed and have been kept. Index this repository again after the reset to carry on.";

  function paused() {
    return makeIndexedRepo({ id: 81, full_name: "acme/paused-repo", status: "paused", detail: PAUSED_DETAIL });
  }

  it("reads as waiting rather than broken, and never the same as a failure", async () => {
    const { wrapper } = await open({
      repos: [paused(), makeIndexedRepo({ id: 82, full_name: "acme/failed-repo", status: "error", detail: "The embedding service is unavailable right now." })],
    });

    const rows = wrapper.findAll('[data-test="repo-row"]');
    const [pausedRow, failedRow] = rows;

    expect(pausedRow!.get('[data-test="repo-status"]').text()).toBe("Paused");
    expect(failedRow!.get('[data-test="repo-status"]').text()).toBe("Failed");
    // Different tone, not just a different word: warn is waiting, bad is broken.
    expect(indexTone("paused")).toBe("warn");
    expect(indexTone("error")).toBe("bad");
    expect(indexTone("paused")).not.toBe(indexTone("error"));
  });

  it("shows the detail the server wrote, which is what to do about it", async () => {
    const { wrapper } = await open({ repos: [paused()] });

    expect(wrapper.get('[data-test="repo-detail"]').text()).toBe(PAUSED_DETAIL);
  });

  it("offers carrying on as a button, where a failure only gets the quiet retry", async () => {
    const { wrapper, request } = await open({ repos: [paused()] });

    const resume = wrapper.get('[data-test="repo-resume"]');
    expect(resume.text()).toBe("Carry on indexing");
    expect(wrapper.find('[data-test="repo-retry"]').exists()).toBe(false);

    await resume.trigger("click");
    await flush();

    // The same POST that queued it: there is no separate resume endpoint.
    expect(calls(request)).toContain("POST /chat/repos");
  });

  it("is not selectable to ask questions of, the same as a failure", async () => {
    const { wrapper } = await open({
      repos: [makeIndexedRepo({ id: 71 }), paused()],
    });

    const options = wrapper.findAll('[data-test="scope-option"]');
    const pausedOption = options.find((o) => o.text() === "acme/paused-repo");
    expect(pausedOption!.attributes("disabled")).toBeDefined();
    expect(pausedOption!.attributes("aria-pressed")).toBeUndefined();

    // And it is not silently searched either: only the ready one goes with the question.
    expect(wrapper.get('[data-test="scope"]').text()).toContain("acme/paused-repo");
  });

  it("keeps a paused repository out of the ids a question is sent with", async () => {
    const page = await open({ repos: [makeIndexedRepo({ id: 71 }), paused()], messages: [] });

    await ask(page, "What changed?");

    const post = page.request.mock.calls.find(([path]) => String(path).endsWith("/messages"));
    expect(post?.[1]).toMatchObject({ body: { indexed_repo_ids: [71] } });
  });
});

describe("/chat · asking", () => {
  it("puts the question in the thread and then the answer that came back", async () => {
    const page = await open({ messages: [], reply: makeChatMessage({ id: 401, content: "It rotates in rotate()." }) });

    await ask(page, "Where is the refresh token rotated?");

    expect(bubbles(page.wrapper)).toEqual([
      "Where is the refresh token rotated?",
      "It rotates in rotate().",
    ]);
    expect((page.wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value).toBe("");
    expect(page.announce.mock.calls.at(-1)?.[0]).toMatch(/answer received/i);
  });

  it("sends only the repositories in scope", async () => {
    const page = await open({
      repos: [makeIndexedRepo({ id: 71 }), makeIndexedRepo({ id: 72, full_name: "acme/forge-api" })],
      messages: [],
    });

    await ask(page, "What does the sync worker do?");

    const post = page.request.mock.calls.find(([path]) => String(path).endsWith("/messages"));
    expect(post?.[1]).toMatchObject({ body: { indexed_repo_ids: [71, 72] } });
  });

  it("keeps every word of a question the API refused", async () => {
    const typed = "Why does the sync worker retry forever when GitHub rate limits it?";
    const page = await open({ sendError: apiError(500, "boom") });

    await ask(page, typed);

    expect((page.wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value).toBe(typed);
    expect(page.wrapper.get('[data-test="composer-error"]').attributes("role")).toBe("alert");
    // The optimistic bubble is gone: nothing was saved, so nothing pretends it was.
    expect(page.wrapper.find('[data-test="asking"]').exists()).toBe(false);
  });

  const distinct: [number, RegExp][] = [
    [429, /sixty questions in an hour/i],
    [502, /AI service did not answer/i],
    [422, /nothing is indexed yet/i],
  ];

  for (const [status, expected] of distinct) {
    it(`explains a ${status} in its own words`, async () => {
      const page = await open({ sendError: apiError(status) });

      await ask(page, "What changed this week?");

      const alert = page.wrapper.get('[data-test="composer-error"]');
      expect(alert.text()).toMatch(expected);
      for (const [other, pattern] of distinct) {
        if (other !== status) expect(alert.text()).not.toMatch(pattern);
      }
    });
  }

  /* Four wordings, decided server-side by who is paying, and all four are rendered as
     sent. Composing a sentence out of the numbers here would tell somebody on the
     platform key how much of somebody else's money they had spent. */
  const allowanceWordings = [
    "You have used today's AI allowance. The allowance resets at 00:00 UTC.",
    "This is larger than the AI allowance you have left today. The allowance resets at 00:00 UTC.",
    "You have used 1,259,779 of your 200,000 daily AI tokens. The allowance resets at 00:00 UTC.",
    "This needs about 500,000 tokens and you have 199,900 of your 200,000 daily AI tokens left. The allowance resets at 00:00 UTC.",
  ];

  for (const detail of allowanceWordings) {
    it(`renders the allowance refusal "${detail.slice(0, 32)}…" as sent`, async () => {
      const page = await open({ sendError: apiError(429, detail) });

      await ask(page, "What changed this week?");

      expect(page.wrapper.get('[data-test="composer-error"]').text()).toBe(detail);
      // The question is still recoverable whichever refusal came back.
      expect((page.wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value)
        .toBe("What changed this week?");
    });
  }

  it("falls back to the burst limit when a 429 carries no message", async () => {
    const page = await open({ sendError: apiError(429) });

    await ask(page, "What changed this week?");

    const alert = page.wrapper.get('[data-test="composer-error"]');
    expect(alert.text()).toMatch(/sixty questions in an hour/i);
  });

  it("routes a 422 at the index panel rather than leaving it as an error", async () => {
    const page = await open({ sendError: apiError(422), repos: [] });

    await ask(page, "What does this repository do?");

    expect(page.wrapper.find('[data-test="go-to-index"]').exists()).toBe(true);
  });

  it("shows what it is doing while the answer is being written", async () => {
    let release: (value: unknown) => void = () => {};
    const held = new Promise((resolve) => {
      release = resolve;
    });
    const { state, api } = stub({ messages: [] });
    const page = await mountPage({
      me: ME,
      page: "chat",
      api: (call) => (call.path.endsWith("/messages") ? held.then(() => api(call)) : api(call)),
    });

    await page.wrapper.get('[data-test="composer"]').setValue("What does the sync worker do?");
    await page.wrapper.get('[data-test="composer-send"]').trigger("click");
    await flush();

    expect(page.wrapper.get('[data-test="waiting"]').text()).toMatch(/searching .* for the relevant code/i);
    // The question is on screen while it waits, not only inside the box it left.
    expect(page.wrapper.get('[data-test="asking"]').text()).toContain("What does the sync worker do?");
    expect(page.wrapper.get('[data-test="composer"]').attributes("disabled")).toBeDefined();

    release(null);
    await flush();
    expect(state.messages.at(-1)?.role).toBe("assistant");
    expect(page.wrapper.find('[data-test="waiting"]').exists()).toBe(false);
  });
});

describe("/chat · the answer", () => {
  it("renders a model's HTML as text and never as markup", async () => {
    const content = 'Try <img src=x onerror="alert(1)"> and <script>alert(2)</script>\nsecond line';
    const page = await open({ messages: [makeChatMessage({ id: 300, content, citations: [] })] });

    const body = page.wrapper.get('[data-test="message-content"]');
    expect(body.text()).toContain("<img src=x");
    expect(body.classes()).toContain("whitespace-pre-wrap");
    expect(page.wrapper.find("img").exists()).toBe(false);
    expect(page.wrapper.html()).not.toContain("<script>");
  });

  it("writes a citation as full_name path:start-end and opens it on demand", async () => {
    const page = await open({
      messages: [
        makeChatMessage({
          id: 300,
          citations: [makeCitation({ path: "app/services/tokens.py", start_line: 40, end_line: 58, snippet: "def rotate():\n    pass" })],
        }),
      ],
    });

    const toggle = page.wrapper.get('[data-test="citation-toggle"]');
    expect(toggle.text()).toContain("acme/pulse-api app/services/tokens.py:40-58");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(page.wrapper.find('[data-test="citation-snippet"]').exists()).toBe(false);

    await toggle.trigger("click");

    const snippet = page.wrapper.get('[data-test="citation-snippet"]');
    expect(snippet.text()).toContain("def rotate():");
    expect(snippet.classes()).toContain("overflow-x-auto");
    expect(snippet.classes()).toContain("whitespace-pre");
    expect(page.wrapper.get('[data-test="citation-toggle"]').attributes("aria-expanded")).toBe("true");
  });

  // Deleting an index nulls the citation's indexed_repo_id rather than deleting the
  // answer, so an old citation has to keep rendering with nothing to point back at.
  it("still renders a citation whose index has been deleted", async () => {
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(args);
    });

    const page = await open({
      messages: [
        makeChatMessage({
          id: 300,
          citations: [
            makeCitation({
              indexed_repo_id: null,
              full_name: "acme/deleted-index",
              path: "app/services/gone.py",
              start_line: 4,
              end_line: 9,
              snippet: "def gone():\n    return None",
            }),
          ],
        }),
      ],
    });

    const toggle = page.wrapper.get('[data-test="citation-toggle"]');
    expect(toggle.text()).toContain("acme/deleted-index app/services/gone.py:4-9");

    await toggle.trigger("click");
    expect(page.wrapper.get('[data-test="citation-snippet"]').text()).toContain("def gone():");

    // Nothing is clickable-through: the only control is the disclosure toggle, and no
    // anchor was rendered pointing at an index that no longer exists.
    expect(page.wrapper.get('[data-test="citation"]').findAll("a")).toHaveLength(0);
    expect(errors).toEqual([]);
    spy.mockRestore();
  });
});

describe("/chat · the scope picker", () => {
  it("offers only the repositories that are ready to be searched", async () => {
    const { wrapper } = await open({
      repos: [
        makeIndexedRepo({ id: 71, full_name: "acme/pulse-api", status: "ready" }),
        makeIndexedRepo({ id: 72, full_name: "acme/forge-api", status: "running" }),
        makeIndexedRepo({ id: 73, full_name: "acme/broken", status: "error", detail: "too big" }),
      ],
    });

    const options = wrapper.findAll('[data-test="scope-option"]');
    expect(options.map((b) => b.text())).toEqual(["acme/pulse-api", "acme/forge-api", "acme/broken"]);
    expect(options[0]!.attributes("disabled")).toBeUndefined();
    expect(options[1]!.attributes("disabled")).toBeDefined();
    expect(options[2]!.attributes("disabled")).toBeDefined();
    // Ready ones start selected; nothing else can be.
    expect(options[0]!.attributes("aria-pressed")).toBe("true");
    expect(options[1]!.attributes("aria-pressed")).toBeUndefined();
  });

  it("narrows the search to what is left selected", async () => {
    const page = await open({
      repos: [makeIndexedRepo({ id: 71 }), makeIndexedRepo({ id: 72, full_name: "acme/forge-api" })],
      messages: [],
    });

    await page.wrapper.findAll('[data-test="scope-option"]')[1]!.trigger("click");
    await ask(page, "Where is the token rotated?");

    const post = page.request.mock.calls.find(([path]) => String(path).endsWith("/messages"));
    expect(post?.[1]).toMatchObject({ body: { indexed_repo_ids: [71] } });
  });

  it("refuses to ask a question of nothing", async () => {
    const { wrapper } = await open({ repos: [makeIndexedRepo({ id: 71 })] });

    await wrapper.get('[data-test="scope-option"]').trigger("click");
    await wrapper.get('[data-test="composer"]').setValue("Anything at all?");
    await flush(1);

    expect(wrapper.get('[data-test="scope-empty"]').text()).toMatch(/nothing is selected/i);
    expect(wrapper.get('[data-test="composer-send"]').attributes("disabled")).toBeDefined();
  });
});

describe("/chat · a refused first question", () => {
  /* The composer opens a conversation before it can post a message, so a refused first
     question used to leave a titled, empty "New conversation" in the list. */

  it("throws away the conversation it opened when the first question is refused", async () => {
    const page = await open({
      conversations: [],
      messages: [],
      sendError: apiError(429, "You have used 200,000 of your 200,000 daily AI tokens."),
    });

    await ask(page, "Where is the refresh token rotated?");
    await flush(2);

    const created = calls(page.request).filter((one) => one === "POST /chat/conversations");
    expect(created).toHaveLength(1);
    expect(calls(page.request).filter((one) => one.startsWith("DELETE /chat/conversations/"))).toHaveLength(1);
    expect(page.state.conversations).toEqual([]);
    expect(page.wrapper.get('[data-test="no-conversations"]').text()).toMatch(/no conversations yet/i);
  });

  it("still says why the question was refused", async () => {
    const page = await open({
      conversations: [],
      messages: [],
      sendError: apiError(429, "You have used 200,000 of your 200,000 daily AI tokens."),
    });

    await ask(page, "Where is the refresh token rotated?");
    await flush(2);

    const alert = page.wrapper.get('[data-test="composer-error"]');
    expect(alert.text()).toMatch(/200,000/);
    expect((page.wrapper.get('[data-test="composer"]').element as HTMLTextAreaElement).value).toBe(
      "Where is the refresh token rotated?",
    );
  });

  it("leaves an existing conversation alone when a later question is refused", async () => {
    const page = await open({ sendError: apiError(502, "boom") });

    await ask(page, "What changed this week?");
    await flush(2);

    expect(calls(page.request)).not.toContain("POST /chat/conversations");
    expect(calls(page.request).some((one) => one.startsWith("DELETE /chat/conversations/"))).toBe(false);
    expect(page.state.conversations.map((c) => c.id)).toContain(12);
  });

  it("keeps the conversation somebody opened with New even if their first question fails", async () => {
    const page = await open({
      conversations: [],
      messages: [],
      sendError: apiError(502, "boom"),
    });

    await page.wrapper.get('[data-test="conversation-new"]').trigger("click");
    await flush(2);
    const opened = page.state.conversations[0]!.id;

    await ask(page, "Where is the refresh token rotated?");
    await flush(2);

    expect(calls(page.request)).not.toContain(`DELETE /chat/conversations/${opened}`);
    expect(page.state.conversations.map((c) => c.id)).toEqual([opened]);
  });

  it("keeps the conversation when the first question lands", async () => {
    const page = await open({ conversations: [], messages: [] });

    await ask(page, "Where is the refresh token rotated?");
    await flush(2);

    expect(calls(page.request)).toContain("POST /chat/conversations");
    expect(calls(page.request).some((one) => one.startsWith("DELETE /chat/conversations/"))).toBe(false);
    expect(page.state.conversations).toHaveLength(1);
  });
});

describe("/chat · conversations", () => {
  it("opens the most recent conversation and says so in the URL", async () => {
    const { route, request } = await open({
      conversations: [makeConversation({ id: 12 }), makeConversation({ id: 9, title: "Older" })],
    });

    expect(route.query.c).toBe("12");
    expect(calls(request)).toContain("GET /chat/conversations/12");
  });

  it("reads the conversation back out of ?c= on load", async () => {
    const { request } = await open(
      { conversations: [makeConversation({ id: 12 }), makeConversation({ id: 9, title: "Older" })] },
      { query: { c: "9" } },
    );

    expect(calls(request)).toContain("GET /chat/conversations/9");
    expect(calls(request)).not.toContain("GET /chat/conversations/12");
  });

  it("asks before deleting a conversation", async () => {
    const { wrapper, request } = await open();

    await wrapper.get('[data-test="conversation-delete"]').trigger("click");
    await flush(2);
    expect(calls(request)).not.toContain("DELETE /chat/conversations/12");

    (document.querySelector('[data-test="conversation-delete-confirm"]') as HTMLElement).click();
    await flush();

    expect(calls(request)).toContain("DELETE /chat/conversations/12");
  });

  it("does not confirm a conversation exists when the API answers 404", async () => {
    const { wrapper } = await open({ detailError: apiError(404, "Conversation not found") });

    expect(wrapper.get('[data-test="thread-missing"]').text()).toMatch(/not available to you/i);
    expect(wrapper.text()).not.toMatch(/someone else|forbidden|no permission/i);
  });

  it("invites a first question rather than showing an empty list", async () => {
    const { wrapper } = await open({ conversations: [], messages: [] });

    expect(wrapper.find('[data-test="thread"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="no-conversations"]').text()).toMatch(/no conversations yet/i);
    expect(wrapper.get('[data-test="thread-empty"]').text()).toMatch(/ask the first question/i);
  });

  it("points a person with nothing indexed at the index panel", async () => {
    const { wrapper } = await open({ repos: [] });

    expect(wrapper.get('[data-test="no-repos"]').text()).toMatch(/nothing is indexed yet/i);
    expect(wrapper.find('[data-test="scope"]').exists()).toBe(false);
  });
});
