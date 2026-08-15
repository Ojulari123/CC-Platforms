import { describe, expect, it } from "vitest";
import { filterSessions, isIdle, isLive, sessionState } from "~/pages/sessions.vue";
import type { SessionResponse } from "~/pages/sessions.vue";

const NOW = Date.parse("2026-08-13T12:00:00Z");
const DAY = 86_400_000;

function session(over: Partial<SessionResponse> & { session_id: string }): SessionResponse {
  return {
    started_at: new Date(NOW - 7 * DAY).toISOString(),
    last_used_at: new Date(NOW - 60_000).toISOString(),
    rotations: 27,
    expires_at: new Date(NOW + 7 * DAY).toISOString(),
    is_revoked: false,
    is_current: false,
    ...over,
  };
}

const REFRESHING = session({ session_id: "fam_8Kd2pQ", is_current: true });
const IDLE = session({ session_id: "fam_5Rt7wN", last_used_at: new Date(NOW - 4 * DAY).toISOString() });
const EXPIRED = session({ session_id: "fam_9Yh4vB", expires_at: new Date(NOW - DAY).toISOString() });
const REVOKED = session({ session_id: "fam_2Lm0zX", is_revoked: true });

const ALL = [REFRESHING, IDLE, EXPIRED, REVOKED];

describe("session state", () => {
  it("reads revoked before expiry, and expiry before idleness", () => {
    expect(sessionState(REFRESHING, NOW)).toBe("refreshing");
    expect(sessionState(IDLE, NOW)).toBe("idle");
    expect(sessionState(EXPIRED, NOW)).toBe("expired");
    expect(sessionState(REVOKED, NOW)).toBe("revoked");
  });

  it("counts a family as live only while it is neither revoked nor past its expiry", () => {
    expect(isLive(REFRESHING, NOW)).toBe(true);
    expect(isLive(IDLE, NOW)).toBe(true);
    expect(isLive(EXPIRED, NOW)).toBe(false);
    expect(isLive(REVOKED, NOW)).toBe(false);
  });

  it("draws the idle line at three days since the last refresh", () => {
    const justUnder = session({ session_id: "a", last_used_at: new Date(NOW - 3 * DAY + 1000).toISOString() });
    const justOver = session({ session_id: "b", last_used_at: new Date(NOW - 3 * DAY - 1000).toISOString() });
    expect(isIdle(justUnder, NOW)).toBe(false);
    expect(isIdle(justOver, NOW)).toBe(true);
  });
});

describe("the filter tabs", () => {
  it("Active is live and recently refreshed", () => {
    expect(filterSessions(ALL, "active", NOW).map((s) => s.session_id)).toEqual(["fam_8Kd2pQ"]);
  });

  it("Stale is everything Active is not, so the two always add up to All", () => {
    const active = filterSessions(ALL, "active", NOW);
    const stale = filterSessions(ALL, "stale", NOW);
    expect(stale.map((s) => s.session_id)).toEqual(["fam_5Rt7wN", "fam_9Yh4vB", "fam_2Lm0zX"]);
    expect(active.length + stale.length).toBe(filterSessions(ALL, "all", NOW).length);
  });
});
