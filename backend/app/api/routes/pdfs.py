from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.dependencies import pdf_service

router = APIRouter(prefix="/pdfs", tags=["pdfs"])


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile] = File(...)):
    try:
        created = await pdf_service.save_uploads(files)
        return {"items": created}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_pdfs():
    return {"items": pdf_service.list_pdfs()}


@router.delete("/{pdf_id}")
def delete_pdf(pdf_id: str):
    try:
        pdf_service.delete_pdf(pdf_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{pdf_id}/pages/{page_number}/image")
def render_page(
    pdf_id: str,
    page_number: int,
    zoom: float | None = None,
    dpi: float | None = None,
):
    """Render PDF page as PNG. Use dpi (72–600) for render resolution, or zoom (1–4) as fallback."""
    if dpi is not None:
        zoom_val = dpi / 72.0
    elif zoom is not None:
        zoom_val = float(zoom)
    else:
        zoom_val = 2.0  # ~144 DPI
    try:
        png = pdf_service.render_page_png(pdf_id, page_number, zoom_val)
        return Response(content=png, media_type="image/png")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
