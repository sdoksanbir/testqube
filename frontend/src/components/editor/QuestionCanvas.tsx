import { useEffect } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import { SortableContext, rectSortingStrategy } from "@dnd-kit/sortable";
import QuestionGrid from "./QuestionGrid";
import { useEditorStore } from "../../store/editorStore";

export default function QuestionCanvas() {
  const questions = useEditorStore((state) => state.questions);
  const fetchQuestions = useEditorStore((state) => state.fetchQuestions);
  const reorderQuestions = useEditorStore((state) => state.reorderQuestions);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = questions.findIndex((q) => q.id === active.id);
    const to = questions.findIndex((q) => q.id === over.id);
    if (from < 0 || to < 0 || from === to) return;
    const next = [...questions];
    const [removed] = next.splice(from, 1);
    next.splice(to, 0, removed);
    reorderQuestions(next.map((q) => q.id));
  };

  return (
    <section className="flex h-full flex-col rounded-2xl border border-slate-300 bg-white/90 p-4 shadow-[0_8px_30px_rgba(15,23,42,0.08)]">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-base font-bold tracking-tight text-slate-800">Seçilen Sorular</h2>
        <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-semibold text-blue-700">Sürükle-bırak ile sıralama</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto rounded-2xl border border-dashed border-slate-300 bg-gradient-to-br from-slate-100 to-slate-200 p-4">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={questions.map((q) => q.id) as string[]} strategy={rectSortingStrategy}>
            <QuestionGrid questions={questions} />
          </SortableContext>
        </DndContext>
      </div>
    </section>
  );
}
