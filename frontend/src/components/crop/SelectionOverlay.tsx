import type { CropBox } from "../../types";
import type { AnswerOption } from "../../types";
import { normalizedRectToDisplayRect } from "../../utils/cropCoordUtils";
import InlineAnswerBar from "./InlineAnswerBar";

type SelectionWithNumber = {
  id: string;
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key?: string;
  number: number;
};

type SelectionOverlayProps = {
  selections: SelectionWithNumber[];
  currentPdfId: string | null;
  currentPage: number;
  displayedW: number;
  displayedH: number;
  editingSelectionId: string | null;
  onStartEdit: (sel: SelectionWithNumber) => void;
  onEndEdit: () => void;
  onAnswerChange: (sel: SelectionWithNumber, answer: AnswerOption | null) => void;
  onDelete: (sel: SelectionWithNumber) => void;
};

export default function SelectionOverlay({
  selections,
  currentPdfId,
  currentPage,
  displayedW,
  displayedH,
  editingSelectionId,
  onStartEdit,
  onEndEdit,
  onAnswerChange,
  onDelete,
}: SelectionOverlayProps) {
  const currentSelections = selections.filter(
    (s) => s.pdf_id === currentPdfId && s.page_number === currentPage
  );

  const safeW = Math.max(1, displayedW);
  const safeH = Math.max(1, displayedH);

  return (
    <div
      className="pointer-events-none absolute left-0 top-0 overflow-visible"
      style={{ width: safeW, height: safeH }}
    >
      {currentSelections.map((sel) => {
        const rect = normalizedRectToDisplayRect(
          sel.crop as { x: number; y: number; width: number; height: number },
          safeW,
          safeH
        );
        if (rect.width <= 0 || rect.height <= 0) return null;

        const currentAnswer: AnswerOption | null =
          sel.answer_key && ["A", "B", "C", "D", "E"].includes(sel.answer_key)
            ? (sel.answer_key as AnswerOption)
            : null;
        const answerText = currentAnswer ?? "?";
        const isEditing = editingSelectionId === sel.id;

        return (
          <div
            key={sel.id}
            className={`absolute overflow-visible ${isEditing ? "pointer-events-none" : "pointer-events-auto"}`}
            style={{
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height,
            }}
          >
            {/* Kırmızı 1px kenarlık (referans görsel) */}
            <div
              className="absolute inset-0 rounded-sm"
              style={{
                border: "1px solid #dc2626",
                boxSizing: "border-box",
              }}
            />

            {/* Sol üst: X. Soru (kırmızı etiket, üst kenarın hemen üstünde) */}
            <div
              className="absolute left-0 z-10 -translate-y-full rounded-md bg-red-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm"
              style={{ top: 0, marginTop: -2 }}
            >
              {sel.number}. Soru
            </div>

            {/* Sağ üst: Düzenle + Soruyu Sil (mavi butonlar, üst kenarın hemen üstünde) */}
            <div
              className="absolute right-0 z-10 flex -translate-y-full gap-1.5 pointer-events-auto"
              style={{ top: 0, marginTop: -2 }}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onStartEdit(sel);
                }}
                className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-blue-500"
              >
                Düzenle
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(sel);
                }}
                className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-blue-500 pointer-events-auto"
              >
                Soruyu Sil
              </button>
            </div>

            {/* Sol alt: DOĞRU CEVAP: X (kırmızı etiket, alt kenarın hemen altında) */}
            <div
              className="absolute bottom-0 left-0 z-10 translate-y-full rounded-md bg-red-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm"
              style={{ marginTop: 2 }}
            >
              DOĞRU CEVAP: {answerText}
            </div>

            {/* Düzenle modu: A-E seçimi popover + seçim alanı ReactCrop ile yeniden boyutlandırılabilir */}
            {isEditing && (
              <div
                className="absolute right-0 top-0 z-20 mt-6 rounded-lg border border-slate-600 bg-slate-800 p-2 shadow-xl pointer-events-auto"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center gap-1">
                  <InlineAnswerBar
                    dark
                    selectedAnswer={currentAnswer}
                    onSelect={(a) => onAnswerChange(sel, a)}
                    onConfirm={onEndEdit}
                    showConfirm={true}
                    bare
                  />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
