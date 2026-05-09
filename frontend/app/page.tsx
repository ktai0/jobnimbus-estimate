"use client";

import { useState } from "react";
import { startAnalysis, startUploadAnalysis, pollJob, getPdfUrl, type JobStatus } from "@/lib/api";
import UploadInput from "./components/UploadInput";

type InputMode = "address" | "upload";

const ADDRESS_STEPS = [
  { key: "pending", label: "Initializing", icon: "1" },
  { key: "geocoding", label: "Geocoding address", icon: "2" },
  { key: "scraping", label: "Capturing aerial & street view imagery", icon: "3" },
  { key: "analyzing", label: "AI analyzing roof geometry", icon: "4" },
  { key: "measuring", label: "Computing measurements", icon: "5" },
  { key: "estimating", label: "Generating estimate", icon: "6" },
];

const UPLOAD_STEPS = [
  { key: "pending", label: "Initializing", icon: "1" },
  { key: "analyzing", label: "AI analyzing roof geometry", icon: "2" },
  { key: "measuring", label: "Computing measurements", icon: "3" },
  { key: "estimating", label: "Generating estimate", icon: "4" },
];

function getStepIndex(status: string, mode: InputMode): number {
  if (status === "pending") return 0;
  if (mode === "upload") {
    if (status === "running") return 1;
    if (status === "completed") return 4;
  } else {
    if (status === "running") return 3;
    if (status === "completed") return 6;
  }
  return 0;
}

export default function Home() {
  const [mode, setMode] = useState<InputMode>("address");
  const [address, setAddress] = useState("");
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startPolling = (jobId: string, addr: string) => {
    setJobStatus({ job_id: jobId, status: "pending", address: addr, report: null, error: null });
    pollJob(jobId, (status) => {
      setJobStatus(status);
      if (status.status === "completed" || status.status === "failed") {
        setLoading(false);
        if (status.status === "failed") setError(status.error || "Analysis failed");
      }
    });
  };

  const handleAnalyze = async () => {
    if (!address.trim()) return;
    setLoading(true);
    setError(null);
    setJobStatus(null);
    try {
      const resp = await startAnalysis(address);
      startPolling(resp.job_id, address);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
      setLoading(false);
    }
  };

  const handleUpload = async (data: { aerialPhotos: File[]; streetviewPhotos: File[]; address: string }) => {
    setLoading(true);
    setError(null);
    setJobStatus(null);
    try {
      const resp = await startUploadAnalysis(data.aerialPhotos, data.streetviewPhotos, data.address || undefined);
      startPolling(resp.job_id, data.address || "Uploaded Photos");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
      setLoading(false);
    }
  };

  const report = jobStatus?.report;
  const steps = mode === "upload" ? UPLOAD_STEPS : ADDRESS_STEPS;
  const activeStep = jobStatus ? getStepIndex(jobStatus.status, mode) : -1;

  return (
    <main className="flex-1">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">CloudNimbus</h1>
              <p className="text-sm text-gray-500">Aerial Roof Measurement & Auto-Estimating</p>
            </div>
          </div>
        </div>
      </header>

      {/* Input Section */}
      <section className="max-w-5xl mx-auto px-6 py-12">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          {/* Mode Toggle */}
          <div className="flex bg-gray-100 rounded-lg p-1 mb-6">
            {([["address", "Enter Address"], ["upload", "Upload Photos"]] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => !loading && setMode(key)}
                className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  mode === key ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
                }`}
                disabled={loading}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === "address" ? (
            <>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Enter a property address</h2>
              <div className="flex gap-3">
                <input
                  type="text"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
                  placeholder="e.g., 21106 Kenswick Meadows Ct, Humble, TX 77338"
                  className="flex-1 px-4 py-3 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={loading}
                />
                <button
                  onClick={handleAnalyze}
                  disabled={loading || !address.trim()}
                  className="px-8 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? "Analyzing..." : "Analyze"}
                </button>
              </div>
              {error && <p className="mt-3 text-red-600 text-sm">{error}</p>}
            </>
          ) : (
            <UploadInput onSubmit={handleUpload} loading={loading} error={error} />
          )}
        </div>
      </section>

      {/* Progress */}
      {loading && jobStatus && (
        <section className="max-w-5xl mx-auto px-6 pb-8">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
            <h3 className="text-lg font-semibold text-gray-900 mb-6">Analyzing property...</h3>
            <div className="space-y-4">
              {steps.map((step, i) => (
                <div key={step.key} className="flex items-center gap-4">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                      i < activeStep
                        ? "bg-green-100 text-green-700"
                        : i === activeStep
                          ? "bg-blue-100 text-blue-700 animate-pulse"
                          : "bg-gray-100 text-gray-400"
                    }`}
                  >
                    {i < activeStep ? (
                      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      step.icon
                    )}
                  </div>
                  <span className={i <= activeStep ? "text-gray-900" : "text-gray-400"}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Report */}
      {report && jobStatus && <ReportView report={report} jobId={jobStatus.job_id} />}
    </main>
  );
}

function ReportView({ report, jobId }: { report: NonNullable<JobStatus["report"]>; jobId: string }) {
  const [tier, setTier] = useState<string>("standard");
  const m = report.measurements;
  const estimate = report.estimates[tier];

  const handleDownloadPdf = () => {
    window.open(getPdfUrl(jobId), "_blank");
  };

  return (
    <section className="max-w-5xl mx-auto px-6 pb-12 space-y-6">
      {/* Header */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-xl font-bold text-gray-900">{report.formatted_address || report.address}</h2>
            <p className="text-sm text-gray-500 mt-1">Report generated {new Date(report.report_date).toLocaleDateString()}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${
              m.confidence >= 0.7
                ? "bg-green-100 text-green-800"
                : m.confidence >= 0.4
                  ? "bg-yellow-100 text-yellow-800"
                  : "bg-red-100 text-red-800"
            }`}>
              {Math.round(m.confidence * 100)}% confidence
            </span>
            <button
              onClick={handleDownloadPdf}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-1.5"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Download PDF
            </button>
          </div>
        </div>
      </div>

      {/* Measurements Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Total Roof Area" value={`${m.total_roof_sqft.toLocaleString()} sq ft`} />
        <StatCard label="Footprint Area" value={`${m.footprint_sqft.toLocaleString()} sq ft`} />
        <StatCard label="Pitch" value={m.pitch.pitch} sub={`Multiplier: ${m.pitch.multiplier.toFixed(3)}`} />
        <StatCard label="Roof Shape" value={m.roof_shape.replace(/-/g, " ")} sub={`${m.facet_count} facets`} />
      </div>

      {/* Data Sources */}
      {m.footprint_sources.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-md font-semibold text-gray-900 mb-3">Data Sources</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {m.footprint_sources.map((src, i) => (
              <div key={i} className="border border-gray-200 rounded-lg p-3">
                <p className="text-sm font-medium text-gray-700">{src.source.replace(/_/g, " ")}</p>
                <p className="text-lg font-bold text-gray-900">{src.footprint_sqft.toLocaleString()} sq ft</p>
                <p className="text-xs text-gray-500">{Math.round(src.confidence * 100)}% confidence</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Line Items */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-md font-semibold text-gray-900 mb-3">Roof Line Items</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 text-gray-600 font-medium">Feature</th>
                <th className="text-right py-2 text-gray-600 font-medium">Length (ft)</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["Ridge", m.line_items.ridge_length_ft],
                  ["Hip", m.line_items.hip_length_ft],
                  ["Valley", m.line_items.valley_length_ft],
                  ["Rake", m.line_items.rake_length_ft],
                  ["Eave", m.line_items.eave_length_ft],
                  ["Flashing", m.line_items.flashing_length_ft],
                  ["Step Flashing", m.line_items.step_flashing_length_ft],
                ] as [string, number][]
              )
                .filter(([, v]) => v > 0)
                .map(([name, value]) => (
                  <tr key={name} className="border-b border-gray-100">
                    <td className="py-2 text-gray-900">{name}</td>
                    <td className="py-2 text-right text-gray-900 font-mono">{value.toFixed(0)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Estimate */}
      {estimate && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-md font-semibold text-gray-900">Cost Estimate</h3>
            <div className="flex bg-gray-100 rounded-lg p-1">
              {["economy", "standard", "premium"].map((t) => (
                <button
                  key={t}
                  onClick={() => setTier(t)}
                  className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    tier === t
                      ? "bg-white text-gray-900 shadow-sm"
                      : "text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <EstimateSection title="Materials" items={estimate.material_items} subtotal={estimate.materials_subtotal} />
            <EstimateSection title="Labor" items={estimate.labor_items} subtotal={estimate.labor_subtotal} />
            <EstimateSection title="Other" items={estimate.other_items} subtotal={estimate.other_subtotal} />

            <div className="border-t border-gray-200 pt-4 space-y-2">
              <div className="flex justify-between text-sm text-gray-600">
                <span>Waste factor (12%)</span>
                <span>${estimate.waste_factor_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-sm text-gray-600">
                <span>Overhead & profit (25% on labor)</span>
                <span>${estimate.overhead_profit_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-lg font-bold text-gray-900 pt-2 border-t border-gray-300">
                <span>Grand Total</span>
                <span>${estimate.grand_total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Solar Validation */}
      {report.solar_validation?.available && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-md font-semibold text-gray-900 mb-3">Cross-Validation (Google Solar API)</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-sm text-gray-500">Solar Roof Area</p>
              <p className="text-lg font-bold text-gray-900">
                {report.solar_validation.whole_roof_sqft?.toLocaleString()} sq ft
              </p>
              {report.solar_validation.area_match_ratio && (
                <p className={`text-xs font-medium ${
                  report.solar_validation.area_match_ratio >= 0.85 && report.solar_validation.area_match_ratio <= 1.15
                    ? "text-green-600" : "text-yellow-600"
                }`}>
                  Match ratio: {(report.solar_validation.area_match_ratio * 100).toFixed(1)}%
                </p>
              )}
            </div>
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-sm text-gray-500">Solar Pitch</p>
              <p className="text-lg font-bold text-gray-900">
                {report.solar_validation.avg_pitch_rise}:12
              </p>
              {report.solar_validation.pitch_match !== null && (
                <p className={`text-xs font-medium ${
                  report.solar_validation.pitch_match ? "text-green-600" : "text-yellow-600"
                }`}>
                  {report.solar_validation.pitch_match ? "Agrees with our estimate" : "Differs from our estimate"}
                </p>
              )}
            </div>
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-sm text-gray-500">Roof Segments</p>
              <p className="text-lg font-bold text-gray-900">
                {report.solar_validation.segment_count}
              </p>
              <p className="text-xs text-gray-500">
                {report.solar_validation.avg_pitch_degrees?.toFixed(1)}° avg pitch
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Sunroof cross-check */}
      {report.sunroof_usable_sqft && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
          <p className="text-sm text-blue-800">
            <strong>Sunroof Cross-Check:</strong> Google Project Sunroof reports {report.sunroof_usable_sqft.toLocaleString()} sq ft of usable (solar-viable) roof area.
            Estimated total roof area from Sunroof: ~{Math.round(report.sunroof_usable_sqft / 0.80).toLocaleString()} sq ft.
          </p>
        </div>
      )}
    </section>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function EstimateSection({
  title,
  items,
  subtotal,
}: {
  title: string;
  items: { description: string; quantity: number; unit: string; unit_cost: number; total_cost: number }[];
  subtotal: number;
}) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-gray-700 mb-2">{title}</h4>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-gray-500">
            <th className="text-left py-1 font-normal">Item</th>
            <th className="text-right py-1 font-normal">Qty</th>
            <th className="text-right py-1 font-normal">Unit</th>
            <th className="text-right py-1 font-normal">Unit Cost</th>
            <th className="text-right py-1 font-normal">Total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i} className="border-b border-gray-50">
              <td className="py-1.5 text-gray-900">{item.description}</td>
              <td className="py-1.5 text-right text-gray-700 font-mono">{item.quantity}</td>
              <td className="py-1.5 text-right text-gray-500">{item.unit}</td>
              <td className="py-1.5 text-right text-gray-700 font-mono">${item.unit_cost}</td>
              <td className="py-1.5 text-right text-gray-900 font-mono">${item.total_cost.toLocaleString()}</td>
            </tr>
          ))}
          <tr className="font-medium">
            <td colSpan={4} className="py-2 text-right text-gray-700">Subtotal</td>
            <td className="py-2 text-right text-gray-900 font-mono">${subtotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
