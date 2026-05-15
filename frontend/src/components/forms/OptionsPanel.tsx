import { useState } from "react";
import { useEditorStore } from "../../store/editorStore";
import AnswerKeyModeModal from "../modals/AnswerKeyModeModal";
import CenterLineTextModal from "../modals/CenterLineTextModal";
import QuestionGapModal from "../modals/QuestionGapModal";
import TestDescriptionModal from "../modals/TestDescriptionModal";

const optionItems = [
  { key: "includeDescription" as const, label: "Test ile ilgili açıklama ekle" },
  { key: "addSpacingBetweenQuestions" as const, label: "Sorular arasına boşluk ekle" },
  { key: "includeAnswerKey" as const, label: "Teste cevap anahtarı ekle" },
  { key: "addTextOnLine" as const, label: "Çizgi üzerine yazı ekle" },
];

export default function OptionsPanel() {
  const options = useEditorStore((state) => state.options);
  const toggleOption = useEditorStore((state) => state.toggleOption);
  const themeColor = useEditorStore((state) => state.themeColor);
  const testDescription = useEditorStore((state) => state.testDescription);
  const descriptionColumnCount = useEditorStore((state) => state.descriptionColumnCount);
  const descriptionTexts = useEditorStore((state) => state.descriptionTexts);
  const descriptionColumnDividers = useEditorStore((state) => state.descriptionColumnDividers);
  const questionGapMm = useEditorStore((state) => state.questionGapMm);
  const questionGapMinMm = useEditorStore((state) => state.questionGapMinMm);
  const autoCompactSpacing = useEditorStore((state) => state.autoCompactSpacing);
  const setQuestionGapMinMm = useEditorStore((state) => state.setQuestionGapMinMm);
  const setAutoCompactSpacing = useEditorStore((state) => state.setAutoCompactSpacing);
  const answerKeyMode = useEditorStore((state) => state.answerKeyMode);
  const centerLineText = useEditorStore((state) => state.centerLineText);
  const centerLineBold = useEditorStore((state) => state.centerLineBold);
  const centerLineItalic = useEditorStore((state) => state.centerLineItalic);
  const centerLineTextDirection = useEditorStore((state) => state.centerLineTextDirection);
  const setDescriptionColumns = useEditorStore((state) => state.setDescriptionColumns);
  const setQuestionGapMm = useEditorStore((state) => state.setQuestionGapMm);
  const setAnswerKeyMode = useEditorStore((state) => state.setAnswerKeyMode);
  const setCenterLineText = useEditorStore((state) => state.setCenterLineText);
  const setCenterLineBold = useEditorStore((state) => state.setCenterLineBold);
  const setCenterLineItalic = useEditorStore((state) => state.setCenterLineItalic);
  const setCenterLineTextDirection = useEditorStore((state) => state.setCenterLineTextDirection);

  const [showDescModal, setShowDescModal] = useState(false);
  const [showGapModal, setShowGapModal] = useState(false);
  const [showAnswerKeyModal, setShowAnswerKeyModal] = useState(false);
  const [showCenterLineModal, setShowCenterLineModal] = useState(false);

  const handleOptionClick = (key: (typeof optionItems)[number]["key"]) => {
    const isCurrentlyChecked = options[key];

    if (key === "includeDescription") {
      if (!isCurrentlyChecked) setShowDescModal(true);
      else toggleOption(key);
    } else if (key === "addSpacingBetweenQuestions") {
      setShowGapModal(true);
    } else if (key === "includeAnswerKey") {
      setShowAnswerKeyModal(true);
    } else if (key === "addTextOnLine") {
      setShowCenterLineModal(true);
    }
  };

  return (
    <section className="flex min-w-0 flex-col gap-3">
      <h3 className="tq-sidebar-section-title text-slate-100">Seçenekler</h3>
      <div className="tq-options-card space-y-2">
        {optionItems.map((item) =>
          item.key === "addTextOnLine" || item.key === "includeDescription" ? (
            <div key={item.key} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={options[item.key]}
                onChange={() => {
                  if (item.key === "addTextOnLine") {
                    if (options[item.key]) {
                      toggleOption(item.key);
                      setCenterLineText("");
                      setCenterLineBold(false);
                      setCenterLineItalic(false);
                    } else {
                      setShowCenterLineModal(true);
                    }
                  } else {
                    if (options[item.key]) {
                      toggleOption(item.key);
                    } else {
                      setShowDescModal(true);
                    }
                  }
                }}
                className="h-4 w-4 shrink-0 cursor-pointer rounded border-slate-500"
              />
              <span
                role="button"
                tabIndex={0}
                onClick={() =>
                  item.key === "includeDescription" ? setShowDescModal(true) : setShowCenterLineModal(true)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    item.key === "includeDescription" ? setShowDescModal(true) : setShowCenterLineModal(true);
                  }
                }}
                className="tq-row-label cursor-pointer hover:text-white"
              >
                {item.label}
              </span>
            </div>
          ) : (
            <label key={item.key} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={options[item.key]}
                onChange={() => handleOptionClick(item.key)}
                className="h-4 w-4 shrink-0 rounded border-slate-500"
              />
              <span className="tq-row-label">{item.label}</span>
            </label>
          )
        )}
      </div>

      <TestDescriptionModal
        open={showDescModal}
        onClose={() => setShowDescModal(false)}
        onConfirm={(columnCount, texts, dividers) => {
          setDescriptionColumns(columnCount, texts, dividers);
          if (!options.includeDescription) toggleOption("includeDescription");
          setShowDescModal(false);
        }}
        initialColumnCount={descriptionColumnCount}
        initialColumnDividers={descriptionColumnDividers}
        initialTexts={
          descriptionTexts.length >= descriptionColumnCount
            ? descriptionTexts
            : descriptionColumnCount === 1
              ? [testDescription || ""]
              : [testDescription || "", ...Array(descriptionColumnCount - 1).fill("")]
        }
        themeColor={themeColor}
      />

      <QuestionGapModal
        open={showGapModal}
        onClose={() => setShowGapModal(false)}
        onConfirm={({ preferredGapMm, minGapMm, autoCompact }) => {
          setQuestionGapMm(preferredGapMm);
          setQuestionGapMinMm(minGapMm);
          setAutoCompactSpacing(autoCompact);
          if (!options.addSpacingBetweenQuestions) toggleOption("addSpacingBetweenQuestions");
          setShowGapModal(false);
        }}
        currentGapMm={questionGapMm}
        currentMinGapMm={questionGapMinMm}
        currentAutoCompact={autoCompactSpacing}
      />

      <AnswerKeyModeModal
        open={showAnswerKeyModal}
        isEnabled={options.includeAnswerKey}
        onClose={() => setShowAnswerKeyModal(false)}
        onConfirm={(mode) => {
          if (mode === "off") {
            toggleOption("includeAnswerKey");
          } else {
            setAnswerKeyMode(mode);
            if (!options.includeAnswerKey) toggleOption("includeAnswerKey");
          }
          setShowAnswerKeyModal(false);
        }}
        currentMode={answerKeyMode}
        themeColor={themeColor}
      />

      <CenterLineTextModal
        open={showCenterLineModal}
        onClose={() => setShowCenterLineModal(false)}
        onConfirm={(text, bold, italic, direction) => {
          setCenterLineText(text);
          setCenterLineBold(bold);
          setCenterLineItalic(italic);
          setCenterLineTextDirection(direction);
          if (!options.addTextOnLine) toggleOption("addTextOnLine");
          setShowCenterLineModal(false);
        }}
        initialText={centerLineText}
        initialBold={centerLineBold}
        initialItalic={centerLineItalic}
        initialDirection={centerLineTextDirection}
        themeColor={themeColor}
      />
    </section>
  );
}
