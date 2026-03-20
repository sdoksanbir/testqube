import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";
import type { QuestionItem } from "../../types";
import { api } from "../../api/client";
import { useEditorStore } from "../../store/editorStore";
import QuestionAnswerChips from "./QuestionAnswerChips";

type QuestionCardProps = {
  question: QuestionItem;
};

export default function QuestionCard({ question }: QuestionCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: question.id });
  const removeQuestion = useEditorStore((state) => state.removeQuestion);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  return (
    <>
      <article
        ref={setNodeRef}
        style={{ transform: CSS.Transform.toString(transform), transition }}
        className={`group relative cursor-grab rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_10px_28px_rgba(15,23,42,0.15)] active:cursor-grabbing ${isDragging ? "opacity-60" : "opacity-100"}`}
        {...attributes}
        {...listeners}
      >
        <div className="mb-1.5 flex items-center justify-between">
          <span className="rounded-md bg-orange-500/90 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow-sm">
            Soru {question.order_index + 1}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                setIsPreviewOpen(true);
              }}
              className="grid h-5 w-5 place-items-center rounded border border-orange-300/80 bg-orange-50 text-orange-700 transition hover:bg-orange-100 hover:border-orange-400"
              aria-label="Soruyu büyüt"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
            </button>
            <button
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                removeQuestion(question.id);
              }}
              className="grid h-5 w-5 place-items-center rounded border border-rose-300/80 bg-rose-50 text-rose-600 transition hover:bg-rose-100 hover:border-rose-400"
              aria-label="Soruyu sil"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </div>
        </div>

        <img src={api.questions.imageUrl(question.id)} alt={`Soru ${question.order_index + 1}`} className="block h-28 w-full rounded-t-xl object-cover" />
        <div className="rounded-b-xl border border-orange-200/80 bg-orange-50/90 px-2 py-0.5 shadow-inner">
          <QuestionAnswerChips questionId={question.id} selected={(question.answer_key || undefined) as import("../../store/editorStore").AnswerOption} />
        </div>
      </article>

      {isPreviewOpen ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-slate-900/70 p-6"
          onClick={() => setIsPreviewOpen(false)}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Escape") setIsPreviewOpen(false);
          }}
        >
          <div
            className="w-full max-w-4xl rounded-2xl bg-white p-4 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
            role="presentation"
          >
            <div className="mb-3 flex items-center justify-between">
              <strong className="text-slate-900">Soru {question.order_index + 1} - Önizleme</strong>
              <button
                type="button"
                onClick={() => setIsPreviewOpen(false)}
                className="rounded-md border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700"
              >
                Kapat
              </button>
            </div>
            <img src={api.questions.imageUrl(question.id)} alt={`Soru ${question.order_index + 1} büyük görünüm`} className="max-h-[70vh] w-full rounded-xl object-contain" />
          </div>
        </div>
      ) : null}
    </>
  );
}
