import { useEffect, useState } from "react";
import type { PdfItem } from "../../types";
import { api } from "../../api/client";
import ConfirmModal from "./ConfirmModal";

type PdfDeleteModalProps = {
  open: boolean;
  onClose: () => void;
  onPdfDeleted?: (deletedId: string) => void;
};

export default function PdfDeleteModal({ open, onClose, onPdfDeleted }: PdfDeleteModalProps) {
  const [pdfs, setPdfs] = useState<PdfItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmPdf, setConfirmPdf] = useState<PdfItem | null>(null);

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

  const doDelete = async (pdf: PdfItem) => {
    setConfirmPdf(null);
    setDeletingId(pdf.id);
    setError(null);
    try {
      await api.pdfs.delete(pdf.id);
      onPdfDeleted?.(pdf.id);
      await fetchPdfs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF silinemedi");
    } finally {
      setDeletingId(null);
    }
  };

  const handleDeleteClick = (pdf: PdfItem) => {
    setConfirmPdf(pdf);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-xl border border-slate-600 bg-slate-800 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="pdf-delete-title"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 id="pdf-delete-title" className="text-base font-semibold text-white">
            PDF Sil
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-500 bg-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-600"
          >
            Kapat
          </button>
        </div>

        {error && (
          <p className="mb-3 text-sm text-rose-400">{error}</p>
        )}

        <div className="max-h-72 overflow-auto rounded-lg border border-slate-600">
          {loading ? (
            <p className="p-4 text-center text-sm text-slate-400">Yükleniyor…</p>
          ) : pdfs.length === 0 ? (
            <p className="p-4 text-center text-sm text-slate-400">
              Henüz PDF yok.
            </p>
          ) : (
            <ul className="divide-y divide-slate-600">
              {pdfs.map((pdf) => (
                <li
                  key={pdf.id}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <span className="truncate text-sm text-slate-300" title={pdf.filename}>
                    {pdf.filename}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleDeleteClick(pdf)}
                    disabled={deletingId === pdf.id}
                    className="shrink-0 rounded border border-rose-600 bg-rose-600/20 px-3 py-1.5 text-xs font-medium text-rose-400 hover:bg-rose-600/40 disabled:opacity-50"
                  >
                    {deletingId === pdf.id ? "Siliniyor…" : "Sil"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <ConfirmModal
          open={!!confirmPdf}
          title="PDF silinsin mi?"
          message={confirmPdf ? `"${confirmPdf.filename}" kalıcı olarak silinecek.` : ""}
          confirmLabel="Sil"
          cancelLabel="Vazgeç"
          variant="danger"
          onConfirm={() => confirmPdf && doDelete(confirmPdf)}
          onCancel={() => setConfirmPdf(null)}
        />
      </div>
    </div>
  );
}
