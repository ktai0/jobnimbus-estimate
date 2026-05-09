import { getBrowser, removeUIElements, waitAndScreenshot } from '../browser';
import path from 'path';
import fs from 'fs';

export interface SunroofResult {
  sqft: number | null;
  panelCount: number | null;
  screenshot: string | null;
  rawData: Record<string, string>;
  available: boolean;
}

/**
 * Scrape Google Project Sunroof for roof data.
 * Gets usable sqft (solar-viable area) and a roof overlay screenshot.
 */
export async function scrapeSunroof(
  address: string,
  outputDir: string
): Promise<SunroofResult> {
  fs.mkdirSync(outputDir, { recursive: true });

  const browser = await getBrowser();
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const result: SunroofResult = {
    sqft: null,
    panelCount: null,
    screenshot: null,
    rawData: {},
    available: false,
  };

  try {
    // Navigate to Project Sunroof
    await page.goto('https://sunroof.withgoogle.com/', {
      waitUntil: 'networkidle2',
      timeout: 30000,
    });

    // Look for the address input and enter the address
    const inputSelector = 'input[type="text"], input[class*="search"], input[aria-label*="address"], #address-input, .address-input input';
    await page.waitForSelector(inputSelector, { timeout: 10000 });
    await page.click(inputSelector);
    await page.type(inputSelector, address, { delay: 50 });

    // Press Enter or click search
    await page.keyboard.press('Enter');

    // Wait for results to load
    await new Promise((r) => setTimeout(r, 5000));

    // Try to extract data from the page
    const pageText = await page.evaluate(() => document.body.innerText);

    // Parse sqft from text like "X,XXX sq ft of usable space"
    const sqftMatch = pageText.match(/([\d,]+)\s*sq\s*ft/i);
    if (sqftMatch) {
      result.sqft = parseInt(sqftMatch[1].replace(/,/g, ''), 10);
      result.available = true;
    }

    // Parse panel count
    const panelMatch = pageText.match(/([\d,]+)\s*panels?\s/i);
    if (panelMatch) {
      result.panelCount = parseInt(panelMatch[1].replace(/,/g, ''), 10);
    }

    // Store any other useful text
    const lines = pageText.split('\n').filter((l: string) => l.trim().length > 0);
    for (const line of lines) {
      if (line.includes('sq ft') || line.includes('panel') || line.includes('sun') || line.includes('roof')) {
        result.rawData[line.trim().substring(0, 50)] = line.trim();
      }
    }

    if (result.available) {
      // Remove UI elements for clean screenshot
      await removeUIElements(page, [
        'header', 'nav', '.header', '.nav',
        '[class*="sidebar"]', '[class*="search"]',
        '[class*="panel"]:not([class*="solar"])',
        'footer', '.footer',
        '[class*="button"]', '[class*="btn"]',
        '[class*="overlay"]:not([class*="roof"])',
      ]);

      const screenshotPath = path.join(outputDir, 'sunroof_overlay.png');
      await waitAndScreenshot(page, screenshotPath, 1000);
      result.screenshot = screenshotPath;
    }
  } catch (error) {
    console.error('Sunroof scraping failed:', (error as Error).message);
  } finally {
    await page.close();
  }

  return result;
}
