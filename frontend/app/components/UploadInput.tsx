"use client";

import { useCallback, useRef, useState } from "react";

interface UploadInputProps {
  onSubmit: (formData: { aerialPhotos: File[]; streetviewPhotos: File[]; address: string }) => void;
  loading: boolean;
  error: string | null;
}

function FileThumbnail({ file, onRemove, disabled }: { file: File; onRemove: () => void; disabled: boolean }) {
  return (
    <div className="relative group">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={URL.createObjectURL(file)}
        alt={file.name}
        className="w-16 h-16 object-cover rounded-lg border border-gray-200"
      />
      {!disabled && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
        >
          x
        </button>
      )}
    </div>
  );
}

function FileDropZone({
  label,
  files,
  onFilesChange,
  disabled,
}: {
  label: string;
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const dropped = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
      if (dropped.length > 0) onFilesChange([...files, ...dropped]);
    },
    [files, onFilesChange, disabled]
  );

  const handleSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = Array.from(e.target.files || []);
      if (selected.length > 0) onFilesChange([...files, ...selected]);
      if (inputRef.current) inputRef.current.value = "";
    },
    [files, onFilesChange]
  );

  const dropZoneClass = `border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
    dragOver ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-gray-400"
  } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`;

  return (
    <div>
      <p className="text-sm font-medium text-gray-700 mb-2">{label}</p>
      <div
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={dropZoneClass}
      >
        <svg className="w-8 h-8 mx-auto text-gray-400 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p className="text-sm text-gray-500">Drag & drop images here, or click to browse</p>
        <input ref={inputRef} type="file" accept="image/*" multiple onChange={handleSelect} className="hidden" disabled={disabled} />
      </div>
      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {files.map((file, i) => (
            <FileThumbnail key={`${file.name}-${i}`} file={file} onRemove={() => onFilesChange(files.filter((_, j) => j !== i))} disabled={disabled} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function UploadInput({ onSubmit, loading, error }: UploadInputProps) {
  const [aerialPhotos, setAerialPhotos] = useState<File[]>([]);
  const [streetviewPhotos, setStreetviewPhotos] = useState<File[]>([]);
  const [address, setAddress] = useState("");

  const canSubmit = !loading && (aerialPhotos.length > 0 || streetviewPhotos.length > 0);

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({ aerialPhotos, streetviewPhotos, address });
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FileDropZone label="Aerial / Satellite Photos" files={aerialPhotos} onFilesChange={setAerialPhotos} disabled={loading} />
        <FileDropZone label="Street View Photos" files={streetviewPhotos} onFilesChange={setStreetviewPhotos} disabled={loading} />
      </div>
      <div>
        <label className="text-sm font-medium text-gray-700 mb-1 block">Address (optional, for report labeling)</label>
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="e.g., 123 Main St, Anytown, USA"
          className="w-full px-4 py-3 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          disabled={loading}
        />
      </div>
      <button
        onClick={handleSubmit}
        disabled={!canSubmit}
        className="w-full px-8 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "Analyzing..." : "Analyze"}
      </button>
      {error && <p className="text-red-600 text-sm">{error}</p>}
    </div>
  );
}
