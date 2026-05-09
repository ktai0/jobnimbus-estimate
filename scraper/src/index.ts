import { geocodeAddress } from './utils/geocode';
import { captureSatellite, calculateGSD } from './scrapers/satellite';
import { captureStreetView } from './scrapers/streetview';
import { scrapeSunroof } from './scrapers/sunroof';
import { closeBrowser } from './browser';
import fs from 'fs';
import path from 'path';

export interface ScrapeResult {
  address: string;
  lat: number;
  lng: number;
  formattedAddress: string;
  satellite: {
    screenshots: string[];
    zoom: number;
    gsdMetersPerPixel: number;
  };
  streetView: {
    screenshots: string[];
  };
  sunroof: {
    sqft: number | null;
    panelCount: number | null;
    screenshot: string | null;
    available: boolean;
    rawData: Record<string, string>;
  };
  outputDir: string;
}

async function scrapeProperty(address: string, outputBase: string): Promise<ScrapeResult> {
  const apiKey = process.env.GOOGLE_MAPS_API_KEY;
  if (!apiKey) {
    throw new Error('GOOGLE_MAPS_API_KEY environment variable is required');
  }

  console.log(`\n=== Scraping: ${address} ===`);

  // 1. Geocode
  console.log('  Geocoding...');
  const geo = await geocodeAddress(address);
  console.log(`  → ${geo.formattedAddress} (${geo.lat}, ${geo.lng})`);

  // Create output directory
  const safeName = address.replace(/[^a-zA-Z0-9]/g, '_').substring(0, 60);
  const outputDir = path.join(outputBase, safeName);
  fs.mkdirSync(outputDir, { recursive: true });

  // 2. Satellite images (via Static Maps API)
  console.log('  Capturing satellite imagery...');
  const satellite = await captureSatellite(geo.lat, geo.lng, outputDir, apiKey);
  console.log(`  → GSD: ${satellite.gsdMetersPerPixel.toFixed(4)} m/px, ${satellite.screenshots.length} images`);

  // 3. Street View images
  console.log('  Capturing street view...');
  const streetView = await captureStreetView(geo.lat, geo.lng, outputDir, apiKey);
  console.log(`  → ${streetView.screenshots.length} street view images`);

  // 4. Sunroof (Puppeteer scrape)
  console.log('  Scraping Project Sunroof...');
  const sunroof = await scrapeSunroof(address, outputDir);
  if (sunroof.available) {
    console.log(`  → Sunroof: ${sunroof.sqft} usable sqft`);
  } else {
    console.log('  → Sunroof: no data available');
  }

  const result: ScrapeResult = {
    address,
    lat: geo.lat,
    lng: geo.lng,
    formattedAddress: geo.formattedAddress,
    satellite,
    streetView,
    sunroof,
    outputDir,
  };

  // Save result JSON
  const resultPath = path.join(outputDir, 'scrape_result.json');
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2));
  console.log(`  → Saved to ${resultPath}`);

  return result;
}

async function main() {
  const address = process.argv[2];
  if (!address) {
    console.error('Usage: npx ts-node src/index.ts "<address>"');
    console.error('  Or pipe JSON: echo \'{"addresses":["..."]}\' | npx ts-node src/index.ts --batch');
    process.exit(1);
  }

  const outputBase = path.join(__dirname, '..', '..', 'output');

  if (address === '--batch') {
    // Read addresses from stdin
    const input = fs.readFileSync(0, 'utf8');
    const { addresses } = JSON.parse(input);
    const results: ScrapeResult[] = [];
    for (const addr of addresses) {
      try {
        const result = await scrapeProperty(addr, outputBase);
        results.push(result);
      } catch (err) {
        console.error(`Failed to scrape ${addr}:`, (err as Error).message);
      }
    }
    // Write batch results
    fs.writeFileSync(
      path.join(outputBase, 'batch_results.json'),
      JSON.stringify(results, null, 2)
    );
  } else {
    await scrapeProperty(address, outputBase);
  }

  await closeBrowser();
}

main().catch((err) => {
  console.error('Fatal error:', err);
  closeBrowser();
  process.exit(1);
});

export { scrapeProperty };
