import base64
import uuid
from pathlib import Path
from typing import List

from app.core.config import IMAGES_DIR
from app.models.schemas import (
    CreateFromLocalPdfRequest,
    CreateQuestionRequest,
    QuestionItem,
    UpdateExplanationCaptionRequest,
)


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
            remove_background=payload.remove_background,
        )
        self._questions.append(item)
        return item

    def create_from_local_pdf(self, payload: CreateFromLocalPdfRequest) -> QuestionItem:
        """Local PDF mode: save image to disk, create question with image_path."""
        qid = str(uuid.uuid4())
        raw = payload.image_base64
        if "," in raw:
            raw = raw.split(",", 1)[1]
        data = base64.b64decode(raw)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        image_path = str(IMAGES_DIR / f"{qid}.png")
        Path(image_path).write_bytes(data)

        item = QuestionItem(
            id=qid,
            pdf_id="",
            page_number=payload.page,
            crop=payload.selection,
            answer_key=payload.answer_key or "",
            order_index=len(self._questions),
            remove_background=payload.remove_background,
            image_path=image_path,
        )
        self._questions.append(item)
        return item

    def update_answer(self, question_id: str, answer_key: str) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                item.answer_key = answer_key
                return item
        raise KeyError(f"Question not found: {question_id}")

    def update_remove_background(self, question_id: str, remove_background: bool) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                item.remove_background = remove_background
                return item
        raise KeyError(f"Question not found: {question_id}")

    def update_crop(self, question_id: str, crop) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                item.crop = crop
                return item
        raise KeyError(f"Question not found: {question_id}")

    def update_content_type(self, question_id: str, content_type: str) -> QuestionItem:
        normalized = str(content_type or "question").strip().lower()
        if normalized not in ("question", "explanation"):
            raise ValueError("content_type must be 'question' or 'explanation'")
        for item in self._questions:
            if item.id == question_id:
                item.content_type = normalized
                return item
        raise KeyError(f"Question not found: {question_id}")

    def update_explanation_caption(self, question_id: str, payload: UpdateExplanationCaptionRequest) -> QuestionItem:
        for item in self._questions:
            if item.id == question_id:
                item.explanation_caption_enabled = bool(payload.explanation_caption_enabled)
                item.explanation_caption_text = payload.explanation_caption_text or ""
                item.explanation_caption_align = payload.explanation_caption_align
                item.explanation_caption_placement = payload.explanation_caption_placement
                item.explanation_caption_side_flow = payload.explanation_caption_side_flow
                item.explanation_caption_color = payload.explanation_caption_color or "#0f172a"
                item.explanation_caption_bold = bool(payload.explanation_caption_bold)
                item.explanation_caption_italic = bool(payload.explanation_caption_italic)
                item.explanation_caption_font_pt = float(payload.explanation_caption_font_pt)
                item.explanation_caption_box_enabled = bool(payload.explanation_caption_box_enabled)
                item.explanation_caption_box_color = payload.explanation_caption_box_color or "#f1f5f9"
                item.explanation_caption_box_corner = payload.explanation_caption_box_corner
                item.explanation_caption_box_width = payload.explanation_caption_box_width
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
