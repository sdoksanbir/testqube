import type { QuestionItem } from "../../types";
import QuestionCard from "./QuestionCard";

type QuestionGridProps = {
  questions: QuestionItem[];
};

export default function QuestionGrid({ questions }: QuestionGridProps) {
  return (
    <div className="grid grid-cols-1 content-start gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {questions.map((question) => (
        <QuestionCard key={question.id} question={question} />
      ))}
    </div>
  );
}
