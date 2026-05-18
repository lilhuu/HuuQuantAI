import axios from "axios";

import { clearStoredSession, getStoredToken } from "./auth";

const baseURL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export const apiClient = axios.create({
  baseURL,
  timeout: 10000,
});

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearStoredSession();
    }
    return Promise.reject(error);
  },
);

export function extractApiError(error) {
  return classifyApiError(error).message;
}

export function classifyApiError(error) {
  const status = error?.response?.status;
  const data = error?.response?.data || {};
  const detail = data.detail;
  const message = data.message;
  const errorCode = data.error_code || data.business_code || "";
  const base = {
    status: status || null,
    errorCode: errorCode || null,
  };

  if (status === 401 || errorCode.startsWith("auth.")) {
    return {
      ...base,
      type: "auth",
      title: "登录已失效",
      message: detail || message || "登录状态已过期，请重新登录。",
    };
  }

  if (status === 403) {
    return {
      ...base,
      type: "auth",
      title: "权限不足",
      message: detail || message || "当前账号没有执行该操作的权限。",
    };
  }

  if (errorCode === "request.validation_failed") {
    return {
      ...base,
      type: "validation",
      title: "参数校验失败",
      message: message || "请检查输入内容后再提交。",
      errors: data.errors || [],
    };
  }

  if (errorCode.startsWith("risk.")) {
    return {
      ...base,
      type: "risk",
      title: "风控拒绝",
      message: message || "该操作未通过风控校验。",
    };
  }

  if (errorCode.startsWith("order.")) {
    return {
      ...base,
      type: "order",
      title: "订单操作失败",
      message: message || "订单当前状态无法完成该操作。",
    };
  }

  if (errorCode.startsWith("strategy.")) {
    return {
      ...base,
      type: "strategy",
      title: "策略配置失败",
      message: message || "策略参数或状态不满足要求。",
    };
  }

  if (status >= 400 && status < 500) {
    return {
      ...base,
      type: "business",
      title: "操作未完成",
      message: detail || message || "请求参数或业务状态不满足要求。",
    };
  }

  if (status >= 500) {
    return {
      ...base,
      type: "server",
      title: "服务异常",
      message: detail || message || "交易后台暂时无法完成请求，请稍后重试。",
    };
  }

  if (error?.code === "ECONNABORTED") {
    return {
      type: "network",
      title: "请求超时",
      message: "后台响应超时，请检查交易内核是否正常运行。",
      status: null,
      errorCode: null,
    };
  }

  if (!error?.response) {
    return {
      type: "network",
      title: "网络连接失败",
      message: error?.message || "无法连接到本地交易后台，请确认应用服务已启动。",
      status: null,
      errorCode: null,
    };
  }

  if (error?.response?.data?.detail) {
    return {
      ...base,
      type: "unknown",
      title: "请求失败",
      message: error.response.data.detail,
    };
  }
  if (error?.response?.data?.message) {
    return {
      ...base,
      type: "unknown",
      title: "请求失败",
      message: error.response.data.message,
    };
  }
  return {
    ...base,
    type: "unknown",
    title: "请求失败",
    message: error?.message || "请求失败",
  };
}
