import { describe, expect, it, vi } from "vitest";
import { apiMessage } from "~/utils/format";

/* An error panel says two things at once: what went wrong, and what to do about it. The
   API can write the first sentence when the failure is the caller's — a 4xx names the
   field, the clash, the missing permission. When the server is the thing that broke, the
   only text on hand is an exception message, which is written for a log and has carried
   configuration key names, so it goes to the console and the panel keeps its own copy. */

const err = (status: number, detail: unknown) => ({ statusCode: status, data: { detail } });

describe("apiMessage", () => {
  it("shows what the API said about a request the caller got wrong", () => {
    expect(apiMessage(err(422, "week_start must be a Monday"), "fallback")).toBe("week_start must be a Monday");
    expect(apiMessage(err(409, "A report already exists for that repository and week"), "fallback")).toBe(
      "A report already exists for that repository and week",
    );
    expect(apiMessage(err(403, "You do not lead this repository"), "fallback")).toBe("You do not lead this repository");
    expect(apiMessage(err(400, "repo_id must be an integer"), "fallback")).toBe("repo_id must be an integer");
    expect(apiMessage(err(404, "No such report"), "fallback")).toBe("No such report");
  });

  it("keeps a server failure off the screen and puts it in the console instead", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiMessage(err(500, "boom"), "The Pulse API did not answer.")).toBe("The Pulse API did not answer.");
    expect(spy).toHaveBeenCalledWith("[pulse] API 500: boom");
  });

  it("treats a 503 the same way, because its detail names configuration keys", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const detail = "GitHub OAuth is not configured on the server (GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET)";
    expect(apiMessage(err(503, detail), "GitHub is not available right now.")).toBe("GitHub is not available right now.");
  });

  it("logs one line per failure, not one per re-render", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const failure = err(502, "GitHub rejected the authorization: bad_verification_code");
    apiMessage(failure, "fallback");
    apiMessage(failure, "fallback");
    apiMessage(failure, "fallback");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("leaves a 401 to the auth layer rather than printing its detail in a panel", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiMessage(err(401, "Not authenticated"), "Sign in again.")).toBe("Sign in again.");
  });

  it("falls back when there is no detail at all, and does not log an empty line", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiMessage(new TypeError("Failed to fetch"), "Could not reach Pulse.")).toBe("Could not reach Pulse.");
    expect(apiMessage(err(500, "   "), "Could not reach Pulse.")).toBe("Could not reach Pulse.");
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not show a detail from a request that never reached the API", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(apiMessage({ data: { detail: "socket hang up" } }, "Could not reach Pulse.")).toBe("Could not reach Pulse.");
    expect(spy).toHaveBeenCalledWith("[pulse] API request failed: socket hang up");
  });
});
