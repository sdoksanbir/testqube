import { useEditorStore } from "../../store/editorStore";

export default function TestMetaForm() {
  const testName = useEditorStore((state) => state.testName);
  const schoolName = useEditorStore((state) => state.schoolName);
  const setTestName = useEditorStore((state) => state.setTestName);
  const setSchoolName = useEditorStore((state) => state.setSchoolName);

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-200">Test Bilgileri</h3>

      <label className="block text-xs text-slate-400">
        Test Adı
        <input
          value={testName}
          onChange={(event) => setTestName(event.target.value)}
          placeholder="Test Adı"
          className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white outline-none ring-blue-500 focus:ring"
        />
      </label>

      <label className="block text-xs text-slate-400">
        Kurum adı
        <input
          value={schoolName}
          onChange={(event) => setSchoolName(event.target.value)}
          placeholder="Kurum adı"
          className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white outline-none ring-blue-500 focus:ring"
        />
      </label>
    </section>
  );
}
