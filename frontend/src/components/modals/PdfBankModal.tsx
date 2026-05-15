import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { PdfItem } from "../../types";
import { api } from "../../api/client";

type PdfBankModalProps = {
  open: boolean;
  onClose: () => void;
};

export default function PdfBankModal({ open, onClose }: PdfBankModalProps) {
  const [pdfs, setPdfs] = useState<PdfItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchPdfs = async () => {
    setLoading(true);
    setError(null);
    try {
      const { items } = await api.pdfs.list();
      setPdfs(items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Liste alınamadı");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchPdfs();
  }, [open]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      await api.pdfs.upload(Array.from(files));
      await fetchPdfs();
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Yükleme başarısız");
    } finally {
      setUploading(false);
    }
  };

  const selectForCrop = (pdfId: string, pageNumber: number) => {
    onClose();
    navigate("/crop-tool", { state: { pdfId, pageNumber } });
  };

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 ${open ? "" : "hidden"}`}
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-lg rounded-xl bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">Soru Bankası</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600"
          >
            Kapat
          </button>
        </div>

        <div className="mb-4">
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            onChange={handleUpload}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="w-full rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 py-3 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-100 disabled:opacity-50"
          >
            {uploading ? "Yükleniyor…" : "+ PDF Yükle"}
          </button>
        </div>

        {error && <p className="mb-3 text-sm text-rose-600">{error}</p>}

        <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
          {loading ? (
            <p className="p-4 text-center text-sm text-slate-500">Yükleniyor…</p>
          ) : pdfs.length === 0 ? (
            <p className="p-4 text-center text-sm text-slate-500">Henüz PDF yok. Yükleyin veya mevcut dosyaları kullanın.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {pdfs.map((pdf) => (
                <li key={pdf.id}>
                  <button
                    type="button"
                    onClick={() => setExpandedId(expandedId === pdf.id ? null : pdf.id)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-slate-50"
                  >
                    <span className="truncate font-medium text-slate-800">{pdf.filename}</span>
                    <span className="ml-2 text-xs text-slate-500">{pdf.page_count} sayfa</span>
                  </button>
                  {expandedId === pdf.id && (
                    <div className="border-t border-slate-100 bg-slate-50/50 px-4 py-2">
                      <p className="mb-2 text-xs font-medium text-slate-600">Sayfa seçin:</p>
                      <select
                        defaultValue=""
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          if (n) selectForCrop(pdf.id, n);
                        }}
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
                      >
                        <option value="" disabled>
                          Sayfa seçin…
                        </option>
                        {Array.from({ length: pdf.page_count }, (_, i) => i + 1).map((n) => (
                          <option key={n} value={n}>
                            Sayfa {n}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
