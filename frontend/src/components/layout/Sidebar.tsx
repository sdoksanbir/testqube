import TestMetaForm from "../forms/TestMetaForm";
import OptionsPanel from "../forms/OptionsPanel";
import ThemeButton from "../forms/ThemeButton";
import PreparePaperButton from "../forms/PreparePaperButton";
import AdvancedSettingsPanel from "../forms/AdvancedSettingsPanel";
import { type SidebarTab, useEditorStore } from "../../store/editorStore";

const tabs: { id: SidebarTab; label: string }[] = [
  { id: "test-paper", label: "Test Kağıdı" },
  { id: "settings", label: "Ayarlar" }
];

export default function Sidebar() {
  const activeTab = useEditorStore((state) => state.activeTab);
  const setActiveTab = useEditorStore((state) => state.setActiveTab);
  const isSettings = activeTab === "settings";

  return (
    <aside className="flex w-[360px] flex-col border-r border-slate-700/60 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-900 text-slate-100 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
      <div className="border-b border-slate-700/80 p-5">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-orange-400 to-orange-600 text-sm font-extrabold text-white shadow">
            TQ
          </div>
          <h1 className="text-xl font-extrabold tracking-wide text-white">TESTQUBE</h1>
        </div>
      </div>

      <div className="flex border-b border-slate-700/70 px-4 pt-3">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`mr-2 rounded-t-xl px-4 py-2 text-sm font-medium transition ${
              activeTab === tab.id
                ? "bg-slate-800 text-white shadow-[0_-1px_0_rgba(255,255,255,0.08)]"
                : "text-slate-400 hover:bg-slate-800/70 hover:text-white"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isSettings ? (
        <div className="overflow-auto p-5">
          <AdvancedSettingsPanel />
        </div>
      ) : (
        <div className="space-y-5 overflow-auto p-5">
          <TestMetaForm />
          <OptionsPanel />
          <div className="grid gap-3 pt-2">
            <ThemeButton />
            <PreparePaperButton />
          </div>
        </div>
      )}
    </aside>
  );
}
