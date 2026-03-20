from fastapi import APIRouter, HTTPException

from app.dependencies import export_service, pdf_service, question_service
from app.models.schemas import ExportRequest

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("/simple")
def export_simple(payload: ExportRequest):
    try:
        path = export_service.export_desktop_style(
            title=payload.title,
            school_name=payload.school_name,
            include_answer_key=payload.include_answer_key,
            columns=payload.columns,
            question_gap_mm=payload.question_gap_mm,
            page_preset=payload.page_preset,
            header_style_id=payload.header_style_id,
            theme_color=payload.theme_color,
            questions=question_service.list_questions(),
            pdf_items=pdf_service.list_pdfs(),
        )
        return {"path": str(path)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
