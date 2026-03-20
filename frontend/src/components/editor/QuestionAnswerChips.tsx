import { type AnswerOption, useEditorStore } from "../../store/editorStore";

type QuestionAnswerChipsProps = {
  questionId: string;
  selected?: AnswerOption;
};

const options: AnswerOption[] = ["A", "B", "C", "D", "E"];

export default function QuestionAnswerChips({ questionId, selected }: QuestionAnswerChipsProps) {
  const setQuestionAnswer = useEditorStore((state) => state.setQuestionAnswer);

  return (
    <div className="flex justify-center gap-1.5">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => setQuestionAnswer(questionId, option)}
          className={`flex h-5 w-5 items-center justify-center rounded border text-[10px] font-bold leading-none transition ${
            selected === option
              ? "border-orange-500 bg-orange-500 text-white shadow-md shadow-orange-900/30"
              : "border-orange-300/90 bg-white text-orange-900/90 hover:bg-orange-100 hover:border-orange-400"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
