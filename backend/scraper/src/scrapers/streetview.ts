import https from 'https';
import fs from 'fs';
import path from 'path';

export interface StreetViewResult {
  screenshots: string[];
}

/**
 * Query the Street View Metadata API to find the panorama location,
 * then compute the heading from the camera toward the building.
 */
async function getHeadingTowardBuilding(
  lat: number,
  lng: number,
  apiKey: string
): Promise<number> {
  const metaUrl = `https://maps.googleapis.com/maps/api/streetview/metadata?location=${lat},${lng}&source=outdoor&key=${apiKey}`;

  return new Promise((resolve) => {
    https.get(metaUrl, (response) => {
      let body = '';
      response.on('data', (chunk: Buffer) => { body += chunk.toString(); });
      response.on('end', () => {
        try {
          const data = JSON.parse(body);
          if (data.status === 'OK' && data.location) {
            const panoLat: number = data.location.lat;
            const panoLng: number = data.location.lng;
            const dLng = lng - panoLng;
            const dLat = lat - panoLat;
            const heading = ((Math.atan2(dLng, dLat) * 180) / Math.PI + 360) % 360;
            resolve(heading);
            return;
          }
        } catch {
          // fall through
        }
        resolve(0);
      });
    }).on('error', () => {
      resolve(0);
    });
  });
}

/**
 * Capture Street View images via Google Static Street View API.
 * Computes heading toward the building so all views face the property.
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

  // Compute heading from Street View camera toward the building
  const baseHeading = await getHeadingTowardBuilding(lat, lng, apiKey);
  const headings = [0, 90, 180, 270].map(
    (offset) => Math.round((baseHeading + offset) % 360)
  );

  // Standard captures (pitch=20) + roof-focused captures (pitch=35, looking up toward roof)
  const captureConfigs = [
    { pitchAngle: 20, suffix: '' },
    { pitchAngle: 35, suffix: '_roof' },
  ];

  for (const { pitchAngle, suffix } of captureConfigs) {
    for (const heading of headings) {
      const url = `https://maps.googleapis.com/maps/api/streetview?size=${size}&location=${lat},${lng}&heading=${heading}&pitch=${pitchAngle}&fov=90&key=${apiKey}`;
      const filepath = path.join(outputDir, `streetview_${heading}${suffix}.jpg`);

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
