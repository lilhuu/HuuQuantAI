// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

import { useAiChatStore } from "../stores/aiChat";
import CopilotPet from "./CopilotPet.vue";

describe("CopilotPet", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  it("opens from a keyboard-accessible floating button", async () => {
    const wrapper = mount(CopilotPet, { global: { plugins: [createPinia()] } });
    const button = wrapper.get("[data-copilot-pet]");

    expect(button.attributes("aria-pressed")).toBe("false");
    expect(button.attributes("data-pet-state")).toBe("idle");
    await button.trigger("click");
    expect(wrapper.emitted("toggle")).toHaveLength(1);
    wrapper.unmount();
  });

  it("maps chat progress and unread replies to visible pet states", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useAiChatStore();
    const wrapper = mount(CopilotPet, { global: { plugins: [pinia] } });

    store.streaming = true;
    await wrapper.vm.$nextTick();
    expect(wrapper.get("[data-copilot-pet]").attributes("data-pet-state")).toBe("thinking");

    store.firstTokenReceived = true;
    await wrapper.vm.$nextTick();
    expect(wrapper.get("[data-copilot-pet]").attributes("data-pet-state")).toBe("speaking");

    store.streaming = false;
    store.unreadCount = 1;
    await wrapper.vm.$nextTick();
    expect(wrapper.get("[data-copilot-pet]").attributes("data-pet-state")).toBe("attention");
    expect(wrapper.get(".copilot-pet__badge").text()).toBe("1");
    wrapper.unmount();
  });
});
