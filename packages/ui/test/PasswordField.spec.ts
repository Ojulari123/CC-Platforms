import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { h } from "vue";
import PasswordField from "../components/PasswordField.vue";

/* The reveal control. The test that matters most is the boring one: a bare <button>
   inside a form submits it, so "clicking the eye does not send the form" is asserted with
   a real submit button next to it as the control. */

function mountField(props: Record<string, unknown> = {}) {
  return mount(PasswordField, {
    props: { modelValue: "", id: "pw", name: "password", ...props },
  });
}

describe("PasswordField", () => {
  it("starts hidden and flips type and aria-pressed together", async () => {
    const wrapper = mountField();
    const input = () => wrapper.get("input");
    const toggle = wrapper.get("button");

    expect(input().attributes("type")).toBe("password");
    expect(toggle.attributes("aria-pressed")).toBe("false");

    await toggle.trigger("click");
    expect(input().attributes("type")).toBe("text");
    expect(toggle.attributes("aria-pressed")).toBe("true");

    await toggle.trigger("click");
    expect(input().attributes("type")).toBe("password");
    expect(toggle.attributes("aria-pressed")).toBe("false");
  });

  it("names what it will do, not what it is showing", async () => {
    const wrapper = mountField();
    const toggle = wrapper.get("button");

    expect(toggle.attributes("aria-label")).toBe("Show password");
    await toggle.trigger("click");
    expect(toggle.attributes("aria-label")).toBe("Hide password");
  });

  it("is a type=button and does not submit the form it sits in", async () => {
    const onSubmit = vi.fn();
    const Form = {
      render() {
        return h("form", { onSubmit }, [
          h(PasswordField, { modelValue: "", id: "pw", name: "password" }),
          h("button", null, "Sign in"),
        ]);
      },
    };
    const wrapper = mount(Form);
    const [toggle, submitButton] = wrapper.findAll("button");

    /* `type` is what a browser reads to decide whether a click submits, and an unset one
       defaults to "submit" — which is what the control below shows: the sibling button
       carries no type attribute of its own and still reports "submit". */
    expect(toggle!.attributes("type")).toBe("button");
    expect((toggle!.element as HTMLButtonElement).type).toBe("button");
    expect((submitButton!.element as HTMLButtonElement).type).toBe("submit");

    await toggle!.trigger("click");
    expect(onSubmit).not.toHaveBeenCalled();

    // happy-dom does not run implicit form submission, so the listener is proved live by
    // dispatching the event the browser would have raised.
    await wrapper.get("form").trigger("submit");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not remember being open across a mount", async () => {
    const first = mountField();
    await first.get("button").trigger("click");
    expect(first.get("input").attributes("type")).toBe("text");

    expect(mountField().get("input").attributes("type")).toBe("password");
  });

  it("stays a real input a password manager can fill", () => {
    const wrapper = mountField({ autocomplete: "new-password", name: "new-password" });
    const input = wrapper.get("input");

    expect(input.attributes("id")).toBe("pw");
    expect(input.attributes("name")).toBe("new-password");
    expect(input.attributes("autocomplete")).toBe("new-password");
    expect(input.attributes("spellcheck")).toBe("false");
  });

  it("points the toggle at the input it controls, and the label at it too", () => {
    const wrapper = mountField({ label: "New password" });
    expect(wrapper.get("button").attributes("aria-controls")).toBe("pw");
    expect(wrapper.get("label").attributes("for")).toBe("pw");
    expect(wrapper.get("label").text()).toBe("New password");
  });

  it("is keyboard reachable with a visible focus ring and a tap target", () => {
    const toggle = mountField().get("button");
    expect(toggle.attributes("tabindex")).toBeUndefined();
    expect(toggle.classes()).toContain("focus-visible:outline-2");
    expect(toggle.classes()).toContain("focus-visible:outline-[color:var(--accent-ink)]");
    expect(toggle.classes()).toContain("tap");
  });

  it("carries the field's error and busy state without owning either", () => {
    const wrapper = mountField({ invalid: true, describedby: "pw-err pw-rules", busy: true });
    const input = wrapper.get("input");

    expect(input.attributes("aria-invalid")).toBe("true");
    expect(input.attributes("aria-describedby")).toBe("pw-err pw-rules");
    expect(input.attributes("aria-busy")).toBe("true");
    expect(input.classes()).toContain("ring-bad");
  });

  it("leaves aria-invalid off a field that is not in error", () => {
    const input = mountField().get("input");
    expect(input.attributes("aria-invalid")).toBeUndefined();
    expect(input.classes()).toContain("ring-line");
  });

  it("disables both halves together", () => {
    const wrapper = mountField({ disabled: true });
    expect(wrapper.get("input").attributes("disabled")).toBeDefined();
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
  });

  it("emits what a v-model and a blur handler need", async () => {
    const wrapper = mountField();
    await wrapper.get("input").setValue("Meridian!2026");
    expect(wrapper.emitted("update:modelValue")).toEqual([["Meridian!2026"]]);

    await wrapper.get("input").trigger("blur");
    expect(wrapper.emitted("blur")).toHaveLength(1);
  });
});
