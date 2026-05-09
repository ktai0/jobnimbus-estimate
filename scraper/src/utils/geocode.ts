import https from 'https';

export interface GeocodeResult {
  lat: number;
  lng: number;
  formattedAddress: string;
}

function httpsGet(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'CloudNimbus/1.0' } }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => resolve(data));
      res.on('error', reject);
    }).on('error', reject);
  });
}

export async function geocodeAddress(address: string): Promise<GeocodeResult> {
  const googleKey = process.env.GOOGLE_MAPS_API_KEY;

  if (googleKey) {
    return geocodeGoogle(address, googleKey);
  }
  return geocodeNominatim(address);
}

async function geocodeGoogle(address: string, apiKey: string): Promise<GeocodeResult> {
  const encoded = encodeURIComponent(address);
  const url = `https://maps.googleapis.com/maps/api/geocode/json?address=${encoded}&key=${apiKey}`;
  const data = JSON.parse(await httpsGet(url));

  if (data.status !== 'OK' || !data.results?.length) {
    throw new Error(`Google geocoding failed: ${data.status} - ${data.error_message || 'No results'}`);
  }

  const result = data.results[0];
  return {
    lat: result.geometry.location.lat,
    lng: result.geometry.location.lng,
    formattedAddress: result.formatted_address,
  };
}

async function geocodeNominatim(address: string): Promise<GeocodeResult> {
  const encoded = encodeURIComponent(address);
  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encoded}&limit=1`;
  const data = JSON.parse(await httpsGet(url));

  if (!data.length) {
    throw new Error(`Nominatim geocoding failed: no results for "${address}"`);
  }

  return {
    lat: parseFloat(data[0].lat),
    lng: parseFloat(data[0].lon),
    formattedAddress: data[0].display_name,
  };
}
