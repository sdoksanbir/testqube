import { useState } from "react";
import { useEditorStore } from "../../store/editorStore";
import type { DraftFilePayload } from "../../store/editorStore";

type SaveDraftModalProps = {
  open: boolean;
  onClose: () => void;
};

/**
 * Taslağı Kaydet: TEK explicit persistence noktası.
 * Working draft → kalıcı kayıt (dosya indirme).
 * "Seçimleri Kaydet" bu modal'ı tetiklemez.
 */
export default function SaveDraftModal({ open, onClose }: SaveDraftModalProps) {
  const questions = useEditorStore((s) => s.questions);
  const testName = useEditorStore((s) => s.testName);
  const schoolName = useEditorStore((s) => s.schoolName);
  const options = useEditorStore((s) => s.options);
  const questionGapMm = useEditorStore((s) => s.questionGapMm);
  const questionGapMinMm = useEditorStore((s) => s.questionGapMinMm);
  const autoCompactSpacing = useEditorStore((s) => s.autoCompactSpacing);
  const headerStyleId = useEditorStore((s) => s.headerStyleId);
  const themeColor = useEditorStore((s) => s.themeColor);
  const sections = useEditorStore((s) => s.sections);
  const descriptionColumnCount = useEditorStore((s) => s.descriptionColumnCount);
  const descriptionTexts = useEditorStore((s) => s.descriptionTexts);
  const descriptionColumnDividers = useEditorStore((s) => s.descriptionColumnDividers);
  const answerKeyMode = useEditorStore((s) => s.answerKeyMode);
  const centerLineText = useEditorStore((s) => s.centerLineText);
  const centerLineBold = useEditorStore((s) => s.centerLineBold);
  const centerLineItalic = useEditorStore((s) => s.centerLineItalic);
  const centerLineTextDirection = useEditorStore((s) => s.centerLineTextDirection);
  const examType = useEditorStore((s) => s.examType);
  const classSection = useEditorStore((s) => s.classSection);
  const group = useEditorStore((s) => s.group);
  const writtenPaperOptions = useEditorStore((s) => s.writtenPaperOptions);
  const writtenHeaderFieldLines = useEditorStore((s) => s.writtenHeaderFieldLines);
  const writtenHeaderFieldLabels = useEditorStore((s) => s.writtenHeaderFieldLabels);
  const writtenHeaderFieldHidden = useEditorStore((s) => s.writtenHeaderFieldHidden);
  const customExamTypes = useEditorStore((s) => s.customExamTypes);
  const marginTopMm = useEditorStore((s) => s.marginTopMm);
  const marginBottomMm = useEditorStore((s) => s.marginBottomMm);
  const marginLeftMm = useEditorStore((s) => s.marginLeftMm);
  const marginRightMm = useEditorStore((s) => s.marginRightMm);
  const teacherNames = useEditorStore((s) => s.teacherNames);
  const principalName = useEditorStore((s) => s.principalName);
  const setDirty = useEditorStore((s) => s.setDirty);
  const setPersistedDraftName = useEditorStore((s) => s.setPersistedDraftName);
  const [name, setName] = useState(testName || "");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    const draftName = name.trim() || `taslak-${Date.now()}`;
    const safeName = draftName.replace(/\s+/g, "-");
    setSaving(true);
    setError(null);
    try {
      const payload: DraftFilePayload = {
        name: draftName,
        questions,
        notes: notes.trim() || undefined,
        test_info: { test_title: testName, school_name: schoolName },
        export_settings: {
          include_answer_key: options.includeAnswerKey,
          add_spacing: options.addSpacingBetweenQuestions,
          include_description: options.includeDescription,
          add_text_on_line: options.addTextOnLine,
        },
        editor_state: {
          testName,
          schoolName,
          options: { ...options },
          questionGapMm,
          questionGapMinMm,
          autoCompactSpacing,
          headerStyleId,
          themeColor,
          sections: sections.length > 0 ? sections : undefined,
          descriptionColumnCount,
          descriptionTexts,
          descriptionColumnDividers,
          answerKeyMode,
          centerLineText,
          centerLineBold,
          centerLineItalic,
          centerLineTextDirection,
          examType,
          classSection,
          group,
          writtenPaperOptions: { ...writtenPaperOptions },
          teacherNames: teacherNames.length > 0 ? [...teacherNames] : undefined,
          principalName: principalName.trim() || undefined,
          writtenHeaderFieldLines: { ...writtenHeaderFieldLines },
          writtenHeaderFieldLabels: { ...writtenHeaderFieldLabels },
          writtenHeaderFieldHidden: { ...writtenHeaderFieldHidden },
          customExamTypes: customExamTypes.length > 0 ? customExamTypes : undefined,
          marginTopMm,
          marginBottomMm,
          marginLeftMm,
          marginRightMm,
        },
      };
      const content = JSON.stringify(payload, null, 2);

      // File System Access API: Konum seçerek kaydet (Chrome, Edge)
      if ("showSaveFilePicker" in window) {
        const handle = await (window as any).showSaveFilePicker({
          suggestedName: `${safeName}.testqube`,
          types: [
            {
              description: "TestQube Taslak",
              accept: { "application/json": [".testqube"] },
            },
          ],
        });
        const writable = await handle.createWritable();
        await writable.write(content);
        await writable.close();
      } else {
        // Fallback: İndirme (eski tarayıcılar)
        const blob = new Blob([content], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeName}.testqube`;
        a.click();
        URL.revokeObjectURL(url);
      }

      setDirty(false);
      setPersistedDraftName(draftName);
      onClose();
    } catch (e) {
      if ((e as Error).name === "AbortError") return; // Kullanıcı iptal etti
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
          <p className="text-xs text-slate-500">
            {questions.length} soru kaydedilecek. Kaydet’e tıklayınca konum ve dosya adı seçebileceğiniz pencere açılır.
          </p>
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
