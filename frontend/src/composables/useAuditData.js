import { computed } from "vue";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { badgeClassForOrder, eventToneFromType } from "../lib/tradingUtils";

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function useAuditData() {
  const autoStore = useAutoTradingStore();
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();

  const safetyItems = computed(() => [
    { label: "真实交易", value: "永久关闭", tone: "status-chip--idle" },
    { label: "做空", value: "禁止", tone: "status-chip--idle" },
    { label: "杠杆", value: "禁止", tone: "status-chip--idle" },
    {
      label: "自动交易",
      value: autoStore.enabled ? "运行中" : "未启动",
      tone: autoStore.enabled ? "status-chip--connected" : "status-chip--idle",
    },
    {
      label: "行情连接",
      value: marketStore.marketSocketState === "connected" ? "已连接" : "未连接",
      tone: marketStore.marketSocketState === "connected" ? "status-chip--connected" : "status-chip--idle",
    },
  ]);

  const orderLifecycle = computed(() =>
    systemStore.cryptoOrders.slice(0, 30).map((order) => ({
      id: order.order_id || `${order.symbol}-${order.created_time || order.filled_time || ""}`,
      timestamp: formatTime(order.created_time || order.filled_time),
      symbol: order.symbol || "-",
      action: order.action || "-",
      quantity: order.quantity ?? "-",
      status: order.status || "-",
      source: order.strategy || order.source || "manual",
      tone: badgeClassForOrder(order.status),
    })),
  );

  const blockedDecisions = computed(() =>
    (autoStore.decisions || [])
      .filter((item) => String(item.status || "").toLowerCase() === "blocked")
      .slice(-30)
      .reverse(),
  );

  const auditLogs = computed(() =>
    (systemStore.cryptoLogs || []).slice(0, 40).map((log, index) => ({
      id: `${log.timestamp || index}-${log.event || log.message || index}`,
      event: log.event || "paper_event",
      message: log.message || "-",
      timestamp: formatTime(log.timestamp),
      tone: eventToneFromType(log.event, log.status),
    })),
  );

  const rejectedLogs = computed(() =>
    auditLogs.value.filter((log) => `${log.event} ${log.message}`.toLowerCase().includes("reject")),
  );

  async function refreshAudit() {
    await Promise.allSettled([autoStore.fetchStatus(), systemStore.refreshOverview()]);
  }

  return {
    safetyItems,
    orderLifecycle,
    blockedDecisions,
    auditLogs,
    rejectedLogs,
    refreshAudit,
  };
}
