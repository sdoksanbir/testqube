from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.dependencies import pdf_service, question_service
from app.models.schemas import (
    CreateFromLocalPdfRequest,
    CreateQuestionRequest,
    ReorderQuestionsRequest,
    UpdateAnswerRequest,
    UpdateContentTypeRequest,
    UpdateExplanationCaptionRequest,
    UpdateRemoveBackgroundRequest,
    UpdateCropRequest,
)

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


@router.post("/from-local-pdf")
def create_from_local_pdf(payload: CreateFromLocalPdfRequest):
    """Local PDF mode: client sends cropped image, no server PDF. Mevcut sisteme ek."""
    try:
        return question_service.create_from_local_pdf(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{question_id}/answer")
def update_answer(question_id: str, payload: UpdateAnswerRequest):
    try:
        return question_service.update_answer(question_id, payload.answer_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{question_id}/remove-background")
def update_remove_background(question_id: str, payload: UpdateRemoveBackgroundRequest):
    try:
        return question_service.update_remove_background(question_id, payload.remove_background)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{question_id}/crop")
def update_crop(question_id: str, payload: UpdateCropRequest):
    try:
        return question_service.update_crop(question_id, payload.crop)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{question_id}/content-type")
def update_content_type(question_id: str, payload: UpdateContentTypeRequest):
    try:
        return question_service.update_content_type(question_id, payload.content_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{question_id}/explanation-caption")
def update_explanation_caption(question_id: str, payload: UpdateExplanationCaptionRequest):
    try:
        return question_service.update_explanation_caption(question_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        if getattr(q, "image_path", None):
            path = Path(q.image_path)
            if path.exists():
                png = path.read_bytes()
                if getattr(q, "remove_background", False):
                    png = pdf_service.remove_background_from_png_bytes(png)
                return Response(content=png, media_type="image/png")
            raise HTTPException(status_code=404, detail="Image not found")
        png = pdf_service.crop_page_png(
            q.pdf_id, q.page_number,
            q.crop.x, q.crop.y, q.crop.width, q.crop.height,
            remove_background=getattr(q, "remove_background", False),
        )
        return Response(content=png, media_type="image/png")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
