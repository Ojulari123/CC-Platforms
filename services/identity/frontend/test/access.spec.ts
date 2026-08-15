import { describe, expect, it } from "vitest";
import {
  CAPS,
  capsAllowed,
  capsRefused,
  maxScope,
  peopleAllowed,
  verdict,
} from "~/pages/access.vue";
import type { AccessPerson } from "~/pages/access.vue";

function person(over: Partial<AccessPerson> & { id: number; name: string }): AccessPerson {
  return {
    firstName: over.name.split(" ")[0] ?? "",
    active: true,
    platformAdmin: false,
    role: "engineer",
    deptName: "Software Dev",
    deptCount: 1,
    ...over,
  };
}

const ENGINEER = person({ id: 1, name: "Tunde Balogun" });
const MANAGER = person({ id: 2, name: "Ada Nwosu", role: "manager" });
const DEPT_ADMIN = person({ id: 3, name: "Zainab Yusuf", role: "admin" });
const PLATFORM = person({ id: 4, name: "Adeoluwa Ojulari", role: "admin", platformAdmin: true });
const UNPLACED = person({ id: 5, name: "Femi Adeyemi", role: null, deptName: null, deptCount: 0 });
const DEACTIVATED = person({ id: 6, name: "Grace Okonkwo", active: false, role: "admin" });

const EVERYONE = [ENGINEER, MANAGER, DEPT_ADMIN, PLATFORM, UNPLACED, DEACTIVATED];

function cap(id: string) {
  return CAPS.find((c) => c.id === id)!;
}

describe("the capability list", () => {
  it("is the twelve the spec names, with the guard that enforces each", () => {
    expect(CAPS).toHaveLength(12);
    expect(CAPS.map((c) => c.id)).toEqual([
      "report_own",
      "report_decide",
      "repo_file",
      "report_read",
      "invite",
      "place",
      "role",
      "dept_rename",
      "dept_create",
      "dept_head",
      "directory",
      "deactivate",
    ]);
    // Guard names are real dependencies, not decoration.
    expect(cap("invite").guard).toBe("dept_admin");
    expect(cap("dept_create").guard).toBe("require_platform_admin");
    expect(cap("report_read").guard).toBe("role == manager");
    expect(cap("repo_file").guard).toBe("_require_can_admin_repo");
  });
});

describe("verdict", () => {
  it("refuses everything for a deactivated account, before any role is read", () => {
    for (const c of CAPS) {
      const v = verdict(DEACTIVATED, c);
      expect(v.allowed).toBe(false);
      expect(v.reason).toContain("deactivated");
    }
    expect(capsAllowed(DEACTIVATED)).toEqual([]);
    expect(maxScope(DEACTIVATED)).toBe(-1);
  });

  it("lets everybody write their own report and nothing else, for an engineer", () => {
    expect(verdict(ENGINEER, cap("report_own")).allowed).toBe(true);
    expect(capsAllowed(ENGINEER).map((c) => c.id)).toEqual(["report_own"]);
    expect(maxScope(ENGINEER)).toBe(0);
  });

  it("gives the department-wide read to manager and to nobody else", () => {
    expect(verdict(MANAGER, cap("report_read")).allowed).toBe(true);
    expect(verdict(DEPT_ADMIN, cap("report_read")).allowed).toBe(false);
    expect(verdict(PLATFORM, cap("report_read")).allowed).toBe(false);
    expect(verdict(DEPT_ADMIN, cap("report_read")).reason).toContain("belongs to manager");
  });

  it("stops a department admin at the edge of their department", () => {
    expect(verdict(DEPT_ADMIN, cap("invite")).allowed).toBe(true);
    expect(verdict(DEPT_ADMIN, cap("dept_rename")).allowed).toBe(true);
    expect(verdict(DEPT_ADMIN, cap("dept_create")).allowed).toBe(false);
    expect(verdict(DEPT_ADMIN, cap("directory")).allowed).toBe(false);
    expect(maxScope(DEPT_ADMIN)).toBe(2);
  });

  it("does not treat an unplaced account as a department admin", () => {
    expect(verdict(UNPLACED, cap("invite")).allowed).toBe(false);
    expect(verdict(UNPLACED, cap("invite")).reason).toContain("belongs to no department");
    expect(capsAllowed(UNPLACED).map((c) => c.id)).toEqual(["report_own"]);
  });

  it("gives a platform admin everything except the manager read", () => {
    expect(capsRefused(PLATFORM).map((c) => c.id)).toEqual(["report_read"]);
    expect(maxScope(PLATFORM)).toBe(3);
  });

  it("says out loud that repository leadership is not readable from identity", () => {
    expect(verdict(ENGINEER, cap("report_decide")).caveat).toContain("lives in Pulse");
    expect(verdict(DEPT_ADMIN, cap("report_decide")).caveat).toContain("lives in Pulse");
  });

  it("names the guard on the answer, not just on the capability", () => {
    for (const c of CAPS) {
      expect(verdict(ENGINEER, c).guard).toBe(c.guard);
    }
  });
});

describe("both views are the same function", () => {
  it("by-person and by-capability never disagree about anybody", () => {
    for (const c of CAPS) {
      const fromCapabilityView = peopleAllowed(EVERYONE, c).map((p) => p.id);
      const fromPersonView = EVERYONE.filter((p) => capsAllowed(p).some((x) => x.id === c.id)).map((p) => p.id);
      expect(fromPersonView).toEqual(fromCapabilityView);
    }
  });

  it("can and cannot partition the twelve for every person", () => {
    for (const p of EVERYONE) {
      const can = capsAllowed(p);
      const cannot = capsRefused(p);
      expect(can.length + cannot.length).toBe(CAPS.length);
      expect(can.filter((c) => cannot.some((x) => x.id === c.id))).toEqual([]);
    }
  });

  it("the reach ladder agrees with the can list", () => {
    for (const p of EVERYONE) {
      const highest = capsAllowed(p).reduce((top, c) => Math.max(top, c.scope), -1);
      expect(maxScope(p)).toBe(highest);
    }
  });
});
