import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import InviteDialog from "~/components/InviteDialog.vue";

const DEPTS = [
  { value: "1", label: "Software Dev" },
  { value: "6", label: "Data" },
];
const ROLES = [
  { value: "admin", label: "admin" },
  { value: "manager", label: "manager" },
  { value: "engineer", label: "engineer" },
];

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(InviteDialog, {
    props: { open: true, departments: DEPTS, roles: ROLES, ...props },
    attachTo: document.body,
  });
}

function error(): HTMLElement | null {
  return document.querySelector("[role='alert']");
}

async function send(w: ReturnType<typeof mountDialog>) {
  const buttons = Array.from(document.querySelectorAll("button"));
  const submit = buttons.find((b) => b.textContent?.trim() === "Send invite")!;
  submit.click();
  await w.vm.$nextTick();
}

describe("the invite dialog", () => {
  it("refuses an empty address and says why", async () => {
    const w = mountDialog();
    await send(w);
    expect(w.emitted("submit")).toBeUndefined();
    expect(error()?.textContent).toContain("An email address is required");
    w.unmount();
  });

  it("refuses something that is not an address", async () => {
    const w = mountDialog();
    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    field.value = "ada@";
    field.dispatchEvent(new Event("input"));
    await w.vm.$nextTick();
    await send(w);
    expect(w.emitted("submit")).toBeUndefined();
    expect(error()?.textContent).toContain("does not look like an email address");
    w.unmount();
  });

  it("refuses an invite with no department — every invite endpoint is nested under one", async () => {
    const w = mountDialog();
    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    field.value = "ada.nwosu@cyphercrescent.org";
    field.dispatchEvent(new Event("input"));
    await w.vm.$nextTick();
    await send(w);
    expect(w.emitted("submit")).toBeUndefined();
    expect(error()?.textContent).toContain("Choose a department");
    w.unmount();
  });

  it("offers no way to defer the department at all", () => {
    const w = mountDialog();
    expect(document.body.textContent).not.toContain("Place them later");
    expect(document.body.textContent).toContain("Required.");
    w.unmount();
  });

  it("submits address, department and role once all three are there", async () => {
    const w = mountDialog();
    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    field.value = "  ada.nwosu@cyphercrescent.org  ";
    field.dispatchEvent(new Event("input"));
    await w.vm.$nextTick();

    const combos = Array.from(document.querySelectorAll("[role='combobox']")) as HTMLElement[];
    const deptTrigger = combos.find((c) => c.getAttribute("aria-label") === "Department")!;
    deptTrigger.click();
    await w.vm.$nextTick();
    const option = Array.from(document.querySelectorAll("[role='option']")).find(
      (o) => o.textContent?.trim() === "Data",
    ) as HTMLElement;
    option.click();
    await w.vm.$nextTick();

    await send(w);
    expect(w.emitted("submit")).toEqual([[{ email: "ada.nwosu@cyphercrescent.org", deptId: 6, role: "engineer" }]]);
    w.unmount();
  });

  it("hides the department control when the screen already knows which one", async () => {
    const w = mountDialog({ lockedDeptId: 1 });
    const combos = Array.from(document.querySelectorAll("[role='combobox']")) as HTMLElement[];
    expect(combos.map((c) => c.getAttribute("aria-label"))).toEqual(["Role"]);

    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    field.value = "femi@cyphercrescent.org";
    field.dispatchEvent(new Event("input"));
    await w.vm.$nextTick();
    await send(w);
    expect(w.emitted("submit")).toEqual([[{ email: "femi@cyphercrescent.org", deptId: 1, role: "engineer" }]]);
    w.unmount();
  });

  it("shows whatever the API said instead of swallowing it", () => {
    const w = mountDialog({ serverError: "409 · that address has already been invited here" });
    expect(error()?.textContent).toContain("already been invited");
    w.unmount();
  });

  it("wires the field to its error for a screen reader", async () => {
    const w = mountDialog();
    await send(w);
    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(field.getAttribute("aria-describedby")).toBe("invite-error");
    expect(document.getElementById("invite-error")).not.toBeNull();
    w.unmount();
  });

  it("gives the address field an autocomplete hint", () => {
    const w = mountDialog();
    const field = document.querySelector("input[type='email']") as HTMLInputElement;
    expect(field.getAttribute("autocomplete")).toBe("email");
    w.unmount();
  });
});
