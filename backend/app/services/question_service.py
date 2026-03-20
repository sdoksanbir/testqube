import uuid
from typing import List

from app.models.schemas import CreateQuestionRequest, QuestionItem


class QuestionService:
    """
    Migration decision:
    - Question state transitions (create/edit/reorder) are business logic.
    - Keep this backend-owned, independent from any specific UI toolkit.
    """

    def __init__(self) -> None:
        self._questions: List[QuestionItem] = []

    def list_questions(self) -> List[QuestionItem]:
        return sorted(self._questions, key=lambda x: x.order_index)

    def create_question(self, payload: CreateQuestionRequest) -> QuestionItem:
        item = QuestionItem(
            id=str(uuid.uuid4()),
            pdf_id=payload.pdf_id,
            page_number=payload.page_number,
            crop=payload.crop,
            answer_key=payload.answer_key or "",
            order_index=len(self._questions),
        )
        self._questions.append(item)
        return item

    def update_answer(self, question_id: str, answer_key: str) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                item.answer_key = answer_key
                return item
        raise KeyError(f"Question not found: {question_id}")

    def reorder(self, ordered_ids: List[str]) -> List[QuestionItem]:
        by_id = {q.id: q for q in self._questions}
        if set(ordered_ids) != set(by_id.keys()):
            raise ValueError("Ordered IDs must match existing question IDs exactly.")

        self._questions = [by_id[qid] for qid in ordered_ids]
        for idx, item in enumerate(self._questions):
            item.order_index = idx
        return self.list_questions()

    def replace_all(self, questions: List[QuestionItem]) -> None:
        self._questions = sorted(questions, key=lambda x: x.order_index)
        for idx, item in enumerate(self._questions):
            item.order_index = idx

    def delete_question(self, question_id: str) -> None:
        for i, item in enumerate(self._questions):
            if item.id == question_id:
                self._questions.pop(i)
                for idx, q in enumerate(self._questions):
                    q.order_index = idx
                return
        raise KeyError(f"Question not found: {question_id}")

    def get_question(self, question_id: str) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                return item
        raise KeyError(f"Question not found: {question_id}")
