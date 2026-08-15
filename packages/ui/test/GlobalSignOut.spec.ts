import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useGlobalSignOut } from "../composables/useGlobalSignOut";

/* The point of this composable is the order and the reach: revoke on the server first,
   then clear the browser. Clearing first and revoking second is the bug it replaces —
   the product looks signed out while identity's session is still alive. */

const IDENTITY_API = "http://identity.test";
const IDENTITY_WEB = "http://web.identity.test";

let order: string[];
let fetchMock: ReturnType<typeof vi.fn>;
let navigate: ReturnType<typeof vi.fn>;
let accessToken: { value: string | null };
let logout: ReturnType<typeof vi.fn>;

function install(config: Record<string, unknown> = {}) {
  const g = globalThis as Record<string, unknown>;
  order = [];
  accessToken = ref<string | null>("access-abc") as { value: string | null };
  fetchMock = vi.fn(async () => {
    order.push("revoke");
    return undefined;
  });
  logout = vi.fn(() => {
    order.push("clear");
  });
  navigate = vi.fn(async (to: string) => {
    order.push(`go:${to}`);
    return undefined;
  });

  g.$fetch = fetchMock;
  g.navigateTo = navigate;
  g.useAuth = () => ({ accessToken, logout, adoptSession: vi.fn() });
  g.useRuntimeConfig = () => ({
    public: { identityUrl: IDENTITY_API, identityWebUrl: IDENTITY_WEB, ...config },
  });
}

describe("useGlobalSignOut", () => {
  beforeEach(() => install());

  it("revokes on identity before it clears anything locally", async () => {
    await useGlobalSignOut()();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe(`${IDENTITY_API}/auth/logout-all`);
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ Authorization: "Bearer access-abc" });
    expect(order).toEqual(["revoke", "clear", `go:${IDENTITY_WEB}/login`]);
  });

  it("lands the browser on identity, signed out, as a real cross-origin navigation", async () => {
    await useGlobalSignOut()();
    expect(navigate).toHaveBeenCalledWith(`${IDENTITY_WEB}/login`, { external: true });
  });

  it("clears and leaves even when the revoke call fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network"));
    await useGlobalSignOut()();
    expect(logout).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith(`${IDENTITY_WEB}/login`, { external: true });
  });

  it("skips the call when this origin holds no token, and still clears", async () => {
    accessToken.value = null;
    await useGlobalSignOut()();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(order).toEqual(["clear", `go:${IDENTITY_WEB}/login`]);
  });

  it("refuses a landing value that would leave the platform", async () => {
    await useGlobalSignOut()("//evil.example/steal");
    expect(navigate).toHaveBeenCalledWith(`${IDENTITY_WEB}/login`, { external: true });
  });

  it("accepts an in-app landing path on identity", async () => {
    await useGlobalSignOut()("/login?signed_out=1");
    expect(navigate).toHaveBeenCalledWith(`${IDENTITY_WEB}/login?signed_out=1`, { external: true });
  });

  it("stays in this app when no identity front end is configured", async () => {
    install({ identityWebUrl: "" });
    await useGlobalSignOut()();
    expect(navigate).toHaveBeenCalledWith("/login");
  });
});
