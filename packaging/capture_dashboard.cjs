const fs = require("fs");
const { chromium } = require("playwright");

async function main() {
  const [url, screenshotPath, metadataPath] = process.argv.slice(2);
  if (!url || !screenshotPath || !metadataPath) {
    throw new Error("usage: capture_dashboard.cjs URL SCREENSHOT METADATA");
  }
  const launchOptions = { headless: true };
  if (process.env.PAT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PAT_CHROMIUM_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    const response = await page.goto(url, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    if (!response || response.status() !== 200) {
      throw new Error(`dashboard HTTP status was ${response ? response.status() : "missing"}`);
    }
    await page.waitForFunction(
      () => {
        const text = document.body ? document.body.innerText : "";
        const expectedView =
          text.includes("Command Center") || text.includes("System Status");
        return text.includes("Personal Alpha") && expectedView && text.length > 200;
      },
      { timeout: 45000 },
    );
    await page.waitForTimeout(2000);
    const title = await page.title();
    const bodyText = await page.locator("body").innerText();
    await page.screenshot({ path: screenshotPath, fullPage: true });
    fs.writeFileSync(
      metadataPath,
      JSON.stringify(
        {
          url,
          http_status: response.status(),
          title,
          body_text_length: bodyText.length,
          rendered_marker: bodyText.includes("Command Center")
            ? "Command Center"
            : "System Status",
          captured_at: new Date().toISOString(),
        },
        null,
        2,
      ),
      "utf8",
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
