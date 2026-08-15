import { describe, expect, it, vi } from "vitest";
import { changeEmailMessage, newEmailError, SENT, sentMessage } from "~/pages/account.vue";
import { CONFIRM_COPY, confirmState, isRetryable, runConfirm } from "~/pages/confirm-email-change.vue";

/* The address is the sign-in handle, so this flow is the one place on the account screen
   where being vague is the correct answer: POST /auth/change-email answers 204 whether or
   not anything was sent, because an address that already belongs to someone must not be
   told apart from a free one. The success copy is asserted here in full for that reason —
   a future edit that turns it into "we've sent you a link" is a lie about a taken
   address, and this test is what catches it. */

function refusal(status: number, detail?: unknown) {
  return { statusCode: status, data: detail === undefined ? undefined : { detail } };
}

describe("the new address field", () => {
  it("asks for an address rather than submitting an empty one", () => {
    expect(newEmailError("")).toBe("Enter the new email address.");
    expect(newEmailError("   ")).toBe("Enter the new email address.");
  });

  it.each(["nope", "nope@", "@cyphercrescent.com", "two @ signs@x.com", "no.dot@localhost"])(
    "refuses %s before it can become a 422",
    (value) => {
      expect(newEmailError(value)).toBe("Enter a valid email address.");
    },
  );

  it("accepts a plus-alias, which is a real address and not a typo", () => {
    expect(newEmailError("oj.demo+new@cyphercrescent.com")).toBeNull();
  });

  it("ignores surrounding whitespace, because a pasted address carries it", () => {
    expect(newEmailError("  oj.demo@cyphercrescent.com  ")).toBeNull();
  });
});

describe("what a 204 is allowed to claim", () => {
  it("promises a link only if the address is free, because a taken one answers the same 204", () => {
    expect(sentMessage("new@example.com")).toBe(
      "Check your new inbox. If new@example.com isn't already tied to another account, a confirmation link is on its way "
        + "to it. The link expires in 30 minutes. Nothing changes until you open it, and we've emailed your current address "
        + "to let you know.",
    );
  });

  it.each(["we sent", "we have sent", "we've sent", "a link has been sent", "check your email for the link"])(
    "never says %s",
    (claim) => {
      expect(sentMessage("new@example.com").toLowerCase()).not.toContain(claim);
    },
  );

  it("names the address that was asked for, so a typo is visible before the wait starts", () => {
    expect(sentMessage("oj.demo+typo@cyphercrescent.com")).toContain("oj.demo+typo@cyphercrescent.com");
  });

  it("sets the expiry as its own segment, which is what puts it in mono on screen", () => {
    expect(SENT.expiry).toBe("30 minutes");
  });

  it("carries its own spacing, because the segments render as adjacent spans", () => {
    // Whitespace between two tags is collapsed away, so a segment that leans on the
    // template for its leading space renders as "inbox.If".
    expect(SENT.beforeAddress.startsWith(" ")).toBe(true);
    expect(sentMessage("new@example.com")).not.toContain("  ");
  });
});

describe("what each refusal says", () => {
  it("puts a wrong password under the password field, not over the whole form", () => {
    expect(changeEmailMessage(refusal(401, "Current password is incorrect"))).toEqual({
      field: "password",
      message: "That password doesn't match. Try again.",
    });
  });

  it("treats a 401 with no sentence as the wrong password, which is the common case", () => {
    expect(changeEmailMessage(refusal(401)).field).toBe("password");
  });

  it("tells a dead session apart from a wrong password, since both are 401", () => {
    expect(changeEmailMessage(refusal(401, "Not authenticated"))).toEqual({
      field: null,
      message: "Your session has expired. Sign in again, then retry the change.",
    });
  });

  it("names the same-address 400 as its own case", () => {
    expect(changeEmailMessage(refusal(400, "That's already the email on this account"))).toEqual({
      field: null,
      message: "That's already the email on this account.",
    });
  });

  it("flattens the 422 array into one readable line", () => {
    // FastAPI's 422 detail is a list of objects; printing it raw is how a stack trace
    // ends up on screen.
    expect(changeEmailMessage(refusal(422, [{ loc: ["body", "new_email"], msg: "value is not a valid email address" }]))).toEqual({
      field: null,
      message: "Enter a valid email address.",
    });
  });

  it("does not read the 429 body, which puts its sentence under `error` rather than `detail`", () => {
    expect(changeEmailMessage({ statusCode: 429, data: { error: "Rate limit exceeded: 5 per 1 minute" } })).toEqual({
      field: null,
      message: "Too many attempts. Wait a minute and try again.",
    });
  });

  it("says who can fix a server with no email configured", () => {
    expect(changeEmailMessage(refusal(503, "Email is not configured on the server (BREVO_API_KEY unset)"))).toEqual({
      field: null,
      message: "Email isn't set up on the server, so we can't send the confirmation. Contact an admin.",
    });
  });

  it("promises nothing was sent when it does not know what happened", () => {
    expect(changeEmailMessage(refusal(500))).toEqual({
      field: null,
      message: "Could not request the change. Nothing has been sent.",
    });
  });
});

describe("confirming the link", () => {
  it("never posts a blank token", async () => {
    const post = vi.fn();
    const clearSession = vi.fn();

    expect(await runConfirm({ post, clearSession }, "")).toBe("missing");
    expect(await runConfirm({ post, clearSession }, "   ")).toBe("missing");
    expect(post).not.toHaveBeenCalled();
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("drops the stored tokens once identity has made the swap", async () => {
    const post = vi.fn().mockResolvedValue(undefined);
    const clearSession = vi.fn();

    expect(await runConfirm({ post, clearSession }, "raw.token")).toBe("done");
    expect(post).toHaveBeenCalledWith("raw.token");
    // Every session is revoked server-side by now, so anything still held here would
    // only 401 on the next call.
    expect(clearSession).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["an expired link", refusal(400, "This confirmation link has expired, so request the change again"), "expired"],
    ["a spent or superseded link", refusal(400, "Invalid or already-used confirmation link"), "invalid"],
    ["a 400 with no sentence", refusal(400), "invalid"],
    ["an address claimed in the meantime", refusal(409, "That email address is no longer available"), "taken"],
    ["a rate limit", { statusCode: 429, data: { error: "Rate limit exceeded: 5 per 1 minute" } }, "limited"],
    ["identity being unreachable", { message: "fetch failed" }, "failed"],
  ])("reads %s", async (_label, err, expected) => {
    const clearSession = vi.fn();

    const state = await runConfirm({ post: vi.fn().mockRejectedValue(err), clearSession }, "raw.token");

    expect(state).toBe(expected);
    // Nothing moved, so the session this browser holds is still good.
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("sorts the two 400s on the word identity uses, not on their order", () => {
    expect(confirmState(400, "This confirmation link has expired, so request the change again")).toBe("expired");
    expect(confirmState(400, "Invalid or already-used confirmation link")).toBe("invalid");
  });

  it("keeps the token in the URL only where opening the link again could still work", () => {
    expect(isRetryable("limited")).toBe(true);
    expect(isRetryable("failed")).toBe(true);
    expect(["done", "expired", "invalid", "taken", "missing"].some((s) => isRetryable(s as never))).toBe(false);
  });
});

describe("the words each state shows", () => {
  it("says what is happening while the token is in flight", () => {
    expect(CONFIRM_COPY.working.message).toBe("Confirming your new email address…");
  });

  it("says the sign-out was deliberate rather than leaving it to be discovered", () => {
    expect(CONFIRM_COPY.done.message).toBe(
      "Your sign-in email has been updated. For security, we signed you out everywhere — sign in again with your new address.",
    );
  });

  it("sends an expired link back to the account page", () => {
    expect(CONFIRM_COPY.expired.message).toBe("This link has expired. Request the change again from your account page.");
  });

  it("lists every way a link goes invalid, because the server cannot say which one", () => {
    expect(CONFIRM_COPY.invalid.message).toBe(
      "This link is no longer valid. It may have already been used, replaced by a newer request, or cancelled by a password change. Request the change again.",
    );
  });

  it("says plainly that the address went to somebody else", () => {
    expect(CONFIRM_COPY.taken.message).toBe(
      "That address now belongs to another account, so we couldn't move your sign-in email.",
    );
  });

  it("tells a link with no token in it to open the email rather than retype the address", () => {
    expect(CONFIRM_COPY.missing.message).toContain("no token in it at all");
  });
});
