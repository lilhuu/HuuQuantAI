import { expect, test } from "@playwright/test";

import {
  installApiMocks,
  installStreamingChatMock,
  seedAuthenticatedSession,
  waitForMockApiIdle,
} from "./support/mockApi";

async function openAuthenticatedWorkbench(page, path = "/") {
  await seedAuthenticatedSession(page);
  const api = await installApiMocks(page, { authenticated: true });
  await page.goto(path);
  await expect(page.locator(".cq-shell")).toBeVisible();
  return api;
}

test("local login enters the protected workbench", async ({ page }) => {
  const api = await installApiMocks(page, { authenticated: false });

  await page.goto("/");
  await expect(page).toHaveURL(/\/auth(?:\?.*)?$/);
  await page.getByLabel("用户名").fill("owner");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "登录工作台" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "仪表盘" })).toBeVisible();
  expect(api.loginPayload).toEqual({ username: "owner", password: "password123" });
  await waitForMockApiIdle(page, api);
  expect(api.unexpectedRequests).toEqual([]);
});

test("sidebar route changes render distinct functional modules", async ({ page }) => {
  const api = await openAuthenticatedWorkbench(page);

  await page.getByRole("link", { name: "市场行情" }).click();
  await expect(page).toHaveURL(/\/market$/);
  await expect(page.locator('[data-feature-role="market-intelligence"]')).toBeVisible();

  await page.getByRole("link", { name: "回测中心" }).click();
  await expect(page).toHaveURL(/\/backtest$/);
  await expect(page.locator('[data-feature-role="backtest-center"]')).toBeVisible();

  await page.getByRole("link", { name: "账户状态" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.locator('[data-feature-role="paper-account"]')).toBeVisible();
  await waitForMockApiIdle(page, api);
  expect(api.unexpectedRequests).toEqual([]);
});

test("pet chat renders a streamed assistant response", async ({ page }) => {
  await seedAuthenticatedSession(page);
  await installStreamingChatMock(page);
  const api = await installApiMocks(page, { authenticated: true });
  await page.goto("/");

  await page.locator("[data-copilot-pet]").click();
  const panel = page.locator("[data-copilot-panel]");
  await expect(panel).toBeVisible();
  await panel.locator('[data-ai-drawer-input="message"]').fill("检查当前行情");
  const sendButton = panel.locator('[data-ai-drawer-send="message"]');
  await sendButton.click();

  await expect(sendButton).toHaveText("回答中");
  const assistantText = panel.locator(".ai-chat-message--assistant p").last();
  await expect.poll(() => page.evaluate(() => window.__e2eReleaseStreamChunk())).toBe(true);
  await expect(assistantText).toHaveText("实时");
  expect(await page.evaluate(() => window.__e2eReleaseStreamChunk())).toBe(true);
  await expect(assistantText).toHaveText("实时行情正常");
  expect(await page.evaluate(() => window.__e2eReleaseStreamChunk())).toBe(true);
  await expect(sendButton).toHaveText("发送");
  await expect(panel.locator(".ai-chat-message--user").last()).toContainText("检查当前行情");
  const requests = await page.evaluate(() => window.__e2eStreamRequests);
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    method: "POST",
    accept: "text/event-stream",
    authorization: "Bearer e2e-token",
    payload: { message: "检查当前行情", include_context: true },
  });
  await waitForMockApiIdle(page, api);
  expect(api.unexpectedRequests).toEqual([]);
});

test("AI supervised paper trading cannot start before explicit confirmation", async ({ page }) => {
  const api = await openAuthenticatedWorkbench(page, "/auto");
  const startButton = page.getByRole("button", { name: "启动", exact: true });

  await expect(page.locator('[data-feature-role="auto-decision-pipeline"]')).toBeVisible();
  await expect(startButton).toBeDisabled();
  expect(api.autoStartCount).toBe(0);

  await page.locator("[data-ai-supervisor-ack]").check();
  await expect(startButton).toBeEnabled();
  await startButton.click();

  await expect.poll(() => api.autoStartCount).toBe(1);
  expect(api.autoConfigPayload).toMatchObject({
    decision_mode: "ai_supervised",
    mode: "paper",
    real_trading_enabled: false,
  });
  await waitForMockApiIdle(page, api);
  expect(api.unexpectedRequests).toEqual([]);
});

test("mobile workbench and pet panel stay inside the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await openAuthenticatedWorkbench(page, "/market");

  await expect(page.getByRole("heading", { name: "Binance Spot 全市场行情", exact: true })).toBeVisible();
  const initialLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  expect(Math.max(initialLayout.documentWidth, initialLayout.bodyWidth)).toBeLessThanOrEqual(initialLayout.viewport + 1);

  await page.locator("[data-copilot-pet]").click();
  const panel = page.locator("[data-copilot-panel]");
  await expect(panel.locator('[data-ai-drawer-input="message"]')).toBeVisible();
  const box = await panel.boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(391);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(845);

  await page.getByRole("button", { name: "关闭 AI 助手" }).click();
  await page.getByRole("link", { name: "自动交易" }).click();
  await expect(page).toHaveURL(/\/auto$/);
  await expect(page.locator('[data-feature-role="auto-decision-pipeline"]')).toBeVisible();
  await waitForMockApiIdle(page, api);
  expect(api.unexpectedRequests).toEqual([]);
});
