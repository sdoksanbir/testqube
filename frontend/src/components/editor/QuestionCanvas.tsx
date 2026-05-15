import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, rectSortingStrategy } from "@dnd-kit/sortable";
import QuestionGrid from "./QuestionGrid";
import QuestionCardContent from "./QuestionCardContent";
import { useEditorStore } from "../../store/editorStore";
import { buildQuestionNumberMap, normalizeContentType } from "../../utils/questionNumbering";

export default function QuestionCanvas() {
  const navigate = useNavigate();
  const questions = useEditorStore((state) => state.questions);
  const sections = useEditorStore((state) => state.sections);
  const fetchQuestions = useEditorStore((state) => state.fetchQuestions);
  const reorderQuestions = useEditorStore((state) => state.reorderQuestions);
  const numberById = useMemo(() => buildQuestionNumberMap(questions, sections), [questions, sections]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [lastOverId, setLastOverId] = useState<string | null>(null);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 3 } }));

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(String(event.active.id));
    setLastOverId(null);
  };

  const handleDragOver = (event: DragOverEvent) => {
    if (event.over) setLastOverId(String(event.over.id));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    const overId = over ? String(over.id) : lastOverId;
    setActiveId(null);
    setLastOverId(null);
    if (!overId || String(active.id) === overId) return;
    const ids = questions.map((q) => q.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(overId);
    if (from < 0 || to < 0 || from === to) return;
    reorderQuestions(arrayMove(ids, from, to));
  };

  const activeQuestion = activeId ? questions.find((q) => q.id === activeId) : null;
  const isEmpty = questions.length === 0;

  return (
    <section className="tq-canvas-shell h-full min-h-0 min-w-0">
      <div
        className="mb-0 flex min-w-0 flex-shrink-0 flex-wrap items-center justify-between gap-2"
        style={{ marginBottom: "var(--tq-space-2)" }}
      >
        <h2 className="tq-main-section-title">Seçilen Sorular</h2>
        {!isEmpty && (
          <span className="tq-main-pill rounded-full bg-slate-100 px-2.5 py-1 text-slate-600 ring-1 ring-slate-200/80">
            Sürükle-bırak ile sıralama
          </span>
        )}
      </div>

      <div className="tq-canvas-scroll shadow-inner">
        {isEmpty ? (
          <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-gradient-to-br from-slate-50 via-orange-50/30 to-slate-100">
            <div className="mb-6 rounded-2xl bg-gradient-to-br from-orange-100 to-orange-200/80 p-6 shadow-lg" aria-hidden>
              <svg
                width="64"
                height="64"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-orange-600"
              >
                <rect x="3" y="3" width="18" height="18" rx="2" strokeDasharray="3 2" />
                <path d="M8 8h8" />
                <path d="M8 12h8" />
                <path d="M8 16h4" />
              </svg>
            </div>
            <h3 className="mb-2 text-base font-semibold text-slate-800">Henüz soru seçilmedi</h3>
            <p className="mb-6 max-w-md text-center text-base leading-relaxed text-slate-600">
              Kırpma Aracı ile PDF&apos;den soru alanlarını seçin. Seçtiğiniz sorular otomatik olarak buraya eklenecek.
            </p>
            <button
              type="button"
              onClick={() => navigate("/crop-tool")}
              className="rounded-xl bg-gradient-to-r from-orange-500 to-orange-600 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-orange-500/30 transition hover:from-orange-600 hover:to-orange-700 hover:shadow-orange-500/40"
            >
              Kırpma Aracına Git
            </button>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={pointerWithin}
            onDragStart={handleDragStart}
            onDragOver={handleDragOver}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={questions.map((q) => q.id)} strategy={rectSortingStrategy}>
              <QuestionGrid questions={questions} />
            </SortableContext>
            <DragOverlay dropAnimation={null}>
              {activeQuestion ? (
                <div className="cursor-grabbing opacity-95 shadow-xl">
                  <QuestionCardContent
                    question={activeQuestion}
                    hideActions
                    displayNumber={numberById.get(activeQuestion.id) ?? null}
                    isExplanation={normalizeContentType(activeQuestion.content_type) === "explanation"}
                  />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
        )}
      </div>
    </section>
  );
}
