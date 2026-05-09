import puppeteer, { Browser, Page } from 'puppeteer';

let browserInstance: Browser | null = null;

export async function getBrowser(): Promise<Browser> {
  if (!browserInstance || !browserInstance.connected) {
    browserInstance = await puppeteer.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-web-security',
        '--disable-features=VizDisplayCompositor',
      ],
    });
  }
  return browserInstance;
}

export async function closeBrowser(): Promise<void> {
  if (browserInstance) {
    await browserInstance.close();
    browserInstance = null;
  }
}

export async function removeUIElements(page: Page, selectors: string[]): Promise<void> {
  for (const selector of selectors) {
    await page.evaluate((sel) => {
      document.querySelectorAll(sel).forEach((el) => {
        (el as HTMLElement).style.display = 'none';
      });
    }, selector);
  }
}

export async function waitAndScreenshot(
  page: Page,
  outputPath: string,
  waitMs: number = 2000
): Promise<string> {
  await new Promise((r) => setTimeout(r, waitMs));
  await page.screenshot({ path: outputPath, fullPage: false });
  return outputPath;
}
