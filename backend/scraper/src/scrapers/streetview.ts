import https from 'https';
import fs from 'fs';
import path from 'path';

export interface StreetViewResult {
  screenshots: string[];
}

/**
 * Capture Street View images via Google Static Street View API.
 * Takes multiple angles to help with pitch estimation.
 */
export async function captureStreetView(
  lat: number,
  lng: number,
  outputDir: string,
  apiKey: string
): Promise<StreetViewResult> {
  fs.mkdirSync(outputDir, { recursive: true });

  const screenshots: string[] = [];
  const size = '640x480';

  // Capture from multiple headings to see different angles of the roof
  const headings = [0, 90, 180, 270]; // N, E, S, W

  for (const heading of headings) {
    const url = `https://maps.googleapis.com/maps/api/streetview?size=${size}&location=${lat},${lng}&heading=${heading}&pitch=20&fov=90&key=${apiKey}`;
    const filepath = path.join(outputDir, `streetview_${heading}.jpg`);

    try {
      await downloadImage(url, filepath);
      // Check file size - Google returns a small grey image if no streetview available
      const stats = fs.statSync(filepath);
      if (stats.size > 5000) {
        screenshots.push(filepath);
      } else {
        fs.unlinkSync(filepath);
      }
    } catch {
      // Skip failed captures
    }
  }

  return { screenshots };
}

function downloadImage(url: string, filepath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(filepath);
    https.get(url, (response) => {
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
