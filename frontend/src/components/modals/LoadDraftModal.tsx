import { useEffect, useRef, useState } from "react";
import type { DraftInfo } from "../../types";
import { api } from "../../api/client";
import { useEditorStore } from "../../store/editorStore";
import type { DraftFilePayload } from "../../store/editorStore";

type LoadDraftModalProps = {
  open: boolean;
  onClose: () => void;
};

export default function LoadDraftModal({ open, onClose }: LoadDraftModalProps) {
  const [drafts, setDrafts] = useState<DraftInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const applyDraftPayload = useEditorStore((s) => s.applyDraftPayload);

  const fetchDrafts = async () => {
    setLoading(true);
    setError(null);
    try {
      const { items } = await api.drafts.list();
      setDrafts(items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Taslaklar yüklenemedi");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchDrafts();
  }, [open]);

  const handleLoad = async (draftName: string) => {
    setError(null);
    try {
      const draft = await api.drafts.load(draftName);
      const payload: DraftFilePayload = {
        name: draft.name ?? draftName,
        questions: draft.questions,
        notes: draft.notes,
        test_info: draft.test_info,
        export_settings: draft.export_settings as DraftFilePayload["export_settings"],
        editor_state: (draft as DraftFilePayload).editor_state,
      };
      applyDraftPayload(payload);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Taslak yüklenemedi");
    }
  };

  const handleLoadFromFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const draft = JSON.parse(reader.result as string);
        if (draft.questions && Array.isArray(draft.questions)) {
          const payload: DraftFilePayload = {
            name: draft.name ?? "Yüklü Taslak",
            questions: draft.questions,
            notes: draft.notes,
            test_info: draft.test_info,
            export_settings: draft.export_settings,
            editor_state: draft.editor_state,
          };
          applyDraftPayload(payload);
          onClose();
        } else {
          setError("Geçersiz taslak dosyası");
        }
      } catch {
        setError("Dosya okunamadı");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={onClose} role="presentation">
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} role="presentation">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">Taslağı Geri Yükle</h3>
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600">
            Kapat
          </button>
        </div>

        {error && <p className="mb-3 text-sm text-rose-600">{error}</p>}

        <div className="mb-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".testqube,.json"
            className="hidden"
            onChange={handleLoadFromFile}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="w-full rounded-lg border border-emerald-500 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
          >
            Bilgisayardan dosya seç (.testqube)
          </button>
        </div>

        <div className="max-h-48 overflow-auto rounded-lg border border-slate-200">
          {loading ? (
            <p className="p-4 text-center text-sm text-slate-500">Yükleniyor…</p>
          ) : drafts.length === 0 ? (
            <p className="p-4 text-center text-sm text-slate-500">Kayıtlı taslak bulunamadı.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {drafts.map((d) => (
                <li key={d.name}>
                  <button
                    type="button"
                    onClick={() => handleLoad(d.name)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-slate-50"
                  >
                    <span className="font-medium text-slate-800">{d.name}</span>
                    <span className="text-xs text-slate-500">
                      {new Date(d.updated_at).toLocaleDateString("tr-TR")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
