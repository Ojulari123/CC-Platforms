import { config } from "@vue/test-utils";
import { afterEach, vi } from "vitest";

// NuxtLink only exists inside a Nuxt app. Stub it as a real anchor so link markup and
// keyboard reachability stay testable.
config.global.stubs = {
  NuxtLink: {
    props: { to: { type: [String, Object], default: "" } },
    template: '<a :href="typeof to === \'string\' ? to : \'#\'"><slot /></a>',
  },
};

// happy-dom has no rAF-driven layout, and several shared components use rAF to let a
// mounted node settle before its enter transition. Run it on the next macrotask instead.
if (typeof globalThis.requestAnimationFrame !== "function") {
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) =>
    setTimeout(() => cb(Date.now()), 0) as unknown as number) as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = ((id: number) => clearTimeout(id)) as typeof cancelAnimationFrame;
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = vi.fn();
}

afterEach(() => {
  document.body.innerHTML = "";
  document.body.style.removeProperty("overflow");
  sessionStorage.clear();
  localStorage.clear();
});
