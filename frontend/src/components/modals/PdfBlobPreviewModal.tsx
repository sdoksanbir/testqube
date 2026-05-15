/**
 * PDF blob önizleme modalı – Yazılı Kağıdı için.
 * Blob hazır olunca gösterir, Kaydet ile indirir.
 */
import { useEffect, useMemo } from "react";

type PdfBlobPreviewModalProps = {
  isOpen: boolean;
  onClose: () => void;
  blob: Blob | null;
  loading: boolean;
  suggestedFileName?: string;
};

export default function PdfBlobPreviewModal({
  isOpen,
  onClose,
  blob,
  loading,
  suggestedFileName = "yazili.pdf",
}: PdfBlobPreviewModalProps) {
  const objectUrl = useMemo(
    () => (blob && isOpen ? URL.createObjectURL(blob) : null),
    [blob, isOpen]
  );

  useEffect(() => {
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  const handleSave = () => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const base = (suggestedFileName || "").replace(/\.pdf$/i, "").trim() || `yazili-${Date.now()}`;
    a.download = `${base}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-slate-900"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pdf-blob-preview-title"
    >
      {/* Üst bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-700 bg-slate-800 px-4 py-3">
        <h2 id="pdf-blob-preview-title" className="text-base font-bold text-slate-100">
          PDF Önizleme
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleSave}
            disabled={!blob || loading}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            PDF&apos;yi Kaydet
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-600"
          >
            Kapat
          </button>
        </div>
      </div>

      {/* İçerik */}
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <p className="text-slate-400">PDF hazırlanıyor…</p>
          </div>
        ) : objectUrl ? (
          <iframe
            src={objectUrl}
            title="PDF önizleme"
            className="mx-auto h-full min-h-[70vh] w-full max-w-4xl rounded-lg border border-slate-600 bg-white"
          />
        ) : (
          <div className="flex h-64 items-center justify-center">
            <p className="text-slate-400">PDF yüklenemedi</p>
          </div>
        )}
      </div>
    </div>
  );
}
