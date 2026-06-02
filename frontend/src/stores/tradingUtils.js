export const PORTFOLIO_REFRESH_DELAY_MS = 180;

/**
 * @typedef {Object} CryptoOrderLike
 * @property {string=} order_id
 * @property {string=} created_time
 * @property {string=} filled_time
 * @property {string=} status
 */

/**
 * @param {CryptoOrderLike | null | undefined} order
 * @returns {string}
 */
export function orderTime(order) {
  return order?.created_time || order?.filled_time || "";
}

/**
 * Normalize common crypto symbol inputs into BASE/QUOTE form.
 *
 * @param {string | number | null | undefined} value
 * @param {string} [quoteCurrency]
 * @returns {string}
 */
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

/**
 * @param {string | number | null | undefined} value
 * @returns {string}
 */
export function formatCryptoSymbol(value) {
  return normalizeCryptoSymbol(value) || "-";
}

/**
 * @param {CryptoOrderLike[]} items
 * @returns {CryptoOrderLike[]}
 */
export function sortOrders(items) {
  return [...items].sort((left, right) => orderTime(right).localeCompare(orderTime(left)));
}

/**
 * @param {string} state
 * @returns {"connected" | "connecting" | "error" | "idle"}
 */
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

/**
 * @param {unknown} value
 * @returns {number}
 */
function toFiniteNumber(value) {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

const priceFormatter = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 8,
});

/**
 * @param {unknown} value
 * @returns {string}
 */
export function formatCurrency(value) {
  return formatUsdt(value);
}

/**
 * @param {unknown} value
 * @returns {string}
 */
export function formatUsdt(value) {
  const number = toFiniteNumber(value);
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number).replace("US$", "USDT ");
}

/**
 * @param {unknown} value
 * @returns {string}
 */
export function formatPrice(value) {
  return priceFormatter.format(toFiniteNumber(value));
}

/**
 * @param {unknown} value
 * @returns {string}
 */
export function formatPercent(value) {
  return `${formatPrice(value)}%`;
}

/**
 * @param {string | null | undefined} status
 * @returns {"badge-live" | "badge-warn" | "badge-danger" | "badge-muted"}
 */
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

/**
 * @param {string | null | undefined} eventType
 * @param {string | null | undefined} [status]
 * @returns {"success" | "error" | "warn" | "info"}
 */
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

/**
 * @param {string | null | undefined} eventType
 * @param {string | null | undefined} [status]
 * @returns {"badge-live" | "badge-warn" | "badge-danger" | "badge-muted"}
 */
export function badgeClassForEvent(eventType, status) {
  return badgeClassForOrder(eventType || status);
}
