import type { CropBox } from "../../types";
import type { AnswerOption } from "../../types";
import { normalizedRectToDisplayRect } from "../../utils/cropCoordUtils";
import { normalizeContentType } from "../../utils/questionNumbering";
import InlineAnswerBar from "./InlineAnswerBar";

type SelectionWithNumber = {
  id: string;
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key?: string;
  number: number;
  listBadge?: string;
  content_type?: string;
  explanation_caption_enabled?: boolean;
  explanation_caption_text?: string;
  remove_background?: boolean;
  isLocal?: boolean;
  localPdfId?: string;
};

type SelectionOverlayProps = {
  selections: SelectionWithNumber[];
  currentPdfId: string | null;
  currentLocalPdfId: string | null;
  currentPage: number;
  displayedW: number;
  displayedH: number;
  editingSelectionId: string | null;
  choiceCount?: 3 | 4 | 5;
  onStartEdit: (sel: SelectionWithNumber) => void;
  onEndEdit: () => void;
  onAnswerChange: (sel: SelectionWithNumber, answer: AnswerOption | null) => void;
  onDelete: (sel: SelectionWithNumber) => void;
};

export default function SelectionOverlay({
  selections,
  currentPdfId,
  currentLocalPdfId,
  currentPage,
  displayedW,
  displayedH,
  editingSelectionId,
  choiceCount = 5,
  onStartEdit,
  onEndEdit,
  onAnswerChange,
  onDelete,
}: SelectionOverlayProps) {
  const currentSelections = selections.filter(
    (s) =>
      s.page_number === currentPage &&
      ((!s.isLocal && s.pdf_id === currentPdfId) ||
        (s.isLocal && s.localPdfId === currentLocalPdfId))
  );

  const safeW = Math.max(1, displayedW);
  const safeH = Math.max(1, displayedH);

  return (
    <div
      className="pointer-events-none absolute left-0 top-0 z-10 overflow-visible"
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
        const isExplanation = normalizeContentType(sel.content_type) === "explanation";
        const capText =
          sel.explanation_caption_enabled && (sel.explanation_caption_text || "").trim()
            ? (sel.explanation_caption_text || "").trim().slice(0, 28) +
              ((sel.explanation_caption_text || "").trim().length > 28 ? "…" : "")
            : "";
        const topLabel = isExplanation ? capText : `${sel.listBadge ?? sel.number}. Soru`;

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

            {/* Sol üst: X. Soru (kutunun içinde - overflow ile kesilmez) */}
            {isExplanation && !topLabel ? (
              <div
                className="absolute left-0 top-0 z-10 h-6 w-1.5 rounded-br-md rounded-tl-sm bg-teal-700/95 shadow-sm"
                title="Açıklama (metin yok)"
              />
            ) : (
              <div
                className={`absolute left-0 top-0 z-10 max-w-[85%] rounded-br-md rounded-tl-sm px-2 py-0.5 text-xs font-semibold text-white shadow-sm ${
                  isExplanation ? "bg-teal-700/95" : "bg-red-600/95"
                }`}
              >
                {topLabel || `${sel.listBadge ?? sel.number}. Soru`}
              </div>
            )}

            {/* Sağ üst: Düzenle + Soruyu Sil (kutunun üstünde, overflow-visible ile) */}
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

            {/* Sol alt: cevap şeridi — yalnızca soru tipinde */}
            {!isExplanation ? (
              <div className="absolute bottom-0 left-0 z-10 rounded-tr-md rounded-bl-sm bg-red-600/95 px-2 py-0.5 text-xs font-semibold text-white shadow-sm">
                DOĞRU CEVAP: {answerText}
              </div>
            ) : (
              <div className="absolute bottom-0 left-0 z-10 rounded-tr-md rounded-bl-sm bg-teal-800/90 px-2 py-0.5 text-[0.625rem] font-medium text-teal-50 shadow-sm">
                Cevap anahtarı yok
              </div>
            )}

            {/* Düzenle modu: A-E seçimi sorunun altında (dışında) */}
            {isEditing && !isExplanation && (
              <div
                className="absolute left-1/2 top-full z-20 mt-2 -translate-x-1/2 flex items-center gap-1 rounded-lg border border-slate-600 bg-slate-800 p-1.5 shadow-xl pointer-events-auto"
                onClick={(e) => e.stopPropagation()}
              >
                <InlineAnswerBar
                  dark
                  selectedAnswer={currentAnswer}
                  onSelect={(a) => onAnswerChange(sel, a)}
                  onConfirm={onEndEdit}
                  showConfirm={true}
                  bare
                  compact
                  compactSmall
                  choiceCount={choiceCount}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
