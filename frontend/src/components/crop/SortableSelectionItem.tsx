import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PdfItem } from "../../types";

type PendingSelection = {
  id: string;
  pdf_id: string;
  page_number: number;
  number: number;
  answer_key?: string;
};

type SortableSelectionItemProps = {
  sel: PendingSelection;
  pdf: PdfItem | undefined;
  onRemove: (sel: PendingSelection) => void;
  onNavigate: (pdfId: string, pageNumber: number) => void;
};

export default function SortableSelectionItem({
  sel,
  pdf,
  onRemove,
  onNavigate,
}: SortableSelectionItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: sel.id });

  const fullText = `${sel.number}. ${pdf?.filename ?? sel.pdf_id} · s.${sel.page_number}${sel.answer_key ? ` · ${sel.answer_key}` : " · ?"}`;

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex cursor-grab items-center justify-between gap-2 rounded border border-slate-600 bg-slate-700/50 p-2 text-xs active:cursor-grabbing ${isDragging ? "opacity-60" : ""}`}
      title={fullText}
      {...attributes}
      {...listeners}
    >
      <button
        type="button"
        onClick={() => onNavigate(sel.pdf_id, sel.page_number)}
        className="min-w-0 flex-1 truncate text-left text-slate-300 hover:text-white hover:underline"
      >
        {sel.number}. {pdf?.filename ?? sel.pdf_id} · s.{sel.page_number}
        {sel.answer_key ? ` · ${sel.answer_key}` : " · ?"}
      </button>
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onRemove(sel);
        }}
        className="shrink-0 text-rose-400 hover:text-rose-300"
      >
        Kaldır
      </button>
    </li>
  );
}
