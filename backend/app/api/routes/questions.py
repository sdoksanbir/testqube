from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.dependencies import pdf_service, question_service
from app.models.schemas import CreateQuestionRequest, ReorderQuestionsRequest, UpdateAnswerRequest

router = APIRouter(prefix="/questions", tags=["questions"])


@router.get("")
def list_questions():
    return {"items": question_service.list_questions()}


@router.post("")
def create_question(payload: CreateQuestionRequest):
    try:
        return question_service.create_question(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{question_id}/answer")
def update_answer(question_id: str, payload: UpdateAnswerRequest):
    try:
        return question_service.update_answer(question_id, payload.answer_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reorder")
def reorder_questions(payload: ReorderQuestionsRequest):
    try:
        items = question_service.reorder(payload.ordered_ids)
        return {"items": items}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{question_id}")
def delete_question(question_id: str):
    try:
        question_service.delete_question(question_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{question_id}/image")
def get_question_image(question_id: str):
    try:
        q = question_service.get_question(question_id)
        png = pdf_service.crop_page_png(
            q.pdf_id, q.page_number,
            q.crop.x, q.crop.y, q.crop.width, q.crop.height
        )
        return Response(content=png, media_type="image/png")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
