import { test, expect, type Page } from "@playwright/test";

const mods = Array.from({ length: 60 }, (_, i) => ({
  install_order: i + 1, file_id: String(i + 100), slug: "sample-mod",
  name: i === 0 ? "Community Patch" : `Graphics mod ${i}`,
  url: "https://example.test/mod.zip", game: "KOTOR1", section: "", category: "Graphics",
  note: "Install the TPC version.", instructions: "Install the TPC version.",
  option_hint: "", install_method_hint: "loose", build_key: "k1_full",
  source_host: "deadlystream", auto_downloadable: true,
}));

async function mockBackend(page: Page) {
  let settings = { language: "en", download_dir: "C:\\Downloads", nexus_api_key: "" };
  await page.route("http://127.0.0.1:8756/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings") {
      if (route.request().method() === "POST") {
        settings = route.request().postDataJSON();
        await route.fulfill({ json: { ok: true } });
      } else {
        await route.fulfill({ json: settings });
      }
      return;
    }
    const responses: Record<string, unknown> = {
      "/api/status": { version: "0.16.18", logged_in: true, pipeline_running: false },
      "/api/settings": { language: "en", download_dir: "C:\\Downloads", nexus_api_key: "" },
      "/api/builds": { builds: [{ key: "k1_full", label: "KOTOR 1 - Full Build", game: "KOTOR1" }] },
      "/api/credentials": { username: "Test player" },
      "/api/profiles": { profiles: [{ id: "KOTOR1", name: "KOTOR 1", game: "KOTOR1" }], active: "KOTOR1" },
      "/api/library": { mods: [] }, "/api/conflicts": { conflicts: [] },
      "/api/cache": { count: 0, entries: [], total_bytes: 0, in_use_bytes: 0 },
      "/api/mod/info": { description: "Community mod.", images: [] },
      "/api/source-site": { url: "https://kotor.neocities.org", username: "", has_password: false },
    };
    await route.fulfill({ json: path.endsWith("/load") ? { ok: true, mods } : responses[path] ?? {} });
  });
}

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await expect(page.getByRole("checkbox", { name: "Community Patch", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Install 60 mods", exact: true })).toBeVisible();
});

test("navigation preserves build search and selection", async ({ page }) => {
  await page.getByRole("checkbox", { name: "Community Patch", exact: true }).click();
  await page.getByRole("textbox", { name: "Search mods…" }).fill("Community");
  await page.getByRole("button", { name: "Installed mods", exact: true }).click();
  await page.getByRole("button", { name: "Builds", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Search mods…" })).toHaveValue("Community");
  await expect(page.getByRole("checkbox", { name: "Community Patch", exact: true })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Install 59 mods", exact: true })).toBeVisible();
});

test("Space toggles a checkbox without opening mod details", async ({ page }) => {
  const checkbox = page.getByRole("checkbox", { name: "Community Patch", exact: true });
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).not.toBeChecked();
  await expect(page.getByRole("button", { name: "Close", exact: true })).toHaveCount(0);
});

test("navigation preserves mod-list scroll position", async ({ page }) => {
  const list = page.locator("div.overflow-auto").filter({ has: page.getByRole("checkbox", { name: "Community Patch", exact: true }) });
  await list.evaluate(el => { el.scrollTop = 500; });
  const before = await list.evaluate(el => el.scrollTop);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Builds", exact: true }).click();
  expect(await list.evaluate(el => el.scrollTop)).toBe(before);
});

test("settings tabs preserve unsaved changes", async ({ page }) => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("textbox", { name: "Download folder", exact: true }).fill("D:\\My mods");
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await page.getByRole("button", { name: "General", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Download folder", exact: true })).toHaveValue("D:\\My mods");
});

test("browser back follows the visible screen", async ({ page }) => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Mod builds", exact: true })).toBeVisible();
});

test("saving General keeps credentials saved in Account", async ({ page }) => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("textbox", { name: "Download folder", exact: true }).fill("D:\\My mods");
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await page.locator("#nexuskey").fill("test-api-key");
  const accountSave = page.waitForResponse(r => r.url().endsWith("/api/settings") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  await accountSave;
  await page.getByRole("button", { name: "General", exact: true }).click();
  const generalSave = page.waitForRequest(r => r.url().endsWith("/api/settings") && r.method() === "POST");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((await generalSave).postDataJSON()).toMatchObject({
    nexus_api_key: "test-api-key", download_dir: "D:\\My mods",
  });
});

test("mod details do not duplicate guide instructions", async ({ page }) => {
  await page.getByRole("button", { name: /1 Community Patch Pending/ }).click();
  await expect(page.getByText("Install the TPC version.", { exact: true })).toHaveCount(1);
});
