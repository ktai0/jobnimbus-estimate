const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface AnalyzeResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface LineItems {
  ridge_length_ft: number;
  hip_length_ft: number;
  valley_length_ft: number;
  rake_length_ft: number;
  eave_length_ft: number;
  flashing_length_ft: number;
  step_flashing_length_ft: number;
  drip_edge_length_ft: number;
  gutter_length_ft: number;
}

export interface PitchEstimate {
  pitch: string;
  rise: number;
  run: number;
  multiplier: number;
  confidence: number;
}

export interface FootprintSource {
  source: string;
  footprint_sqft: number;
  confidence: number;
}

export interface RoofMeasurements {
  total_roof_sqft: number;
  footprint_sqft: number;
  pitch: PitchEstimate;
  roof_shape: string;
  facet_count: number;
  line_items: LineItems;
  footprint_sources: FootprintSource[];
  confidence: number;
}

export interface EstimateLineItem {
  category: string;
  description: string;
  quantity: number;
  unit: string;
  unit_cost: number;
  total_cost: number;
}

export interface CostEstimate {
  tier: string;
  material_items: EstimateLineItem[];
  labor_items: EstimateLineItem[];
  other_items: EstimateLineItem[];
  materials_subtotal: number;
  labor_subtotal: number;
  other_subtotal: number;
  waste_factor_amount: number;
  overhead_profit_amount: number;
  grand_total: number;
}

export interface SolarValidation {
  available: boolean;
  whole_roof_sqft: number | null;
  usable_sqft: number | null;
  segment_count: number;
  avg_pitch_degrees: number | null;
  avg_pitch_rise: number | null;
  area_match_ratio: number | null;
  pitch_match: boolean | null;
}

export interface PropertyReport {
  address: string;
  formatted_address: string;
  lat: number;
  lng: number;
  measurements: RoofMeasurements;
  estimates: Record<string, CostEstimate>;
  satellite_images: string[];
  streetview_images: string[];
  sunroof_image: string | null;
  sunroof_usable_sqft: number | null;
  solar_validation: SolarValidation | null;
  report_date: string;
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  address: string;
  report: PropertyReport | null;
  error: string | null;
}

export async function startAnalysis(address: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ address }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function startUploadAnalysis(
  aerialPhotos: File[],
  streetviewPhotos: File[],
  address?: string
): Promise<AnalyzeResponse> {
  const formData = new FormData();
  for (const file of aerialPhotos) {
    formData.append("aerial_photos", file);
  }
  for (const file of streetviewPhotos) {
    formData.append("streetview_photos", file);
  }
  if (address) {
    formData.append("address", address);
  }
  const res = await fetch(`${API_BASE}/api/analyze/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getReport(jobId: string): Promise<PropertyReport> {
  const res = await fetch(`${API_BASE}/api/reports/${jobId}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function listReports(): Promise<
  { job_id: string; address: string; status: string; total_sqft: number | null }[]
> {
  const res = await fetch(`${API_BASE}/api/reports`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function getPdfUrl(jobId: string): string {
  return `${API_BASE}/api/reports/${jobId}/pdf`;
}

export function pollJob(
  jobId: string,
  onUpdate: (status: JobStatus) => void,
  intervalMs = 2000
): () => void {
  let active = true;

  const poll = async () => {
    while (active) {
      try {
        const status = await getJobStatus(jobId);
        onUpdate(status);
        if (status.status === "completed" || status.status === "failed") {
          break;
        }
      } catch {
        // Retry on error
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  };

  poll();
  return () => {
    active = false;
  };
}
