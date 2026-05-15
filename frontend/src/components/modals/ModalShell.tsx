import type { ReactNode } from "react";

type ModalShellProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
};

export default function ModalShell({ open, title, onClose, children }: ModalShellProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600">
            Kapat
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
