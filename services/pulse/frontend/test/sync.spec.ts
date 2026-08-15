import { describe, expect, it } from "vitest";
import { failedRuns, inferTrigger, parseSyncCounts, runDuration } from "~/utils/pulse";
import { makeRun } from "./fixtures";

describe("parseSyncCounts", () => {
  it("reads the four counts the worker writes, stripping the repository prefix", () => {
    expect(parseSyncCounts("acme/pulse-api: commits=3, branches=0, pull_requests=1, issues=0")).toEqual({
      commits: 3,
      branches: 0,
      pull_requests: 1,
      issues: 0,
    });
  });

  it("parses a row with no name prefix, which is what an unresolved repository writes", () => {
    expect(parseSyncCounts("commits=4, branches=0, pull_requests=1, issues=0")).toEqual({
      commits: 4,
      branches: 0,
      pull_requests: 1,
      issues: 0,
    });
  });

  it("returns null for a skip, so the row renders em dashes rather than zeros", () => {
    expect(parseSyncCounts("northwind/billing-service: not tracked")).toBeNull();
  });

  it("returns null for a rate limit sentence, which contains a colon of its own", () => {
    const detail =
      "acme/pulse-sync: GitHub API rate limit exceeded for this token; it resets at 2026-08-11T10:14:00Z.";
    expect(parseSyncCounts(detail)).toBeNull();
  });

  it("returns null for a null detail", () => {
    expect(parseSyncCounts(null)).toBeNull();
  });

  it("does not invent a commits key", () => {
    expect(parseSyncCounts("acme/pulse-api: branches=1, issues=0")).toBeNull();
  });

  it("counts no reviews, because reviews are ingested with their pull request", () => {
    const counts = parseSyncCounts("acme/pulse-api: commits=3, branches=0, pull_requests=1, issues=0");
    expect(counts).not.toBeNull();
    expect(Object.keys(counts!)).toEqual(["commits", "branches", "pull_requests", "issues"]);
  });
});

describe("runDuration", () => {
  it("reports sub-second passes in milliseconds", () => {
    expect(
      runDuration({ started_at: "2026-08-11T02:00:00.000Z", finished_at: "2026-08-11T02:00:00.300Z" }),
    ).toBe("300ms");
  });

  it("reports seconds, then minutes and seconds", () => {
    expect(runDuration({ started_at: "2026-08-11T02:00:00Z", finished_at: "2026-08-11T02:00:27Z" })).toBe("27s");
    expect(runDuration({ started_at: "2026-08-11T02:00:00Z", finished_at: "2026-08-11T02:01:05Z" })).toBe("1m 05s");
  });

  it("has nothing to report for a run that never finished", () => {
    expect(runDuration({ started_at: "2026-08-11T02:00:00Z", finished_at: null })).toBe("—");
  });
});

describe("inferTrigger", () => {
  it("calls the 02:00 UTC beat scheduled", () => {
    expect(inferTrigger({ started_at: "2026-08-11T02:00:04Z" })).toBe("scheduled");
  });

  it("calls anything else manual — an inference, not a field", () => {
    expect(inferTrigger({ started_at: "2026-08-11T09:42:03Z" })).toBe("manual");
  });
});

describe("failedRuns", () => {
  it("counts errors and rate limits, not skips", () => {
    const runs = [
      makeRun({ id: 1, status: "success" }),
      makeRun({ id: 2, status: "skipped", detail: "acme/x: not tracked" }),
      makeRun({ id: 3, status: "error", detail: "acme/forge-web: 404 Not Found" }),
      makeRun({ id: 4, status: "rate_limited", detail: "acme/pulse-sync: rate limit" }),
    ];
    expect(failedRuns(runs).map((r) => r.id)).toEqual([3, 4]);
  });
});
