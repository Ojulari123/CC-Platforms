import { describe, expect, it } from "vitest";
import {
  PEOPLE_FILTERS,
  canDeleteAccount,
  filterPeople,
  sortPeople,
  toggleSelection,
  visibleSelection,
} from "~/pages/users.vue";
import type { DirectoryRow } from "~/pages/users.vue";

function row(over: Partial<DirectoryRow> & { id: number; name: string }): DirectoryRow {
  return {
    email: `${over.name.toLowerCase().replace(/\s+/g, ".")}@cyphercrescent.org`,
    first_name: over.name.split(" ")[0] ?? "",
    last_name: over.name.split(" ")[1] ?? "",
    is_active: true,
    is_platform_admin: false,
    email_verified: true,
    created_at: "2026-01-01T00:00:00Z",
    placements: [],
    ...over,
  };
}

const ADA = row({ id: 1, name: "Ada Nwosu", placements: [{ deptId: 1, deptName: "Software Dev", role: "manager" }] });
const FEMI = row({ id: 2, name: "Femi Adeyemi", email_verified: false });
const GRACE = row({ id: 3, name: "Grace Okonkwo", is_active: false });
const ZAINAB = row({
  id: 4,
  name: "Zainab Yusuf",
  is_platform_admin: true,
  placements: [{ deptId: 6, deptName: "Data", role: "admin" }],
});

const ALL = [ADA, FEMI, GRACE, ZAINAB];

describe("the people filters", () => {
  it("has one match function per tab and they partition the states the screen claims", () => {
    const byId = Object.fromEntries(PEOPLE_FILTERS.map((f) => [f.id, ALL.filter(f.match).map((r) => r.id)]));
    expect(byId.all).toEqual([1, 2, 3, 4]);
    expect(byId.active).toEqual([1, 2, 4]);
    expect(byId.deactivated).toEqual([3]);
    expect(byId.unverified).toEqual([2]);
    // Admins is both kinds: platform admin, and admin on a membership row.
    expect(byId.admins).toEqual([4]);
  });

  it("counts a department admin who is not a platform admin as an admin", () => {
    const deptAdmin = row({ id: 9, name: "Tunde Balogun", placements: [{ deptId: 1, deptName: "Software Dev", role: "admin" }] });
    expect(PEOPLE_FILTERS.find((f) => f.id === "admins")!.match(deptAdmin)).toBe(true);
  });
});

describe("search", () => {
  it("matches on name, email and user_id, case-insensitively", () => {
    expect(filterPeople(ALL, "ada", "all").map((r) => r.id)).toEqual([1]);
    expect(filterPeople(ALL, "GRACE.OKONKWO@", "all").map((r) => r.id)).toEqual([3]);
    expect(filterPeople(ALL, "4", "all").map((r) => r.id)).toEqual([4]);
  });

  it("applies the tab and the query together, not one or the other", () => {
    // Grace matches the query but is deactivated, so the Active tab must drop her.
    expect(filterPeople(ALL, "okonkwo", "deactivated").map((r) => r.id)).toEqual([3]);
    expect(filterPeople(ALL, "okonkwo", "active")).toEqual([]);
  });

  it("ignores surrounding whitespace and returns everything for an empty query", () => {
    expect(filterPeople(ALL, "   ", "all")).toHaveLength(4);
  });
});

describe("sort", () => {
  it("flips between A–Z and Z–A without mutating the source array", () => {
    const source = [...ALL];
    expect(sortPeople(source, "asc").map((r) => r.name)).toEqual([
      "Ada Nwosu",
      "Femi Adeyemi",
      "Grace Okonkwo",
      "Zainab Yusuf",
    ]);
    expect(sortPeople(source, "desc").map((r) => r.name)).toEqual([
      "Zainab Yusuf",
      "Grace Okonkwo",
      "Femi Adeyemi",
      "Ada Nwosu",
    ]);
    expect(source.map((r) => r.id)).toEqual([1, 2, 3, 4]);
  });
});

describe("bulk selection", () => {
  it("adds and removes one row", () => {
    expect(toggleSelection([], 1)).toEqual([1]);
    expect(toggleSelection([1, 2], 1)).toEqual([2]);
  });

  it("never acts on a row the filter has taken off screen", () => {
    const selected = [1, 3];
    const onScreen = filterPeople(ALL, "", "active");
    // Grace is selected but deactivated, so the Active tab must not carry her into a
    // bulk action.
    expect(visibleSelection(selected, onScreen)).toEqual([1]);
  });

  it("select-all only ever covers the rows currently shown", () => {
    const onScreen = filterPeople(ALL, "", "unverified");
    const selected = onScreen.map((r) => r.id);
    expect(visibleSelection(selected, onScreen)).toEqual([2]);
    expect(visibleSelection(selected, onScreen).length === onScreen.length).toBe(true);
  });
});

describe("the delete guard", () => {
  it("blocks while the person still belongs to a department", () => {
    expect(canDeleteAccount(ADA)).toBe(false);
    expect(canDeleteAccount(ZAINAB)).toBe(false);
  });

  it("allows an account that belongs to no department", () => {
    expect(canDeleteAccount(FEMI)).toBe(true);
    expect(canDeleteAccount(GRACE)).toBe(true);
  });

  it("blocks on any membership, not just the first", () => {
    const two = row({
      id: 10,
      name: "Ngozi Obi",
      placements: [
        { deptId: 1, deptName: "Software Dev", role: "engineer" },
        { deptId: 6, deptName: "Data", role: "engineer" },
      ],
    });
    expect(canDeleteAccount(two)).toBe(false);
  });
});
