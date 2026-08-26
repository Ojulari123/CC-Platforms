import { beforeEach, describe, expect, it } from "vitest";
import { failureFingerprint } from "~/utils/pulse";
import { apiError, flush, mountPage } from "./pageHarness";
import { makeAccount, makeRepo, makeRun, makeUser } from "./fixtures";

/* Two behaviours fixed in the same pass, both of which are invisible to a unit test of the
   helpers alone: what the Overview's tab rail is allowed to contain, and whether the stale
   sync notice can be put away without being able to hide a new failure. */

const ME = makeUser();

function page(rows: unknown[] = []) {
  return ({ path }: { path: string }) => {
    if (path === "/reports/review-queue") return { items: rows, total: rows.length };
    if (path === "/reports") return { items: rows, total: rows.length };
    if (path.startsWith("/activity")) throw apiError(404);
    return { items: [], total: 0 };
  };
}

describe("/ · the recent-reports strip", () => {
  /* A tablist is one no-wrap row — its indicator is positioned on offsetLeft alone, so a
     second line would strand it. The two page actions used to ride in the rail's trailing
     slot, which put four items on that row and overflowed it at 390px. */
  it("keeps the tab rail down to its tabs, with the actions in the heading row above", async () => {
    const { wrapper } = await mountPage({ page: "home", api: page(), me: ME });

    const rail = wrapper.get('[role="tablist"]');
    expect(rail.findAll('[role="tab"]')).toHaveLength(2);
    expect(rail.findAll("a")).toHaveLength(0);
    expect(rail.text()).not.toContain("All reports");
  });

  it("gives the section a visible heading rather than a screen-reader-only one", async () => {
    const { wrapper } = await mountPage({ page: "home", api: page(), me: ME });

    const heading = wrapper.get("#recent-reports");
    expect(heading.text()).toBe("Recent reports");
    expect(heading.classes()).not.toContain("sr-only");
  });

  // Both ways of writing one, side by side, in the words the rest of the product uses.
  it("offers both kinds of new report from the heading row", async () => {
    const { wrapper } = await mountPage({ page: "home", api: page(), me: ME });

    const links = wrapper.findAll("a").map((a) => a.text());
    expect(links).toContain("New weekly report");
    expect(links).toContain("New custom report");
  });
});

describe("failureFingerprint", () => {
  it("is empty when nothing failed", () => {
    expect(failureFingerprint([makeRun(), makeRun({ id: 2 })])).toBe("");
  });

  it("ignores the order the API returned the runs in", () => {
    const a = makeRun({ id: 9, status: "error" });
    const b = makeRun({ id: 4, status: "rate_limited" });
    expect(failureFingerprint([a, b])).toBe(failureFingerprint([b, a]));
  });

  // The whole point: a new failure has to be a new notice.
  it("changes when a different run fails", () => {
    const first = failureFingerprint([makeRun({ id: 9, status: "error" })]);
    const second = failureFingerprint([
      makeRun({ id: 9, status: "error" }),
      makeRun({ id: 11, status: "error" }),
    ]);
    expect(second).not.toBe(first);
  });

  it("does not change when a successful run is added beside the failing one", () => {
    const failing = makeRun({ id: 9, status: "error" });
    expect(failureFingerprint([failing, makeRun({ id: 12 })])).toBe(failureFingerprint([failing]));
  });
});

describe("/sync · the stale notice", () => {
  const RUNS = [
    makeRun({ id: 9, status: "error", detail: "acme/pulse-api: boom" }),
    makeRun({ id: 10 }),
  ];

  function sync(runs = RUNS) {
    return ({ path }: { path: string }) => {
      // 200 with the account inside a wrapper. Not connected is `account: null`, not a 404.
      if (path === "/github/account") return { account: makeAccount() };
      if (path === "/github/sync-runs") return { items: runs, total: runs.length };
      return { items: [], total: 0 };
    };
  }

  beforeEach(() => {
    window.localStorage.clear();
  });

  async function open(runs = RUNS) {
    return mountPage({ page: "sync", api: sync(runs), me: ME, repositories: [makeRepo()] });
  }

  it("shows the notice, with a named control for putting it away", async () => {
    const { wrapper } = await open();
    expect(wrapper.get('[data-test="stale-notice"]').text()).toContain("did not complete");
    expect(wrapper.get('[data-test="stale-dismiss"]').attributes("aria-label")).toBe(
      "Dismiss the stale sync notice",
    );
  });

  it("puts it away, and remembers that across a reload", async () => {
    const first = await open();
    await first.wrapper.get('[data-test="stale-dismiss"]').trigger("click");
    await flush();
    expect(first.wrapper.find('[data-test="stale-notice"]').exists()).toBe(false);

    const second = await open();
    expect(second.wrapper.find('[data-test="stale-notice"]').exists()).toBe(false);
  });

  /* The reason the dismissal is keyed to the failing runs rather than to the notice. A
     notice that can be silenced for good while the thing it warns about carries on is
     worse than no notice. */
  it("comes back when a different run fails", async () => {
    const first = await open();
    await first.wrapper.get('[data-test="stale-dismiss"]').trigger("click");
    await flush();

    const next = await open([...RUNS, makeRun({ id: 14, status: "rate_limited" })]);
    expect(next.wrapper.find('[data-test="stale-notice"]').exists()).toBe(true);
  });

  it("stays away while the same runs are the ones failing", async () => {
    const first = await open();
    await first.wrapper.get('[data-test="stale-dismiss"]').trigger("click");
    await flush();

    // A new successful run does not change which runs are failing.
    const next = await open([...RUNS, makeRun({ id: 15 })]);
    expect(next.wrapper.find('[data-test="stale-notice"]').exists()).toBe(false);
  });
});

describe("/sync · the GitHub connection", () => {
  function api(account: unknown, thrown?: unknown) {
    return ({ path }: { path: string }) => {
      if (path === "/github/account") {
        if (thrown) throw thrown;
        return { account };
      }
      if (path === "/github/sync-runs") return { items: [], total: 0 };
      return { items: [], total: 0 };
    };
  }

  /* Never having connected GitHub is where every account starts, so the API answers it
     with a 200 and a null inside. Nothing here may treat that as a failure — it used to
     be a 404, which put a red line in the console of every user who had not connected. */
  it("reads account: null as not connected, not as a failure", async () => {
    const { wrapper } = await mountPage({ page: "sync", api: api(null), me: ME, repositories: [makeRepo()] });

    expect(wrapper.text()).toContain("No GitHub account");
    expect(wrapper.text()).toContain("Connect GitHub");
    expect(wrapper.text()).not.toMatch(/could not read the github connection/i);
  });

  it("shows the connected account out of the wrapper", async () => {
    const { wrapper } = await mountPage({
      page: "sync",
      api: api(makeAccount({ github_login: "ada", github_user_id: 55123 })),
      me: ME,
      repositories: [makeRepo()],
    });

    expect(wrapper.text()).toContain("ada");
    expect(wrapper.text()).toContain("55123");
    expect(wrapper.text()).toContain("Connected");
  });

  /* Reconnect leaves the stored account alone, so the connection on screen keeps working
     until GitHub confirms a new one. Both facts are worth saying, because the button sits
     next to Disconnect. */
  it("reconnects through /github/reconnect, and says the current connection survives it", async () => {
    const { wrapper, request } = await mountPage({
      page: "sync",
      api: api(makeAccount()),
      me: ME,
      repositories: [makeRepo()],
    });

    expect(wrapper.get('[data-test="reconnect-note"]').text()).toMatch(/keeps working until it does/i);

    await wrapper.get('[data-test="reconnect"]').trigger("click");
    await flush();

    const calls = request.mock.calls.map(([path, opts]) => `${(opts as { method?: string })?.method ?? "GET"} ${path}`);
    expect(calls).toContain("POST /github/reconnect");
    expect(calls).not.toContain("GET /github/connect");
  });

  it("uses /github/connect for a first connection", async () => {
    const { wrapper, request } = await mountPage({
      page: "sync",
      api: api(null),
      me: ME,
      repositories: [makeRepo()],
    });

    expect(wrapper.find('[data-test="reconnect"]').exists()).toBe(false);
    await wrapper.findAllComponents({ name: "Btn" }).find((b) => b.text() === "Connect GitHub")!.trigger("click");
    await flush();

    const calls = request.mock.calls.map(([path, opts]) => `${(opts as { method?: string })?.method ?? "GET"} ${path}`);
    expect(calls).toContain("GET /github/connect");
    expect(calls).not.toContain("POST /github/reconnect");
  });

  // A 404 has one meaning left and it is not this one, so a real failure still says so.
  it("still reports a failure that is a failure", async () => {
    const { wrapper } = await mountPage({
      page: "sync",
      api: api(null, apiError(500, "boom")),
      me: ME,
      repositories: [makeRepo()],
    });

    expect(wrapper.text()).toMatch(/could not read the github connection/i);
  });
});
