import Sidebar from "./Sidebar";
import QuestionCanvas from "../editor/QuestionCanvas";
import BottomActionBar from "./BottomActionBar";
import PdfBankModal from "../modals/PdfBankModal";
import QuestionEditorModal from "../modals/QuestionEditorModal";
import SaveDraftModal from "../modals/SaveDraftModal";
import LoadDraftModal from "../modals/LoadDraftModal";
import { useEditorStore } from "../../store/editorStore";

export default function AppShell() {
  const openModal = useEditorStore((state) => state.openModal);

  return (
    <div className="h-screen w-screen overflow-hidden bg-white">
      <div className="flex h-full flex-col">
        <div className="flex min-h-0 flex-1 bg-slate-100">
          <Sidebar />
          <main className="min-h-0 flex-1 bg-gradient-to-br from-slate-100 via-slate-50 to-slate-200 p-6">
            <QuestionCanvas />
          </main>
        </div>
        <BottomActionBar />
      </div>

      <PdfBankModal open={openModal === "pdf-bank"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <QuestionEditorModal open={openModal === "question-editor"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <SaveDraftModal open={openModal === "save-draft"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <LoadDraftModal open={openModal === "load-draft"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
    </div>
  );
}
