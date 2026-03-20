import { useNavigate } from "react-router-dom";
import { useEditorStore } from "../../store/editorStore";

const actions = [
  { label: "Soru Bankasından Seçin", key: "pdf-bank" as const, style: "from-blue-500 to-blue-600", isRoute: false },
  { label: "Kırpma Aracı", key: "crop-tool" as const, style: "from-orange-500 to-orange-600", isRoute: true },
  { label: "Soru Editörü", key: "question-editor" as const, style: "from-fuchsia-500 to-fuchsia-600", isRoute: false },
  { label: "Taslağı Kaydet", key: "save-draft" as const, style: "from-emerald-500 to-emerald-600", isRoute: false },
  { label: "Taslağı Geri Yükle", key: "load-draft" as const, style: "from-amber-500 to-amber-600", isRoute: false }
];

export default function BottomActionBar() {
  const navigate = useNavigate();
  const setOpenModal = useEditorStore((state) => state.setOpenModal);

  const handleAction = (action: (typeof actions)[0]) => {
    if (action.isRoute) {
      navigate("/crop-tool");
    } else {
      setOpenModal(action.key);
    }
  };

  return (
    <footer className="grid w-full grid-cols-5 gap-3 border-t border-slate-300 bg-slate-100/90 px-5 py-4">
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          onClick={() => handleAction(action)}
          className={`rounded-xl bg-gradient-to-r ${action.style} px-4 py-3 text-sm font-bold text-white shadow-[0_8px_20px_rgba(15,23,42,0.25)] transition hover:-translate-y-0.5 hover:brightness-110`}
        >
          {action.label}
        </button>
      ))}
    </footer>
  );
}
