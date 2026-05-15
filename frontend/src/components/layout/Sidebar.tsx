import TestMetaForm from "../forms/TestMetaForm";
import OptionsPanel from "../forms/OptionsPanel";
import ThemeButton from "../forms/ThemeButton";
import PreparePaperButton from "../forms/PreparePaperButton";
import AdvancedSettingsPanel from "../forms/AdvancedSettingsPanel";
import WrittenPaperForm from "../forms/WrittenPaperForm";
import { type SidebarTab, useEditorStore } from "../../store/editorStore";

/** Ayarlar sekmesi — ince konturlu dişli (Lucide Settings) */
function SettingsGearIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

const tabs: { id: SidebarTab; label: string; iconOnly?: boolean }[] = [
  { id: "written-paper", label: "Yazılı Kağıdı" },
  { id: "test-paper", label: "Test Kağıdı" },
  { id: "trial-exam", label: "Deneme Sınavı" },
  { id: "settings", label: "Ayarlar", iconOnly: true },
];

export default function Sidebar() {
  const activeTab = useEditorStore((state) => state.activeTab);
  const setActiveTab = useEditorStore((state) => state.setActiveTab);
  const themeColor = useEditorStore((state) => state.themeColor);
  const isSettings = activeTab === "settings";
  const isWrittenPaper = activeTab === "written-paper";

  return (
    <aside
      className="tq-sidebar flex min-h-0 w-[var(--tq-sidebar-width)] shrink-0 flex-col border-r border-slate-700/60 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-900 text-slate-100 shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]"
    >
      <div className="tq-sidebar-header shrink-0 border-b border-slate-700/80">
        <div className="flex items-center gap-2.5">
          <div
            className="tq-sidebar-brand-mark grid place-items-center rounded-md text-white shadow"
            style={{ backgroundColor: themeColor }}
          >
            TQ
          </div>
          <h1 className="tq-brand-title text-white">TESTQUBE</h1>
        </div>
      </div>

      <div
        className="tq-sidebar-tablist shrink-0 border-b border-slate-700/70"
        role="tablist"
        aria-label="Bölümler"
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-label={tab.label}
            title={tab.label}
            onClick={() => {
              if (tab.id === "settings" && activeTab !== "settings") {
                useEditorStore.getState().setTabBeforeSettings(activeTab);
              }
              setActiveTab(tab.id);
            }}
            className={`tq-sidebar-tab ${tab.iconOnly ? "tq-sidebar-tab--icon-only" : "tq-sidebar-tab--grow"} ${
              activeTab === tab.id
                ? "bg-slate-800 font-semibold text-white shadow-[inset_0_-1px_0_rgba(255,255,255,0.12)]"
                : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-100"
            }`}
          >
            {tab.iconOnly ? (
              <SettingsGearIcon className="h-4 w-4 opacity-90" aria-hidden />
            ) : (
              tab.label
            )}
          </button>
        ))}
      </div>

      {isSettings ? (
        <div className="tq-sidebar-scroll">
          <AdvancedSettingsPanel />
        </div>
      ) : isWrittenPaper ? (
        <div className="tq-sidebar-scroll">
          <WrittenPaperForm />
        </div>
      ) : (
        <div className="tq-sidebar-scroll">
          <TestMetaForm />
          <OptionsPanel />
          <div className="flex min-w-0 flex-col gap-3 pt-0">
            <ThemeButton />
            <PreparePaperButton />
          </div>
        </div>
      )}
    </aside>
  );
}
