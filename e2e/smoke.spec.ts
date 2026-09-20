import { expect, test } from "@playwright/test";

// Front-door smoke: console renders, tabs navigate, theme toggles.
// API calls may fail locally (no backend) — the console must still render its shell.
test("admin console renders shell and navigates", async ({ page }) => {
  await page.goto("/");
  // New UI gates on a login card until a token is entered (backend may accept any).
  const tokenInput = page.locator('input[type="password"]');
  if (await tokenInput.count()) {
    await tokenInput.fill("e2e-token");
    await page.getByRole("button", { name: /进入|Enter/i }).click();
  }
  await expect(page.getByRole("heading", { name: /雅迪 EKB 管理台|EKB Admin/ })).toBeVisible();
  for (const tab of ["运行健康", "容量估算", "Skill 治理", "审计查询"]) {
    await page.getByRole("button", { name: tab }).click();
  }
  await page.getByRole("button", { name: /切换主题|Toggle theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("health endpoint of control plane responds", async ({ request }) => {
  const base = process.env.EKB_API_URL ?? "http://127.0.0.1:8080";
  const resp = await request.get(`${base}/healthz`);
  expect(resp.ok()).toBeTruthy();
  expect((await resp.json()).status).toBe("ok");
});
