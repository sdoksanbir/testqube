import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

from app.dependencies import export_service, pdf_service, question_service
from app.models.schemas import ExportRequest, ExportWithQuestionsRequest

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


@router.post("/from-questions")
def export_from_questions(payload: ExportWithQuestionsRequest):
    """Export PDF from questions payload - no persist, cache-only mode."""
    try:
        mode = getattr(payload, "answer_key_mode", None) or "per_page"
        if mode not in ("per_page", "separate_page", "end_of_test"):
            mode = "per_page"
        logger.info("Export answer_key_mode=%s include_answer_key=%s", mode, payload.include_answer_key)
        path = export_service.export_from_questions_payload(
            title=payload.title,
            school_name=payload.school_name,
            include_answer_key=payload.include_answer_key,
            answer_key_mode=mode,
            columns=payload.columns,
            question_gap_mm=payload.question_gap_mm,
            question_gap_min_mm=payload.question_gap_min_mm,
            auto_compact_spacing=payload.auto_compact_spacing,
            page_preset=payload.page_preset,
            page_width_mm=payload.page_width_mm,
            page_height_mm=payload.page_height_mm,
            orientation=payload.orientation,
            margin_top_mm=payload.margin_top_mm,
            margin_bottom_mm=payload.margin_bottom_mm,
            margin_left_mm=payload.margin_left_mm,
            margin_right_mm=payload.margin_right_mm,
            header_style_id=payload.header_style_id,
            theme_color=payload.theme_color,
            quality=payload.quality,
            questions=payload.questions,
            sections=payload.sections,
            pdf_items=pdf_service.list_pdfs(),
            include_description=payload.include_description,
            test_description=payload.test_description or "",
            description_column_count=payload.description_column_count or 1,
            description_texts=payload.description_texts or [],
            description_column_dividers=getattr(
                payload, "description_column_dividers", False
            ),
            add_text_on_line=payload.add_text_on_line,
            center_line_text=payload.center_line_text or "",
            center_line_bold=payload.center_line_bold,
            center_line_italic=payload.center_line_italic,
            center_line_text_direction=payload.center_line_text_direction or "up",
            watermark_enabled=payload.watermark_enabled,
            watermark_mode=payload.watermark_mode,
            watermark_text=payload.watermark_text,
            watermark_text_opacity_pct=payload.watermark_text_opacity_pct,
            watermark_text_size_pct=payload.watermark_text_size_pct,
            watermark_text_angle_deg=payload.watermark_text_angle_deg,
            watermark_text_color=payload.watermark_text_color,
            watermark_image_base64=payload.watermark_image_base64,
            watermark_image_opacity_pct=payload.watermark_image_opacity_pct,
            watermark_image_size_pct=payload.watermark_image_size_pct,
            written_paper_header=getattr(payload, "written_paper_header", False),
            written_paper_title=getattr(payload, "written_paper_title", None),
            written_paper_field_lines=getattr(payload, "written_paper_field_lines", None),
            written_paper_field_hidden=getattr(payload, "written_paper_field_hidden", None),
            written_paper_field_labels=getattr(payload, "written_paper_field_labels", None),
            exam_type=getattr(payload, "exam_type", None),
            footer_nav_page_turn_texts=getattr(
                payload, "footer_nav_page_turn_texts", True
            ),
            class_section=getattr(payload, "class_section", None),
            group=getattr(payload, "group", None),
            teacher_names=getattr(payload, "teacher_names", None) or [],
            principal_name=getattr(payload, "principal_name", None),
            layout_y_top_overrides=getattr(payload, "layout_y_top_overrides", None),
        )
        return FileResponse(
            path=str(path),
            filename=path.name,
            media_type="application/pdf",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/layout")
def export_layout(payload: ExportWithQuestionsRequest):
    """Compute question layout positions for PDF preview - no PDF generation."""
    try:
        layout, page_w_pt, page_h_pt = export_service.compute_layout_from_questions(
            title=payload.title,
            school_name=payload.school_name,
            include_answer_key=payload.include_answer_key,
            answer_key_mode=payload.answer_key_mode,
            columns=payload.columns,
            question_gap_mm=payload.question_gap_mm,
            question_gap_min_mm=payload.question_gap_min_mm,
            auto_compact_spacing=payload.auto_compact_spacing,
            page_preset=payload.page_preset,
            page_width_mm=payload.page_width_mm,
            page_height_mm=payload.page_height_mm,
            orientation=payload.orientation,
            margin_top_mm=payload.margin_top_mm,
            margin_bottom_mm=payload.margin_bottom_mm,
            margin_left_mm=payload.margin_left_mm,
            margin_right_mm=payload.margin_right_mm,
            header_style_id=payload.header_style_id,
            theme_color=payload.theme_color,
            questions=payload.questions,
            sections=payload.sections,
            pdf_items=pdf_service.list_pdfs(),
            include_description=payload.include_description,
            test_description=payload.test_description or "",
            description_column_count=payload.description_column_count or 1,
            description_texts=payload.description_texts or [],
            description_column_dividers=getattr(
                payload, "description_column_dividers", False
            ),
            add_text_on_line=payload.add_text_on_line,
            center_line_text=payload.center_line_text or "",
            center_line_bold=payload.center_line_bold,
            center_line_italic=payload.center_line_italic,
            center_line_text_direction=payload.center_line_text_direction or "up",
            watermark_enabled=payload.watermark_enabled,
            watermark_mode=payload.watermark_mode,
            watermark_text=payload.watermark_text,
            watermark_text_opacity_pct=payload.watermark_text_opacity_pct,
            watermark_text_size_pct=payload.watermark_text_size_pct,
            watermark_text_angle_deg=payload.watermark_text_angle_deg,
            watermark_text_color=payload.watermark_text_color,
            watermark_image_base64=payload.watermark_image_base64,
            watermark_image_opacity_pct=payload.watermark_image_opacity_pct,
            watermark_image_size_pct=payload.watermark_image_size_pct,
            written_paper_header=getattr(payload, "written_paper_header", False),
            written_paper_title=getattr(payload, "written_paper_title", None),
            written_paper_field_lines=getattr(payload, "written_paper_field_lines", None),
            written_paper_field_hidden=getattr(payload, "written_paper_field_hidden", None),
            written_paper_field_labels=getattr(payload, "written_paper_field_labels", None),
            exam_type=getattr(payload, "exam_type", None),
            class_section=getattr(payload, "class_section", None),
            group=getattr(payload, "group", None),
            teacher_names=getattr(payload, "teacher_names", None) or [],
            principal_name=getattr(payload, "principal_name", None),
            layout_y_top_overrides=getattr(payload, "layout_y_top_overrides", None),
        )
        if payload.skip_images:
            layout = [{k: v for k, v in it.items() if k != "image_base64"} for it in layout]
        return {"layout": layout, "page_w_pt": page_w_pt, "page_h_pt": page_h_pt}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
