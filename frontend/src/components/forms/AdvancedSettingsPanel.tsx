const colorSwatches = [
  "#f08c2e",
  "#2fa7d8",
  "#1da466",
  "#a78cc4",
  "#e8cbbf",
  "#f2e316",
  "#b7d7e6",
  "#f34a2f",
  "#bfbfbf"
];

export default function AdvancedSettingsPanel() {
  return (
    <section className="space-y-5 text-slate-100">
      <h3 className="text-sm font-semibold text-slate-200">Gelişmiş Ayarlar</h3>

      <label className="flex items-center gap-2 text-sm text-slate-200">
        <input type="checkbox" className="h-4 w-4" />
        Akıllı soru yerleşimi uygula
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-200">
        <input type="checkbox" className="h-4 w-4" />
        Filigran ekle
      </label>

      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-slate-200">Sayfa tasarım rengi belirle:</h4>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-300">Renk:</span>
          {colorSwatches.map((color) => (
            <button
              key={color}
              type="button"
              className="grid h-6 w-6 place-items-center rounded border border-slate-500"
              style={{ backgroundColor: color }}
              aria-label={`Renk ${color}`}
            />
          ))}
          <button type="button" className="grid h-6 w-6 place-items-center rounded border border-slate-500 bg-slate-700 text-sm font-bold text-white">
            +
          </button>
        </div>
      </div>

      <div className="space-y-3">
        <div className="grid grid-cols-[120px_1fr] items-center gap-2">
          <label className="text-sm text-slate-300">Kağıt boyutu:</label>
          <select className="h-10 rounded-lg border border-slate-600 bg-slate-800 px-3 text-sm text-white outline-none ring-blue-500 focus:ring">
            <option>A4 (210 x 297 mm)</option>
          </select>
        </div>
        <div className="grid grid-cols-[120px_1fr] items-center gap-2">
          <label className="text-sm text-slate-300">Yönlendirme:</label>
          <select className="h-10 rounded-lg border border-slate-600 bg-slate-800 px-3 text-sm text-white outline-none ring-blue-500 focus:ring">
            <option>Dikey</option>
          </select>
        </div>
        <div className="grid grid-cols-[120px_1fr] items-center gap-2">
          <label className="text-sm text-slate-300">Sütun sayısı:</label>
          <select className="h-10 rounded-lg border border-slate-600 bg-slate-800 px-3 text-sm text-white outline-none ring-blue-500 focus:ring">
            <option>2</option>
          </select>
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-slate-200">Kenar boşluklarını ayarla:</h4>
        <div className="grid grid-cols-[50px_1fr] gap-3 rounded-lg border border-slate-700 bg-slate-800/60 p-3 text-sm text-slate-200">
          <div className="h-12 w-10 border border-slate-500 bg-slate-700/50" />
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            <span>Üst: 1,5 cm</span>
            <span>Alt: 1,5 cm</span>
            <span>Sol: 1,5 cm</span>
            <span>Sağ: 1,5 cm</span>
            <select className="col-span-1 mt-1 h-9 rounded-lg border border-slate-600 bg-slate-800 px-2 text-sm text-white">
              <option>Normal</option>
            </select>
            <button type="button" className="col-span-1 mt-1 h-9 text-left text-sm text-slate-300 underline">
              Özel kenar boşlukları
            </button>
          </div>
        </div>
      </div>

      <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg bg-slate-700 px-4 text-sm font-medium text-slate-200">
        <span>→</span>
        Diğer ayarları göster
      </button>

      <div>
        <button type="button" className="h-11 rounded-lg bg-blue-600 px-8 text-base font-semibold text-white">
          Tamam
        </button>
      </div>
    </section>
  );
}
