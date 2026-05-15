import { useEffect } from "react";
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
  const isDirty = useEditorStore((state) => state.isDirty);

  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  return (
    <div className="flex h-[100dvh] min-h-0 w-full min-w-0 flex-col overflow-hidden bg-white">
      <div className="flex min-h-0 min-w-0 flex-1 bg-slate-100">
        <Sidebar />
        <main
          className="min-h-0 min-w-0 flex-1 overflow-hidden bg-gradient-to-br from-slate-100 via-slate-50 to-slate-200"
          style={{ padding: "var(--tq-main-padding)" }}
        >
          <QuestionCanvas />
        </main>
      </div>
      <BottomActionBar />

      <PdfBankModal open={openModal === "pdf-bank"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <QuestionEditorModal open={openModal === "question-editor"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <SaveDraftModal open={openModal === "save-draft"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
      <LoadDraftModal open={openModal === "load-draft"} onClose={() => useEditorStore.getState().setOpenModal(null)} />
    </div>
  );
}
