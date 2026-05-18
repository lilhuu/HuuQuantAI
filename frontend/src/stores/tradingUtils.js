export const PORTFOLIO_REFRESH_DELAY_MS = 180;

export function orderTime(order) {
  return order?.created_time || order?.filled_time || "";
}

export function normalizeCryptoSymbol(value, quoteCurrency = "USDT") {
  const raw = String(value || "").trim().toUpperCase().replace(/[-_]/g, "/");
  if (!raw) {
    return "";
  }
  if (raw.includes("/")) {
    const [base, quote] = raw.split("/");
    return base && quote ? `${base}/${quote}` : "";
  }
  const quote = String(quoteCurrency || "USDT").toUpperCase();
  return raw.endsWith(quote) && raw.length > quote.length
    ? `${raw.slice(0, -quote.length)}/${quote}`
    : `${raw}/${quote}`;
}

export function formatCryptoSymbol(value) {
  return normalizeCryptoSymbol(value) || "-";
}

export function sortOrders(items) {
  return [...items].sort((left, right) => orderTime(right).localeCompare(orderTime(left)));
}

export function toneFromSocketState(state) {
  switch (state) {
    case "connected":
      return "connected";
    case "reconnecting":
    case "connecting":
      return "connecting";
    case "error":
      return "error";
    default:
      return "idle";
  }
}

function toFiniteNumber(value) {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

const priceFormatter = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 8,
});

export function formatCurrency(value) {
  return formatUsdt(value);
}

export function formatUsdt(value) {
  const number = toFiniteNumber(value);
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number).replace("US$", "USDT ");
}

export function formatPrice(value) {
  return priceFormatter.format(toFiniteNumber(value));
}

export function formatPercent(value) {
  return `${formatPrice(value)}%`;
}

export function badgeClassForOrder(status) {
  switch (String(status || "").toLowerCase()) {
    case "filled":
      return "badge-live";
    case "partial_filled":
      return "badge-warn";
    case "rejected":
      return "badge-danger";
    case "cancelled":
      return "badge-warn";
    default:
      return "badge-muted";
  }
}

export function eventToneFromType(eventType, status) {
  const normalizedType = String(eventType || status || "").toLowerCase();
  if (normalizedType.includes("fill")) {
    return "success";
  }
  if (normalizedType.includes("reject")) {
    return "error";
  }
  if (normalizedType.includes("cancel")) {
    return "warn";
  }
  return "info";
}

export function badgeClassForEvent(eventType, status) {
  return badgeClassForOrder(eventType || status);
}
