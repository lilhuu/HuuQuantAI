import { ref } from "vue";
import { defineStore } from "pinia";

export const useOrderStore = defineStore("trading-orders", () => {
  const ordersSocketState = ref("idle");
  const lastOrderMessageAt = ref("");

  function connectOrdersSocket() {
    ordersSocketState.value = "idle";
  }

  function disconnectOrdersSocket() {
    ordersSocketState.value = "idle";
  }

  function resetOrderState() {
    ordersSocketState.value = "idle";
    lastOrderMessageAt.value = "";
  }

  return {
    ordersSocketState,
    lastOrderMessageAt,
    connectOrdersSocket,
    disconnectOrdersSocket,
    resetOrderState,
  };
});
