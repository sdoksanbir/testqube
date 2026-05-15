import { useEditorStore } from "../../store/editorStore";

export default function TestMetaForm() {
  const testName = useEditorStore((state) => state.testName);
  const schoolName = useEditorStore((state) => state.schoolName);
  const setTestName = useEditorStore((state) => state.setTestName);
  const setSchoolName = useEditorStore((state) => state.setSchoolName);

  return (
    <section className="flex flex-col gap-3 min-w-0">
      <label className="tq-field">
        <span className="tq-field-label">Test Adı</span>
        <input
          value={testName}
          onChange={(event) => setTestName(event.target.value)}
          placeholder="Test Adı"
          className="tq-input"
        />
      </label>

      <label className="tq-field">
        <span className="tq-field-label">Kurum adı</span>
        <input
          value={schoolName}
          onChange={(event) => setSchoolName(event.target.value)}
          placeholder="Kurum adı"
          className="tq-input"
        />
      </label>
    </section>
  );
}
