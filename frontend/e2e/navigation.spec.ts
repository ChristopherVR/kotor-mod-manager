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
  let settings = { language: "en", download_dir: "C:\\Downloads", seven_zip_path: "" };
  await page.route("http://127.0.0.1:8756/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/extractor/status") {
      await route.fulfill({ json: { seven_zip_path: settings.seven_zip_path || null } });
      return;
    }
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
      "/api/settings": { language: "en", download_dir: "C:\\Downloads" },
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

test("General editing waits for saved settings to load", async ({ page }) => {
  let releaseSettings!: () => void;
  const settingsReady = new Promise<void>(resolve => { releaseSettings = resolve; });
  await page.route("http://127.0.0.1:8756/api/settings", async route => {
    if (route.request().method() === "GET") await settingsReady;
    await route.fallback();
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const folder = page.getByRole("textbox", { name: "Download folder", exact: true });
  const save = page.getByRole("button", { name: "Save", exact: true });
  try {
    await expect(folder).toBeDisabled();
    await expect(folder.locator("..").getByRole("button")).toBeDisabled();
    await expect(page.getByPlaceholder("1920x1080", { exact: true })).toBeDisabled();
    await expect(save).toBeDisabled();
  } finally {
    releaseSettings();
  }
  await expect(folder).toBeEnabled();
  await expect(folder).toHaveValue("C:\\Downloads");
  await folder.fill("D:\\My mods");
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await page.getByRole("button", { name: "General", exact: true }).click();
  await expect(folder).toHaveValue("D:\\My mods");
  const saved = page.waitForRequest(r => r.url().endsWith("/api/settings") && r.method() === "POST");
  await save.click();
  expect((await saved).postDataJSON()).toMatchObject({ download_dir: "D:\\My mods" });
});

test("7-Zip path can be saved and cleared without overwriting other settings", async ({ page }) => {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const path = page.getByLabel("7-Zip executable (optional)", { exact: true });
  await expect(path).toBeEnabled();
  await path.fill("D:\\Portable Tools\\7z.exe");
  const saved = page.waitForRequest(r => r.url().endsWith("/api/settings") && r.method() === "POST");
  await page.getByRole("button", { name: "Save 7-Zip path", exact: true }).click();
  expect((await saved).postDataJSON()).toMatchObject({
    seven_zip_path: "D:\\Portable Tools\\7z.exe", download_dir: "C:\\Downloads",
  });
  await expect(page.getByRole("status")).toContainText("D:\\Portable Tools\\7z.exe");

  // Saving another General field must retain the executable override.
  await page.getByLabel("Download folder", { exact: true }).fill("D:\\Mods");
  const generalSaved = page.waitForRequest(r => r.url().endsWith("/api/settings") && r.method() === "POST");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((await generalSaved).postDataJSON()).toMatchObject({ seven_zip_path: "D:\\Portable Tools\\7z.exe" });

  const cleared = page.waitForRequest(r => r.url().endsWith("/api/settings") && r.method() === "POST");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  expect((await cleared).postDataJSON()).toMatchObject({ seven_zip_path: "", download_dir: "D:\\Mods" });
  await expect(path).toHaveValue("");
  await expect(page.getByRole("status")).toContainText("7-Zip was not found");
});

test("mod details do not duplicate guide instructions", async ({ page }) => {
  await page.getByRole("button", { name: /1 Community Patch Pending/ }).click();
  await expect(page.getByText("Install the TPC version.", { exact: true })).toHaveCount(1);
});

test("Sign in with Nexus Mods opens the Nexus page and waits for approval", async ({ page }) => {
  let flow = { status: "idle" };
  const authorize = "https://users.nexusmods.com/oauth/authorize?client_id=test";
  await page.route("http://127.0.0.1:8756/api/nexus/oauth**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/start")) {
      flow = { status: "waiting" };
      await route.fulfill({ json: { ok: true, url: authorize } });
      return;
    }
    if (path.endsWith("/cancel")) {
      flow = { status: "cancelled" };
      await route.fulfill({ json: { ok: true } });
      return;
    }
    await route.fulfill({ json: { available: true, signed_in: false, name: "", is_premium: false, flow } });
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await expect(page.locator("#nexuskey")).toHaveCount(0);
  const opened = page.waitForRequest(r => r.url().includes("/api/update/open"));
  await page.getByRole("button", { name: "Sign in with Nexus Mods", exact: true }).click();
  expect(decodeURIComponent((await opened).url())).toContain(authorize);
  await expect(page.getByText("Finish signing in on the Nexus Mods page")).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in with Nexus Mods", exact: true })).toBeEnabled();
});

test("Nexus client ID can be typed next to the sign-in button", async ({ page }) => {
  let started: unknown = null;
  await page.route("http://127.0.0.1:8756/api/nexus/oauth**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/start")) {
      started = route.request().postDataJSON();
      await route.fulfill({ json: { ok: true, url: "https://users.nexusmods.com/oauth/authorize?x=1" } });
      return;
    }
    await route.fulfill({ json: {
      available: false, built_in_client: false, client_id: "",
      signed_in: false, name: "", is_premium: false, flow: { status: "idle" },
    } });
  });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Account", exact: true }).click();
  const signIn = page.getByRole("button", { name: "Sign in with Nexus Mods", exact: true });
  await expect(signIn).toBeDisabled();
  await page.getByRole("textbox", { name: "Nexus client ID", exact: true }).fill("  kmi_client  ");
  await expect(signIn).toBeEnabled();
  await signIn.click();
  await expect.poll(() => started).toEqual({ client_id: "kmi_client" });
});

test("No client ID box once the client ID is built in", async ({ page }) => {
  await page.route("http://127.0.0.1:8756/api/nexus/oauth**", route => route.fulfill({
    json: { available: true, built_in_client: true, client_id: "", signed_in: false,
            name: "", is_premium: false, flow: { status: "idle" } },
  }));
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in with Nexus Mods", exact: true })).toBeEnabled();
  await expect(page.locator("#nexusclientid")).toHaveCount(0);
});
