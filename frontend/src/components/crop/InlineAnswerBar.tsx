import type { AnswerOption } from "../../types";

const OPTIONS: AnswerOption[] = ["A", "B", "C", "D", "E"];

type InlineAnswerBarProps = {
  selectedAnswer: AnswerOption | null;
  onSelect: (answer: AnswerOption | null) => void;
  onConfirm: () => void;
  /** Tamam butonu göster */
  showConfirm?: boolean;
  /** İptal butonu (yeni seçim akışında) */
  onCancel?: () => void;
  /** Sadece butonları render et (overlay için kendi container kullanılır) */
  bare?: boolean;
  /** Karanlık mod (crop workspace ile uyumlu) */
  dark?: boolean;
};

export default function InlineAnswerBar({
  selectedAnswer,
  onSelect,
  onConfirm,
  showConfirm = true,
  onCancel,
  bare = false,
  dark = false,
}: InlineAnswerBarProps) {
  const content = (
    <>
      {OPTIONS.map((letter) => (
        <button
          key={letter}
          type="button"
          onClick={() => onSelect(selectedAnswer === letter ? null : letter)}
          className={`flex h-9 w-9 items-center justify-center rounded-lg border text-sm font-bold transition ${
            selectedAnswer === letter
              ? "border-blue-600 bg-blue-600 text-white"
              : dark
                ? "border-slate-500 bg-slate-700 text-slate-200 hover:bg-slate-600 hover:border-slate-400"
                : "border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200"
          }`}
        >
          {letter}
        </button>
      ))}
      {showConfirm && (
        <button
          type="button"
          onClick={onConfirm}
          className="ml-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
        >
          Tamam
        </button>
      )}
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className={
            dark
              ? "rounded-lg border border-slate-500 bg-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-600"
              : "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
          }
        >
          İptal
        </button>
      )}
    </>
  );

  if (bare) return content;

  return (
    <div
      className={
        dark
          ? "flex items-center gap-2 rounded-xl border border-slate-600 bg-slate-800 px-3 py-2 shadow-lg"
          : "flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-lg"
      }
    >
      {content}
    </div>
  );
}
