import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Toast from "../components/Toast.vue";
import { LIVE_REGION_ID } from "../composables/useAnnounce";

function node(wrapper: ReturnType<typeof mount>) {
  return wrapper.get("[data-toast]");
}

describe("Toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("slides in after mount rather than appearing already settled", async () => {
    const wrapper = mount(Toast, { props: { message: "Report submitted" } });
    expect(node(wrapper).classes()).toContain("opacity-0");

    await vi.advanceTimersByTimeAsync(0);
    expect(node(wrapper).classes()).toContain("opacity-100");
    expect(node(wrapper).classes()).toContain("translate-y-0");
  });

  it("auto-dismisses after its duration, exiting in 200ms", async () => {
    const wrapper = mount(Toast, { props: { message: "Report submitted" } });
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(3600);
    expect(node(wrapper).classes()).toContain("opacity-0");
    expect(wrapper.emitted("dismiss")).toBeUndefined();

    await vi.advanceTimersByTimeAsync(200);
    expect(wrapper.emitted("dismiss")).toHaveLength(1);
  });

  // The regression this component's shape exists to prevent: with a keyframe the second
  // toast replays nothing, because the node's identity never changed.
  it("re-animates when a second toast fires over the first", async () => {
    const wrapper = mount(Toast, { props: { message: "Report submitted" } });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(3600);
    expect(node(wrapper).classes()).toContain("opacity-0");

    await wrapper.setProps({ message: "Report approved" });
    expect(node(wrapper).text()).toContain("Report approved");
    // Retargets from where it is, back to settled.
    expect(node(wrapper).classes()).toContain("opacity-100");
    expect(node(wrapper).classes()).toContain("translate-y-0");

    // And the exit that was already in flight is cancelled, not left to fire.
    await vi.advanceTimersByTimeAsync(200);
    expect(wrapper.emitted("dismiss")).toBeUndefined();

    // The new message gets a full duration of its own.
    await vi.advanceTimersByTimeAsync(3400);
    expect(node(wrapper).classes()).toContain("opacity-0");
    await vi.advanceTimersByTimeAsync(200);
    expect(wrapper.emitted("dismiss")).toHaveLength(1);
  });

  it("announces each message through the shared live region, not through its own node", async () => {
    const region = document.createElement("div");
    region.id = LIVE_REGION_ID;
    document.body.appendChild(region);

    const wrapper = mount(Toast, { props: { message: "Report submitted" } });
    await vi.advanceTimersByTimeAsync(60);
    expect(region.textContent).toBe("Report submitted");

    await wrapper.setProps({ message: "Report approved" });
    // Cleared first, so the same message twice still reads twice.
    expect(region.textContent).toBe("");
    await vi.advanceTimersByTimeAsync(60);
    expect(region.textContent).toBe("Report approved");

    expect(node(wrapper).attributes("role")).toBeUndefined();
    expect(node(wrapper).attributes("aria-live")).toBeUndefined();
  });

  it("dismisses on the explicit button", async () => {
    const wrapper = mount(Toast, { props: { message: "Report submitted" } });
    await vi.advanceTimersByTimeAsync(0);
    await wrapper.get('button[aria-label="Dismiss"]').trigger("click");
    expect(node(wrapper).classes()).toContain("opacity-0");
    await vi.advanceTimersByTimeAsync(200);
    expect(wrapper.emitted("dismiss")).toHaveLength(1);
  });
});
