import { describe, expect, it } from "vitest";
import {
  canDecide,
  duplicateReport,
  firstFreeWeek,
  pageCount,
  sortByWeek,
  statusCounts,
} from "~/utils/pulse";
import { makeReport, makeRepo, makeUser } from "./fixtures";

describe("duplicateReport", () => {
  const mine = makeReport({ id: 341, author_user_id: 1042, repo_id: 4, week_start: "2026-08-03" });
  const theirs = makeReport({ id: 342, author_user_id: 1043, repo_id: 4, week_start: "2026-08-03" });

  it("finds your own report for the same repository and week", () => {
    expect(duplicateReport([mine], 4, "2026-08-03", 1042)?.id).toBe(341);
  });

  it("ignores somebody else's report on the same repository and week", () => {
    // uq_report_author_repo_week is (author_user_id, repo_id, week_start): a colleague
    // has not "taken" your week.
    expect(duplicateReport([theirs], 4, "2026-08-03", 1042)).toBeNull();
  });

  it("ignores your own report on a different week or a different repository", () => {
    expect(duplicateReport([mine], 4, "2026-07-27", 1042)).toBeNull();
    expect(duplicateReport([mine], 9, "2026-08-03", 1042)).toBeNull();
  });

  it("has no opinion before a repository is chosen", () => {
    expect(duplicateReport([mine], null, "2026-08-03", 1042)).toBeNull();
  });
});

describe("firstFreeWeek", () => {
  const weeks = ["2026-08-03", "2026-07-27", "2026-07-20"];

  it("offers the first week you have not already written about", () => {
    const taken = [makeReport({ week_start: "2026-08-03", author_user_id: 1042, repo_id: 4 })];
    expect(firstFreeWeek(weeks, taken, 4, 1042)).toBe("2026-07-27");
  });

  it("offers nothing when every week on the list is already yours", () => {
    const taken = weeks.map((week, i) =>
      makeReport({ id: 300 + i, week_start: week, author_user_id: 1042, repo_id: 4 }),
    );
    expect(firstFreeWeek(weeks, taken, 4, 1042)).toBeNull();
  });
});

describe("canDecide", () => {
  const submitted = makeReport({ author_user_id: 1042, status: "submitted", dept_id: 1, repo_id: 4 });

  it("refuses the author, whatever else they are", () => {
    const verdict = canDecide(submitted, makeRepo(), makeUser({ id: 1042, is_platform_admin: true }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toMatch(/you wrote this report/i);
  });

  it("refuses the author even when they are the repository's lead", () => {
    const repo = makeRepo({ lead_user_id: 1042 });
    expect(canDecide(submitted, repo, makeUser({ id: 1042 })).allowed).toBe(false);
  });

  it("allows the repository's lead", () => {
    const repo = makeRepo({ lead_user_id: 1043 });
    expect(canDecide(submitted, repo, makeUser({ id: 1043 })).allowed).toBe(true);
  });

  it("allows the repository's deputy", () => {
    const repo = makeRepo({ deputy_user_id: 1051 });
    expect(canDecide(submitted, repo, makeUser({ id: 1051 })).allowed).toBe(true);
  });

  it("allows an admin of the department the report carries", () => {
    const user = makeUser({
      id: 1099,
      memberships: [{ dept_id: 1, dept_name: "Software Dev", team_id: null, team_name: null, role: "admin" }],
    });
    expect(canDecide(submitted, makeRepo(), user).allowed).toBe(true);
  });

  it("refuses a department admin of a different department", () => {
    const user = makeUser({
      id: 1099,
      memberships: [{ dept_id: 2, dept_name: "Data", team_id: null, team_name: null, role: "admin" }],
    });
    const verdict = canDecide(submitted, makeRepo(), user);
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toMatch(/lead or deputy/i);
  });

  it("refuses a member who is not an admin", () => {
    const user = makeUser({
      id: 1099,
      memberships: [{ dept_id: 1, dept_name: "Software Dev", team_id: null, team_name: null, role: "member" }],
    });
    expect(canDecide(submitted, makeRepo(), user).allowed).toBe(false);
  });

  it("offers no decision on a report that is not awaiting one", () => {
    const approved = makeReport({ author_user_id: 1042, status: "approved" });
    const verdict = canDecide(approved, makeRepo({ lead_user_id: 1043 }), makeUser({ id: 1043 }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toMatch(/only exists while one is being asked for/i);
  });

  it("allows a platform admin on somebody else's submitted report", () => {
    const user = makeUser({ id: 9, is_platform_admin: true });
    expect(canDecide(submitted, makeRepo(), user).allowed).toBe(true);
  });
});

describe("list shaping", () => {
  const rows = [
    makeReport({ id: 1, status: "draft", week_start: "2026-07-27" }),
    makeReport({ id: 2, status: "approved", week_start: "2026-08-03" }),
    makeReport({ id: 3, status: "approved", week_start: "2026-08-03" }),
  ];

  it("counts every status, including the ones with nothing in them", () => {
    expect(statusCounts(rows)).toEqual({
      draft: 1,
      submitted: 0,
      changes_requested: 0,
      approved: 2,
      rejected: 0,
    });
  });

  it("sorts newest week first, newest id first inside a week", () => {
    expect(sortByWeek(rows, "desc").map((r) => r.id)).toEqual([3, 2, 1]);
    expect(sortByWeek(rows, "asc").map((r) => r.id)).toEqual([1, 3, 2]);
  });

  it("pages at eight and never reports fewer than one page", () => {
    expect(pageCount(0, 8)).toBe(1);
    expect(pageCount(8, 8)).toBe(1);
    expect(pageCount(9, 8)).toBe(2);
    expect(pageCount(22, 8)).toBe(3);
  });
});
