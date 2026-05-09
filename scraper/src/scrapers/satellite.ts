import https from 'https';
import fs from 'fs';
import path from 'path';

export interface SatelliteResult {
  screenshots: string[];
  zoom: number;
  gsdMetersPerPixel: number;
}

/**
 * Calculate Ground Sample Distance (meters per pixel) for Google Maps
 * at a given zoom level and latitude.
 */
export function calculateGSD(lat: number, zoom: number, scale: number = 2): number {
  // At zoom 0, the entire world (circumference) fits in 256 pixels
  // GSD = C * cos(lat) / (256 * 2^zoom) where C = 40075016.686 meters
  const C = 40075016.686;
  const gsd = (C * Math.cos((lat * Math.PI) / 180)) / (256 * Math.pow(2, zoom) * scale);
  return gsd;
}

/**
 * Download satellite image via Google Maps Static API.
 * Returns the path to the saved image and the GSD.
 */
export async function captureSatellite(
  lat: number,
  lng: number,
  outputDir: string,
  apiKey: string
): Promise<SatelliteResult> {
  fs.mkdirSync(outputDir, { recursive: true });

  const screenshots: string[] = [];
  const zoom = 20;
  const size = '640x640';
  const scale = 2; // gives 1280x1280 actual pixels

  // Capture at zoom 20 (primary - building level)
  const url20 = `https://maps.googleapis.com/maps/api/staticmap?center=${lat},${lng}&zoom=${zoom}&size=${size}&scale=${scale}&maptype=satellite&key=${apiKey}`;
  const file20 = path.join(outputDir, 'satellite_z20.png');
  await downloadImage(url20, file20);
  screenshots.push(file20);

  // Capture at zoom 19 (wider context)
  const url19 = `https://maps.googleapis.com/maps/api/staticmap?center=${lat},${lng}&zoom=19&size=${size}&scale=${scale}&maptype=satellite&key=${apiKey}`;
  const file19 = path.join(outputDir, 'satellite_z19.png');
  await downloadImage(url19, file19);
  screenshots.push(file19);

  const gsd = calculateGSD(lat, zoom, scale);

  return { screenshots, zoom, gsdMetersPerPixel: gsd };
}

function downloadImage(url: string, filepath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(filepath);
    https.get(url, (response) => {
      // Handle redirects
      if (response.statusCode === 301 || response.statusCode === 302) {
        const redirectUrl = response.headers.location;
        if (redirectUrl) {
          downloadImage(redirectUrl, filepath).then(resolve).catch(reject);
          return;
        }
      }
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      fs.unlink(filepath, () => {});
      reject(err);
    });
  });
}
