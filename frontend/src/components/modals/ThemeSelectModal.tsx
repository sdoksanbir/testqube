import { useEffect, useState } from "react";

type StyleId = "style1" | "style2" | "style3";

const STYLES: { id: StyleId; label: string }[] = [
  { id: "style1", label: "Style 1" },
  { id: "style2", label: "Style 2" },
  { id: "style3", label: "Style 3" },
];

const THEME_COLORS = [
  "#f08c2e",
  "#2fa7d8",
  "#1da466",
  "#a78cc4",
  "#e8cbbf",
  "#f2e316",
  "#b7d7e6",
  "#f34a2f",
  "#bfbfbf",
];

type Props = {
  open: boolean;
  onClose: () => void;
  onConfirm: (styleId: StyleId, themeColor: string) => void;
  currentStyleId: string;
  currentColor: string;
  useDescriptionBox: boolean;
};

export default function ThemeSelectModal({
  open,
  onClose,
  onConfirm,
  currentStyleId,
  currentColor,
  useDescriptionBox,
}: Props) {
  const [styleId, setStyleId] = useState<StyleId>(
    (currentStyleId as StyleId) || "style3"
  );
  const [color, setColor] = useState(currentColor || "#1E88E5");

  useEffect(() => {
    if (open) {
      setStyleId((currentStyleId as StyleId) || "style3");
      setColor(currentColor || "#1E88E5");
    }
  }, [open, currentStyleId, currentColor]);

  if (!open) return null;

  const handleApply = () => {
    onConfirm(styleId, color);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl bg-slate-800 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-base font-bold text-slate-100">
          Tema / Başlık Tasarımı Seç
        </h3>

        <div className="mb-4">
          <h4 className="mb-2 text-sm font-semibold text-slate-300">Başlık Tasarımı</h4>
          <div className="grid grid-cols-3 gap-3">
            {STYLES.map((s) => (
              <label
                key={s.id}
                className="flex cursor-pointer items-center justify-center rounded-lg border-2 px-3 py-2 text-sm transition"
                style={{
                  borderColor: styleId === s.id ? color : "transparent",
                  backgroundColor: styleId === s.id ? `${color}20` : "rgb(51 65 85)",
                }}
              >
                <input
                  type="radio"
                  name="style"
                  checked={styleId === s.id}
                  onChange={() => setStyleId(s.id)}
                  className="sr-only"
                />
                <span className="text-slate-200">
                  {s.label} ({useDescriptionBox ? "Açıklamalı" : "Açıklamasız"})
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="mb-4">
          <h4 className="mb-2 text-sm font-semibold text-slate-300">Tema Rengi (Canlı)</h4>
          <div className="flex flex-wrap gap-2">
            {THEME_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                className="h-6 w-8 rounded-md border-2 transition"
                style={{
                  backgroundColor: c,
                  borderColor: color === c ? "white" : "transparent",
                }}
                aria-label={`Renk ${c}`}
              />
            ))}
            <label className="flex items-center gap-1 text-sm text-slate-400">
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="h-6 w-8 cursor-pointer rounded border-0 bg-transparent p-0"
              />
              Renk Seç…
            </label>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-slate-600 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-500"
          >
            İptal
          </button>
          <button
            type="button"
            onClick={handleApply}
            className="rounded-lg px-4 py-2 text-sm font-bold text-white"
            style={{ backgroundColor: color }}
          >
            Uygula
          </button>
        </div>
      </div>
    </div>
  );
}
