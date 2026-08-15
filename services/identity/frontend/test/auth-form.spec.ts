import { describe, expect, it } from "vitest";
import { afterSignInPath, destinationLabel, emailError, nameError, signInMessage, signInPasswordError, signInPath, signUpMessage } from "~/utils/auth-form";

describe("sign-in validation", () => {
  it("asks for an address before it complains about the shape of one", () => {
    expect(emailError("")).toBe("Enter your work email.");
  });

  it.each(["nope", "no@dots", "@cyphercrescent.com", "two @spaces.com"])("rejects %s", (value) => {
    expect(emailError(value)).toBe("That is not a valid email address.");
  });

  it("accepts a work address", () => {
    expect(emailError("oj.adeoluwa@cyphercrescent.com")).toBeNull();
  });

  it("holds sign-in to the length only, because the server decides the rest", () => {
    expect(signInPasswordError("short")).toBe("Password must be at least 8 characters.");
    expect(signInPasswordError("longenough")).toBeNull();
  });

  it("requires both names when creating an account", () => {
    expect(nameError("  ", "first name")).toBe("A first name is required.");
    expect(nameError("Ada", "first name")).toBeNull();
  });
});

describe("forwarding to the requested route", () => {
  it("carries the intended path into the sign-in URL", () => {
    expect(signInPath("/account")).toBe("/login?next=%2Faccount");
  });

  it("keeps the query string of the route that was refused", () => {
    expect(signInPath("/departments/4?tab=roster")).toBe("/login?next=%2Fdepartments%2F4%3Ftab%3Droster");
  });

  it("does not bother carrying the home page or the sign-in screen itself", () => {
    expect(signInPath("/")).toBe("/login");
    expect(signInPath("/login?next=%2Faccount")).toBe("/login");
  });

  it("returns to the requested route after signing in", () => {
    expect(afterSignInPath("/departments/4?tab=roster")).toBe("/departments/4?tab=roster");
  });

  it("falls back to the picker when there is no request", () => {
    expect(afterSignInPath(undefined)).toBe("/products");
    expect(afterSignInPath("")).toBe("/products");
  });

  it.each([
    ["an absolute URL", "https://evil.example/steal"],
    ["a protocol-relative URL", "//evil.example"],
    ["a backslash trick", "/\\evil.example"],
    ["the sign-in screen itself, which would loop", "/login"],
    ["a non-string", 42],
  ])("refuses to forward to %s", (_label, value) => {
    expect(afterSignInPath(value)).toBe("/products");
  });

  it("names the destination in words on the sign-in screen", () => {
    expect(destinationLabel("/account")).toBe("your account");
    expect(destinationLabel("/departments/7")).toBe("Identity · Organisation");
    expect(destinationLabel("/nowhere")).toBe("where you were headed");
  });
});

describe("what the screen says when identity refuses", () => {
  it("gives one message for a wrong address and a wrong password", () => {
    expect(signInMessage({ statusCode: 401, data: { detail: "Invalid credentials" } })).toBe(
      "That email and password do not match an account.",
    );
  });

  it("explains a deactivated account rather than blaming the password", () => {
    expect(signInMessage({ statusCode: 403 })).toContain("deactivated");
  });

  it("names the rate limit", () => {
    expect(signInMessage({ statusCode: 429 })).toContain("Too many attempts");
    expect(signUpMessage({ statusCode: 429 })).toContain("Too many attempts");
  });

  it("says the address is taken on a 409", () => {
    expect(signUpMessage({ statusCode: 409 })).toContain("already an account");
  });

  it("passes the server's own password complaint through on a 400", () => {
    expect(signUpMessage({ statusCode: 400, data: { detail: "Password must contain a symbol" } })).toBe(
      "Password must contain a symbol",
    );
  });
});
