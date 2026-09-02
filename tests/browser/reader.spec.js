const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.route("**/*", (route) => {
    if (route.request().resourceType() === "image") return route.abort();
    return route.continue();
  });
  await page.addInitScript(() => localStorage.clear());
});

test("selection home exposes both 2026 rule documents", async ({ page }) => {
  await page.goto("/?choose=1");
  await expect(page.getByRole("heading", { name: "차량기술규정" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "경기진행규정" })).toBeVisible();
  await expect(page.getByRole("link", { name: "원문" })).toHaveCount(2);
  await expect(page.locator(".home-description, .data-files")).toHaveCount(0);
  await expect(page.getByText("차량기술규정과 경기진행규정을 연도별로 확인할 수 있습니다.")).toHaveCount(0);
  const pdfLinks = page.getByRole("link", { name: "PDF" });
  await expect(pdfLinks).toHaveCount(2);
  expect(await pdfLinks.evaluateAll(links => links.every(link =>
    !link.hasAttribute("download") && link.target === "_blank"
  ))).toBe(true);
  await expect(page.getByText("매년 이어지는 규정")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth)
  );
});

test("legacy root fragments go to the latest technical document", async ({ page }) => {
  await page.goto("/#formula-technical-10");
  await expect(page).toHaveURL(/\/2026\/formula-technical\/#formula-technical-10$/, { timeout: 15_000 });
  await expect(page.locator("#formula-technical-10")).toContainText("제10조");
  const toolbar = page.locator(".reader-toolbar");
  await expect(toolbar).toBeVisible();
  await expect(toolbar.locator(":scope > *").first()).toHaveAttribute("id", "toc-toggle");
  await expect(page.getByRole("button", { name: "목차", exact: true }).locator("svg")).toHaveCount(1);
  expect(await toolbar.evaluate(element => element.getBoundingClientRect().top)).toBe(0);
  expect(await page.evaluate(() => Boolean(document.elementFromPoint(20, 20)?.closest(".reader-toolbar")))).toBe(true);
  const toolbarLayout = await toolbar.evaluate(element => {
    const toolbarRect = element.getBoundingClientRect();
    const children = [...element.children]
      .filter(child => getComputedStyle(child).display !== "none")
      .map(child => {
        const rect = child.getBoundingClientRect();
        return { left: rect.left, right: rect.right, centerY: rect.top + rect.height / 2 };
      });
    return { toolbarRect, children };
  });
  expect(toolbarLayout.children.every(child =>
    child.left >= toolbarLayout.toolbarRect.left - 0.5 &&
    child.right <= toolbarLayout.toolbarRect.right + 0.5 &&
    Math.abs(child.centerY - toolbarLayout.toolbarRect.height / 2) < 1
  )).toBe(true);
  expect(toolbarLayout.children.every((child, index, children) =>
    index === 0 || children[index - 1].right <= child.left + 0.5
  )).toBe(true);
  const toolbarActions = await toolbar.evaluate(element => {
    const toolbarRect = element.getBoundingClientRect();
    const tocRect = element.querySelector("#toc-toggle").getBoundingClientRect();
    const brand = element.querySelector(".brand");
    const brandRect = brand.getBoundingClientRect();
    const selectors = element.querySelector(".document-selectors");
    const selectorsRect = selectors.getBoundingClientRect();
    const pdfRect = element.querySelector(".toolbar-link").getBoundingClientRect();
    const themeRect = element.querySelector("#theme-toggle").getBoundingClientRect();
    const tocIconRect = element.querySelector("#toc-toggle svg").getBoundingClientRect();
    const themeIconRect = element.querySelector("#theme-toggle svg").getBoundingClientRect();
    const themeStyle = getComputedStyle(element.querySelector("#theme-toggle"));
    return {
      brandFontSize: Number.parseFloat(getComputedStyle(brand).fontSize),
      brandSelectorGap: selectorsRect.left - brandRect.right,
      tocWidth: tocRect.width,
      tocHeight: tocRect.height,
      tocIconWidth: tocIconRect.width,
      pdfWidth: pdfRect.width,
      pdfHeight: pdfRect.height,
      pdfBeforeTheme: pdfRect.right <= themeRect.left,
      themeIsLast: element.lastElementChild.id === "theme-toggle",
      themeRightGap: toolbarRect.right - themeRect.right,
      toolbarRightPadding: Number.parseFloat(getComputedStyle(element).paddingRight),
      themeWidth: themeRect.width,
      themeHeight: themeRect.height,
      themeIconWidth: themeIconRect.width,
      themeDisplay: themeStyle.display,
      toolbarClientWidth: element.clientWidth,
      toolbarScrollWidth: element.scrollWidth,
      unclippedSelectors: [...selectors.querySelectorAll("select")]
        .every(select => select.scrollWidth <= select.clientWidth),
    };
  });
  expect(toolbarActions.brandFontSize).toBeGreaterThanOrEqual(14);
  expect(toolbarActions.brandSelectorGap).toBeGreaterThanOrEqual(6);
  expect(toolbarActions.tocWidth).toBeGreaterThanOrEqual(40);
  expect(toolbarActions.tocHeight).toBeGreaterThanOrEqual(44);
  expect(toolbarActions.tocIconWidth).toBeGreaterThanOrEqual(26);
  expect(toolbarActions.pdfWidth).toBeGreaterThanOrEqual(40);
  expect(toolbarActions.pdfHeight).toBeGreaterThanOrEqual(44);
  expect(toolbarActions.themeWidth).toBeGreaterThanOrEqual(40);
  expect(toolbarActions.themeHeight).toBeGreaterThanOrEqual(44);
  expect(toolbarActions.themeIconWidth).toBeGreaterThanOrEqual(22);
  expect(toolbarActions.toolbarScrollWidth).toBeLessThanOrEqual(toolbarActions.toolbarClientWidth);
  expect(toolbarActions.unclippedSelectors).toBe(true);
  expect(toolbarActions.pdfBeforeTheme).toBe(true);
  expect(toolbarActions.themeIsLast).toBe(true);
  expect(toolbarActions.themeRightGap).toBeCloseTo(toolbarActions.toolbarRightPadding, 0);
  expect(toolbarActions.themeDisplay).toBe("flex");
});

test("reader offers document switching and stable clause anchors", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/2026/formula-competition/#formula-competition-11-12-5-1");
  await expect(page.locator("#document-select option")).toHaveCount(2);
  await expect(page.locator("#formula-competition-11-12-5-1")).toBeVisible();
  await expect(page.locator(".anchor-copy")).toHaveCount(0);
  await expect(page.locator(".document-meta")).toHaveCount(0);
  await expect(page.getByText("2026년판")).toHaveCount(0);
  await expect(page.locator("#search-toggle, #search-dialog")).toHaveCount(0);
  const pdfLink = page.getByRole("link", { name: "PDF" });
  expect(await pdfLink.getAttribute("download")).toBeNull();
  await expect(pdfLink).toHaveAttribute("target", "_blank");
  const context = page.context();
  const pdfPagePromise = context.waitForEvent("page");
  const pdfRequestPromise = context.waitForEvent("request", request => request.url().endsWith(".pdf"));
  await pdfLink.click();
  const [pdfPage, pdfRequest] = await Promise.all([pdfPagePromise, pdfRequestPromise]);
  const pdfResponse = await pdfRequest.response();
  expect(pdfResponse.status()).toBe(200);
  expect(pdfResponse.headers()["content-type"]).toContain("application/pdf");
  expect(pdfResponse.headers()["content-disposition"]).toBeUndefined();
  await pdfPage.close();
  const themeButton = page.locator("#theme-toggle");
  await expect(themeButton.locator("svg")).toHaveCount(1);
  await expect(themeButton).toHaveAttribute("aria-label", "어두운 테마로 전환");
  await themeButton.click();
  await expect(themeButton).toHaveAttribute("aria-label", "밝은 테마로 전환");
  await expect(themeButton.locator("svg circle")).toHaveCount(1);
});

test("reader can open its table of contents", async ({ page }) => {
  await page.goto("/2026/formula-competition/");
  const toc = page.locator("#toc");
  const toggle = page.getByRole("button", { name: "목차", exact: true });
  expect(await toc.evaluate(element => element.inert)).toBe(true);
  await toggle.click();
  await expect(toc).toHaveClass(/open/);
  await expect(toc).toHaveAttribute("aria-hidden", "false");
  await expect(page.locator("#toc nav a").first()).toBeVisible();
  await page.locator("#toc nav a").first().click();
  await expect(page.locator("#back-to-position")).toBeHidden();
  await toggle.click();
  await page.mouse.click(page.viewportSize().width - 4, page.viewportSize().height / 2);
  await expect(toc).not.toHaveClass(/open/);
  expect(await toc.evaluate(element => element.inert)).toBe(true);
  await toggle.click();
  await page.keyboard.press("Escape");
  await expect(toc).not.toHaveClass(/open/);
  await expect(toggle).toBeFocused();
});

test("document cross-reference links offer a return to the exact previous position", async ({ page }) => {
  await page.goto("/2026/formula-technical/#formula-technical-10-8-6");
  const source = page.locator("#formula-technical-10-8-6 a");
  const backButton = page.locator("#back-to-position");
  await source.scrollIntoViewIfNeeded();
  await expect(backButton).toBeHidden();
  const previous = await page.evaluate(() => ({ hash: location.hash, scrollY: window.scrollY }));
  const targetHash = await source.evaluate(link => link.hash);
  await source.click();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe(targetHash);
  await expect(backButton).toBeVisible();
  const buttonAppearance = await backButton.evaluate((button) => {
    const style = getComputedStyle(button);
    const channelValues = color => color.match(/[\d.]+/g).slice(0, 3).map(Number);
    const luminance = (color) => {
      const channels = channelValues(color).map((value) => {
        const normalized = value / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const foreground = luminance(style.color);
    const background = luminance(style.backgroundColor);

    return {
      contrast: (Math.max(foreground, background) + 0.05)
        / (Math.min(foreground, background) + 0.05),
      height: button.getBoundingClientRect().height,
      shadow: style.boxShadow,
      weight: Number(style.fontWeight),
    };
  });
  expect(buttonAppearance.height).toBeGreaterThanOrEqual(44);
  expect(buttonAppearance.weight).toBeGreaterThanOrEqual(700);
  expect(buttonAppearance.contrast).toBeGreaterThanOrEqual(4.5);
  expect(buttonAppearance.shadow).not.toBe("none");
  await expect.poll(() => page.evaluate(expected => Math.abs(window.scrollY - expected), previous.scrollY))
    .toBeGreaterThan(1000);
  await backButton.click();
  await expect(backButton).toBeHidden();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe(previous.hash);
  await expect.poll(() => page.evaluate(expected => Math.abs(window.scrollY - expected), previous.scrollY)).toBeLessThan(3);
  await expect(source).toBeFocused();
});

test("document selectors keep their intrinsic width", async ({ page }) => {
  await page.goto("/2026/formula-technical/");
  await expect(page.locator("#document-select option")).toHaveCount(2);
  const sizing = await page.locator(".document-selectors").evaluate(element => {
    const selectors = [...element.querySelectorAll("select")];
    const elementWidth = element.getBoundingClientRect().width;
    const selectorWidth = selectors.reduce((sum, select) => sum + select.getBoundingClientRect().width, 0);
    return {
      elementWidth,
      availableWidth: element.parentElement.getBoundingClientRect().width,
      flexGrow: getComputedStyle(element).flexGrow,
      extraWidth: elementWidth - selectorWidth,
    };
  });
  expect(sizing.flexGrow).toBe("0");
  expect(sizing.elementWidth).toBeLessThan(sizing.availableWidth / 2);
  expect(sizing.extraWidth).toBeLessThan(12);
});

test("ordinary parentheses stay text and formulas use native MathML", async ({ page }) => {
  await page.goto("/2026/formula-technical/#formula-technical-10");
  await expect(page.locator("#formula-technical-10")).toContainText("제동장치 - Brake System");
  await expect(page.locator("#formula-technical-10-3")).toContainText("LSD(Limited Slip Differential)");
  await expect(page.locator("#formula-technical-10-6")).toContainText("제동장치(Brake by wire)");
  await expect(page.locator("#formula-technical-10-8-2")).toContainText("0% ~ 100%");
  await expect(page.locator("mjx-container")).toHaveCount(0);
  await expect(page.locator("#formula-technical-14-1-2 math[display='block']")).toHaveCount(1);
});

test("documents, tables, and formulas fit every supported viewport", async ({ page }) => {
  for (const document of ["formula-technical", "formula-competition"]) {
    await page.goto(`/2026/${document}/`);
    await page.evaluate(async () => {
      await document.fonts.load('17px "Pretendard"');
      await document.fonts.load('17px "STIX Two Math"');
    });
    const layout = await page.evaluate(() => {
      const viewportWidth = document.documentElement.clientWidth;
      const overflow = [...document.querySelectorAll(".rules-content table, .rules-content math[display='block']")]
        .map((node) => ({
          tag: node.tagName,
          id: node.closest("[data-clause-id]")?.id || null,
          left: node.getBoundingClientRect().left,
          right: node.getBoundingClientRect().right,
        }))
        .filter(({ left, right }) => left < -0.5 || right > viewportWidth + 0.5);
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth,
        overflow,
        readingFont: document.fonts.check('17px "Pretendard"'),
        mathFont: document.fonts.check('17px "STIX Two Math"'),
      };
    });
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.overflow).toEqual([]);
    expect(layout.readingFont).toBe(true);
    expect(layout.mathFont).toBe(true);
  }
});
