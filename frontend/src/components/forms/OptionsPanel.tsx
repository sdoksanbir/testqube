import { useEditorStore } from "../../store/editorStore";

const optionItems = [
  { key: "includeDescription" as const, label: "Test ile ilgili açıklama ekle" },
  { key: "addSpacingBetweenQuestions" as const, label: "Sorular arasına boşluk ekle" },
  { key: "includeAnswerKey" as const, label: "Teste cevap anahtarı ekle" },
  { key: "addTextOnLine" as const, label: "Çizgi üzerine yazı ekle" }
];

export default function OptionsPanel() {
  const options = useEditorStore((state) => state.options);
  const toggleOption = useEditorStore((state) => state.toggleOption);

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-200">Seçenekler</h3>
      <div className="space-y-2 rounded-lg border border-slate-700 bg-slate-800/60 p-3">
        {optionItems.map((item) => (
          <label key={item.key} className="flex items-center gap-2 text-sm text-slate-200">
            <input type="checkbox" checked={options[item.key]} onChange={() => toggleOption(item.key)} className="h-4 w-4" />
            {item.label}
          </label>
        ))}
      </div>
    </section>
  );
}
