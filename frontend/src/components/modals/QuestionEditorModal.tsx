import ModalShell from "./ModalShell";

type QuestionEditorModalProps = {
  open: boolean;
  onClose: () => void;
};

export default function QuestionEditorModal({ open, onClose }: QuestionEditorModalProps) {
  return (
    <ModalShell open={open} onClose={onClose} title="Soru Editoru">
      <p className="text-sm text-slate-600">Soru metni ve secenek duzenleme arayuzu burada acilacak.</p>
    </ModalShell>
  );
}
