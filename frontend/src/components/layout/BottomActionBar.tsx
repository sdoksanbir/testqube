import { useNavigate } from "react-router-dom";
import { useEditorStore } from "../../store/editorStore";

type ActionItem =
  | { label: string; key: "crop-tool"; style: string; isRoute: true }
  | { label: string; key: "pdf-bank" | "question-editor" | "save-draft" | "load-draft"; style: string; isRoute: false };

const actions = [
  { label: "Soru Bankasından Seçin", key: "pdf-bank" as const, style: "from-blue-500 to-blue-600", isRoute: false },
  { label: "Kırpma Aracı", key: "crop-tool" as const, style: "from-orange-500 to-orange-600", isRoute: true },
  { label: "Soru Editörü", key: "question-editor" as const, style: "from-fuchsia-500 to-fuchsia-600", isRoute: false },
  { label: "Taslağı Kaydet", key: "save-draft" as const, style: "from-emerald-500 to-emerald-600", isRoute: false },
  { label: "Taslağı Geri Yükle", key: "load-draft" as const, style: "from-amber-500 to-amber-600", isRoute: false },
] as const satisfies ReadonlyArray<ActionItem>;

export default function BottomActionBar() {
  const navigate = useNavigate();
  const setOpenModal = useEditorStore((state) => state.setOpenModal);

  const handleAction = (action: ActionItem) => {
    if (action.isRoute) {
      navigate("/crop-tool");
    } else {
      setOpenModal(action.key);
    }
  };

  return (
    <footer
      className="grid w-full min-w-0 shrink-0 grid-cols-5 gap-2.5 border-t border-slate-300 bg-slate-100/90 px-4 py-3"
      role="navigation"
      aria-label="Hızlı işlemler"
    >
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          onClick={() => handleAction(action)}
          className={`min-w-0 rounded-xl bg-gradient-to-r ${action.style} px-3 py-2.5 text-sm font-semibold text-white shadow-[0_6px_16px_rgba(15,23,42,0.2)] transition hover:-translate-y-0.5 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2`}
        >
          {action.label}
        </button>
      ))}
    </footer>
  );
}
