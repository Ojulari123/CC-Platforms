import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import ProductShell from "../components/ProductShell.vue";
import TopBar from "../components/TopBar.vue";

// The shell reads the open route to mark its sub-nav. There is no router mounted here,
// and an injected route that does not exist warns on every mount.
vi.mock("vue-router", () => ({ useRoute: () => ({ path: "/" }) }));

/* The two controls that decide whether a product is a room or a dead end: the way back to
   the picker, and the way out of the session. Both are optional, and a control whose
   destination was never supplied must not be rendered as a dead one. */

const PICKER = "http://localhost:3002/products";

function shell(props: Record<string, unknown> = {}) {
  // `current` is passed so the shell never reaches for a router that is not mounted here.
  return mount(ProductShell, { props: { product: "pulse", current: "/", ...props } });
}

function allProductsLink(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll("a").find((a) => a.attributes("aria-label") === "All products");
}

describe("TopBar cross-product link", () => {
  it("renders All products as a real link to the address it was given", () => {
    const wrapper = mount(TopBar, { props: { signedIn: true, allProductsTo: PICKER } });
    const link = allProductsLink(wrapper);
    expect(link).toBeDefined();
    expect(link!.attributes("href")).toBe(PICKER);
    expect(link!.text()).toContain("All products");
  });

  it("omits it entirely when no destination is supplied", () => {
    const wrapper = mount(TopBar, { props: { signedIn: true } });
    expect(allProductsLink(wrapper)).toBeUndefined();
    expect(wrapper.text()).not.toContain("All products");
  });

  it("keeps the link on narrow screens, folding only its label away", () => {
    const wrapper = mount(TopBar, { props: { signedIn: true, allProductsTo: PICKER } });
    const link = allProductsLink(wrapper)!;
    expect(link.classes()).toContain("inline-flex");
    expect(link.classes()).not.toContain("hidden");
    expect(link.find("span").classes()).toContain("hidden");
  });

  it("offers nothing cross-product to a signed-out visitor", () => {
    const wrapper = mount(TopBar, { props: { signedIn: false, allProductsTo: PICKER } });
    expect(allProductsLink(wrapper)).toBeUndefined();
  });

  // By text, not by position: the bar also carries the theme radiogroup's buttons.
  it("hides the sign-out button unless it is asked for", () => {
    const signOut = (wrapper: ReturnType<typeof mount>) =>
      wrapper.findAll("button").find((b) => b.text() === "Sign out");
    expect(signOut(mount(TopBar, { props: { signedIn: true } }))).toBeUndefined();
    expect(signOut(mount(TopBar, { props: { signedIn: true, showSignOut: true } }))).toBeDefined();
  });
});

describe("ProductShell", () => {
  it("forwards the picker address to the bar", () => {
    const wrapper = shell({ allProductsTo: PICKER });
    expect(allProductsLink(wrapper)!.attributes("href")).toBe(PICKER);
  });

  it("leaves the product without a way back when no address is configured", () => {
    expect(allProductsLink(shell())).toBeUndefined();
  });

  it("carries sign out by default and emits it", async () => {
    const wrapper = shell();
    const button = wrapper.findAll("button").find((b) => b.text() === "Sign out");
    expect(button).toBeDefined();
    await button!.trigger("click");
    expect(wrapper.emitted("signOut")).toHaveLength(1);
  });

  it("drops sign out on the one flag, for products that leave it to the picker", () => {
    const wrapper = shell({ showSignOut: false });
    expect(wrapper.findAll("button").some((b) => b.text() === "Sign out")).toBe(false);
  });
});

/* Pulse's six entries measure 485px and a phone gives 390. The strip scrolls rather than
   wrapping or clipping, and it keeps its own gutter when it does — an entry flush against
   the viewport edge has nowhere to draw the focus ring the FOCUS token puts outside it. */
describe("ProductShell sub-nav", () => {
  function nav(wrapper: ReturnType<typeof mount>) {
    return wrapper.get("nav[aria-label='Pulse sections']");
  }

  it("scrolls sideways instead of clipping an entry out of reach", () => {
    const classes = nav(shell()).classes();
    expect(classes).toContain("overflow-x-auto");
    expect(classes).not.toContain("flex-wrap");
  });

  it("keeps the content gutter as scroll padding, so nothing lands flush against the edge", () => {
    const classes = nav(shell()).classes();
    expect(classes).toContain("scroll-px-5");
    expect(classes).toContain("sm:scroll-px-8");
  });

  it("does not hand a sideways swipe to the browser's back gesture", () => {
    expect(nav(shell()).classes()).toContain("overscroll-x-contain");
  });

  it("keeps every section a real link, with aria-current on the open one", () => {
    const links = nav(shell({ current: "/sync" })).findAll("a");
    expect(links.map((a) => a.text())).toEqual(["Overview", "Activity", "Reports", "Repositories", "Journal", "Assistant", "Sync", "Settings"]);
    expect(links.filter((a) => a.attributes("aria-current") === "page").map((a) => a.text())).toEqual(["Sync"]);
  });

  it("brings a focused entry into view without moving anything outside the strip", async () => {
    const wrapper = shell({ current: "/sync" });
    const strip = nav(wrapper).element as HTMLElement;
    // 416px of entries in a 390px strip, with Sync's right edge 6px past it.
    Object.defineProperty(strip, "scrollWidth", { value: 416, configurable: true });
    Object.defineProperty(strip, "clientWidth", { value: 390, configurable: true });
    strip.getBoundingClientRect = () => ({ left: 0, right: 390 }) as DOMRect;
    // No stylesheet here, so what scroll-px-5 resolves to has to be stood up by hand.
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((el: Element, pseudo?: string | null) =>
      el === strip ? ({ scrollPaddingLeft: "20px" } as CSSStyleDeclaration) : real(el, pseudo),
    );
    const sync = nav(wrapper).findAll("a").at(-1)!;
    (sync.element as HTMLElement).getBoundingClientRect = () => ({ left: 345, right: 396 }) as DOMRect;

    await sync.trigger("focusin");

    // 396 - (390 - 20) = 26: far enough that the gutter is back under it.
    expect(strip.scrollLeft).toBe(26);
  });

  it("leaves the strip alone when every entry already fits", async () => {
    const wrapper = shell();
    const strip = nav(wrapper).element as HTMLElement;
    Object.defineProperty(strip, "scrollWidth", { value: 800, configurable: true });
    Object.defineProperty(strip, "clientWidth", { value: 1200, configurable: true });
    await nav(wrapper).findAll("a").at(-1)!.trigger("focusin");
    expect(strip.scrollLeft).toBe(0);
  });
});

// The one part of the ruler a screen sets is a figure — `12 accounts`, `report 42`,
// `next run 9h 55m`. ink-faint is for chrome; a value belongs a step darker.
describe("RulerStrip readout", () => {
  it("renders the readout as data rather than as chrome", () => {
    const readout = shell({ readout: "12 accounts" })
      .findAll("span")
      .find((s) => s.text() === "12 accounts")!;
    expect(readout.classes()).toContain("text-ink-muted");
    expect(readout.classes()).not.toContain("text-ink-faint");
  });
});
