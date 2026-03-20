import { useState } from "react";
import { api } from "../../api/client";
import { useEditorStore } from "../../store/editorStore";

type SaveDraftModalProps = {
  open: boolean;
  onClose: () => void;
};

export default function SaveDraftModal({ open, onClose }: SaveDraftModalProps) {
  const questions = useEditorStore((s) => s.questions);
  const testName = useEditorStore((s) => s.testName);
  const schoolName = useEditorStore((s) => s.schoolName);
  const options = useEditorStore((s) => s.options);
  const [name, setName] = useState(testName || "");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    const draftName = name.trim() || `taslak-${Date.now()}`;
    setSaving(true);
    setError(null);
    try {
      await api.drafts.save({
        name: draftName,
        questions,
        notes: notes.trim() || undefined,
        test_info: { test_title: testName, school_name: schoolName },
        export_settings: { include_answer_key: options.includeAnswerKey, add_spacing: options.addSpacingBetweenQuestions },
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kaydetme başarısız");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={onClose} role="presentation">
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} role="presentation">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">Taslağı Kaydet</h3>
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600">
            Kapat
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Taslak adı</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Taslak adı girin"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Not (isteğe bağlı)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Not ekleyin"
              rows={2}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <p className="text-xs text-slate-500">{questions.length} soru kaydedilecek.</p>
        </div>

        {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}

        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700">
            İptal
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || questions.length === 0}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? "Kaydediliyor…" : "Kaydet"}
          </button>
        </div>
      </div>
    </div>
  );
}
