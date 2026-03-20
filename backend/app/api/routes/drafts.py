from fastapi import APIRouter, HTTPException

from app.dependencies import draft_service, question_service
from app.models.schemas import DraftPayload

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("")
def list_drafts():
    return {"items": draft_service.list_drafts()}


@router.post("")
def save_draft(payload: DraftPayload):
    info = draft_service.save_draft(payload)
    return info


@router.get("/{name}")
def load_draft(name: str):
    try:
        draft = draft_service.load_draft(name)
        question_service.replace_all(draft.questions)
        return draft
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
