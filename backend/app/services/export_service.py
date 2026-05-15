from pathlib import Path
from typing import List

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.core.config import EXPORT_DIR
from app.models.schemas import PdfItem, QuestionItem
from app.services.desktop_export import (
    ExportOptions,
    export_desktop_style,
    export_from_payload,
    compute_layout_from_payload,
    page_size_pt,
)

class ExportService:
    """
    Migration decision:
    - Final composition/export remains backend-side to preserve existing Python logic.
    - Frontend sends intent/settings; backend produces deterministic PDF artifact.
    """

    def export_simple_pdf(
        self,
        title: str,
        include_answer_key: bool,
        questions: List[QuestionItem],
        pdf_items: List[PdfItem],
    ) -> Path:
        pdf_map = {p.id: p for p in pdf_items}
        out_path = EXPORT_DIR / "exported_test.pdf"
        c = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4

        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, height - 40, title)
        y = height - 80

        for idx, q in enumerate(sorted(questions, key=lambda x: x.order_index), start=1):
            item = pdf_map.get(q.pdf_id)
            if not item:
                continue

            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, y, f"Q{idx}")
            if include_answer_key:
                c.setFont("Helvetica", 10)
                c.drawString(90, y, f"Answer: {q.answer_key or '-'}")
            y -= 14

            crop_img = self._render_crop_png(
                Path(item.path),
                q.page_number,
                q.crop.x,
                q.crop.y,
                q.crop.width,
                q.crop.height,
            )  # crop is norm 0..1
            img_path = EXPORT_DIR / f"q_{q.id}.png"
            img_path.write_bytes(crop_img)

            img_h = 110
            img_w = 250
            if y - img_h < 40:
                c.showPage()
                y = height - 40
            c.drawImage(
                str(img_path),
                40,
                y - img_h,
                width=img_w,
                height=img_h,
                preserveAspectRatio=True,
                mask="auto",
            )
            y -= img_h + 20

        c.save()
        return out_path

    def export_desktop_style(
        self,
        title: str,
        school_name: str,
        include_answer_key: bool,
        columns: int,
        question_gap_mm: float,
        page_preset: str,
        header_style_id: str,
        theme_color: str,
        questions: List[QuestionItem],
        pdf_items: List[PdfItem],
    ) -> Path:
        """Desktop-style export with headers, columns, answer key."""
        opts = ExportOptions(
            test_title=title,
            school_name=school_name,
            answer_key_enabled=include_answer_key,
            columns=columns,
            question_gap_mm=question_gap_mm,
            page_preset=page_preset,
            header_style_id=header_style_id,
            theme_color=theme_color,
        )
        return export_desktop_style(questions, pdf_items, opts)

    _QUALITY_ZOOM = {"normal": 4.0, "high": 6.0, "best": 8.0}  # 72*zoom DPI

    def export_from_questions_payload(
        self,
        title: str,
        school_name: str,
        include_answer_key: bool,
        columns: int,
        question_gap_mm: float,
        question_gap_min_mm: float = 12.0,
        answer_key_mode: str = "per_page",
        auto_compact_spacing: bool = True,
        page_preset: str = "A4",
        page_width_mm: float = 210.0,
        page_height_mm: float = 297.0,
        orientation: str = "portrait",
        margin_top_mm: float = 15.0,
        margin_bottom_mm: float = 15.0,
        margin_left_mm: float = 15.0,
        margin_right_mm: float = 15.0,
        header_style_id: str = "style3",
        theme_color: str = "#AECBFA",
        quality: str = "high",
        questions: list | None = None,
        sections: list | None = None,
        pdf_items: list | None = None,
        include_description: bool = False,
        test_description: str = "",
        description_column_count: int = 1,
        description_texts: list | None = None,
        description_column_dividers: bool = False,
        add_text_on_line: bool = False,
        center_line_text: str = "",
        center_line_bold: bool = False,
        center_line_italic: bool = False,
        center_line_text_direction: str = "up",
        watermark_enabled: bool = False,
        watermark_mode: str = "text",
        watermark_text: str = "",
        watermark_text_opacity_pct: int = 20,
        watermark_text_size_pct: int = 90,
        watermark_text_angle_deg: int = 45,
        watermark_text_color: str = "#000000",
        watermark_image_base64: str | None = None,
        watermark_image_opacity_pct: int = 15,
        watermark_image_size_pct: int = 50,
        written_paper_header: bool = False,
        written_paper_title: str | None = None,
        written_paper_field_lines: dict | None = None,
        written_paper_field_hidden: dict | None = None,
        written_paper_field_labels: dict | None = None,
        exam_type: str | None = None,
        footer_nav_page_turn_texts: bool = True,
        class_section: str | None = None,
        group: str | None = None,
        teacher_names: list | None = None,
        principal_name: str | None = None,
        layout_y_top_overrides: list | None = None,
    ) -> Path:
        """Export from questions payload - no persist, supports image_base64 and sections."""
        questions = questions or []
        sections = sections or []
        pdf_items = pdf_items or []
        zoom = self._QUALITY_ZOOM.get((quality or "high").lower(), 6.0)
        ak_mode = (answer_key_mode or "per_page").strip().lower()
        if written_paper_header and include_answer_key:
            ak_mode = "separate_page"
        opts = ExportOptions(
            test_title=title,
            school_name=school_name,
            answer_key_enabled=include_answer_key,
            answer_key_mode=ak_mode,
            columns=columns,
            question_gap_mm=question_gap_mm,
            question_gap_min_mm=question_gap_min_mm,
            auto_compact_spacing=auto_compact_spacing,
            page_preset=page_preset,
            page_width_mm=page_width_mm,
            page_height_mm=page_height_mm,
            orientation=orientation,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            header_style_id=header_style_id,
            theme_color=theme_color,
            zoom=zoom,
            include_description=include_description,
            test_description=test_description or "",
            description_column_count=description_column_count or 1,
            description_texts=description_texts or [],
            description_column_dividers=bool(description_column_dividers),
            center_line_enabled=add_text_on_line,
            center_line_text=center_line_text or "",
            center_line_bold=center_line_bold,
            center_line_italic=center_line_italic,
            center_line_color="",
            center_line_text_direction=center_line_text_direction or "up",
            watermark_enabled=watermark_enabled,
            watermark_mode=watermark_mode or "text",
            watermark_text=watermark_text or "",
            watermark_text_opacity_pct=watermark_text_opacity_pct,
            watermark_text_size_pct=watermark_text_size_pct,
            watermark_text_angle_deg=watermark_text_angle_deg,
            watermark_text_color=watermark_text_color or "#000000",
            watermark_image_base64=watermark_image_base64,
            watermark_image_opacity_pct=watermark_image_opacity_pct,
            watermark_image_size_pct=watermark_image_size_pct,
            written_paper_header=written_paper_header,
            written_paper_title=written_paper_title,
            written_paper_field_lines=written_paper_field_lines,
            written_paper_field_hidden=written_paper_field_hidden,
            written_paper_field_labels=written_paper_field_labels,
            exam_type=exam_type,
            footer_nav_page_turn_texts=footer_nav_page_turn_texts,
            class_section=class_section,
            group=group,
            teacher_names=teacher_names or [],
            principal_name=principal_name,
        )
        q_list = []
        for q in questions:
            if isinstance(q, dict):
                qd = q
            else:
                qd = q.model_dump() if hasattr(q, "model_dump") else (q.dict() if hasattr(q, "dict") else {})
            crop = qd.get("crop", {})
            if hasattr(crop, "model_dump"):
                crop = crop.model_dump()
            elif not isinstance(crop, dict):
                crop = {"x": 0, "y": 0, "width": 1, "height": 1}
            q_list.append({
                "id": qd.get("id", ""),
                "pdf_id": qd.get("pdf_id", ""),
                "page_number": qd.get("page_number", 1),
                "crop": crop,
                "answer_key": qd.get("answer_key", ""),
                "order_index": qd.get("order_index", 0),
                "content_type": qd.get("content_type") or "question",
                "remove_background": qd.get("remove_background", False),
                "image_base64": qd.get("image_base64"),
                "custom_gap_mm": qd.get("custom_gap_mm"),
                "display_scale": qd.get("display_scale"),
                "explanation_caption_enabled": bool(qd.get("explanation_caption_enabled", False)),
                "explanation_caption_text": qd.get("explanation_caption_text") or "",
                "explanation_caption_align": qd.get("explanation_caption_align") or "left",
                "explanation_caption_placement": qd.get("explanation_caption_placement") or "above",
                "explanation_caption_side_flow": qd.get("explanation_caption_side_flow") or "horizontal",
                "explanation_caption_color": qd.get("explanation_caption_color") or "#0f172a",
                "explanation_caption_bold": bool(qd.get("explanation_caption_bold", False)),
                "explanation_caption_italic": bool(qd.get("explanation_caption_italic", False)),
                "explanation_caption_font_pt": float(qd.get("explanation_caption_font_pt") or 9.0),
                "explanation_caption_box_enabled": bool(qd.get("explanation_caption_box_enabled", False)),
                "explanation_caption_box_color": qd.get("explanation_caption_box_color") or "#f1f5f9",
                "explanation_caption_box_corner": qd.get("explanation_caption_box_corner") or "rounded",
                "explanation_caption_box_width": qd.get("explanation_caption_box_width") or "full",
            })
        s_list = []
        for s in sections:
            sd = s if isinstance(s, dict) else (s.model_dump() if hasattr(s, "model_dump") else s)
            if isinstance(sd, dict):
                s_list.append(sd)
        return export_from_payload(
            q_list,
            pdf_items,
            opts,
            sections=s_list,
            layout_y_top_overrides=layout_y_top_overrides,
        )

    def compute_layout_from_questions(
        self,
        title: str,
        school_name: str,
        include_answer_key: bool,
        columns: int,
        question_gap_mm: float,
        question_gap_min_mm: float = 12.0,
        answer_key_mode: str = "per_page",
        auto_compact_spacing: bool = True,
        page_preset: str = "A4",
        page_width_mm: float = 210.0,
        page_height_mm: float = 297.0,
        orientation: str = "portrait",
        margin_top_mm: float = 15.0,
        margin_bottom_mm: float = 15.0,
        margin_left_mm: float = 15.0,
        margin_right_mm: float = 15.0,
        header_style_id: str = "style3",
        theme_color: str = "#AECBFA",
        questions: list | None = None,
        sections: list | None = None,
        pdf_items: list | None = None,
        include_description: bool = False,
        test_description: str = "",
        description_column_count: int = 1,
        description_texts: list | None = None,
        description_column_dividers: bool = False,
        add_text_on_line: bool = False,
        center_line_text: str = "",
        center_line_bold: bool = False,
        center_line_italic: bool = False,
        center_line_text_direction: str = "up",
        watermark_enabled: bool = False,
        watermark_mode: str = "text",
        watermark_text: str = "",
        watermark_text_opacity_pct: int = 20,
        watermark_text_size_pct: int = 90,
        watermark_text_angle_deg: int = 45,
        watermark_text_color: str = "#000000",
        watermark_image_base64: str | None = None,
        watermark_image_opacity_pct: int = 15,
        watermark_image_size_pct: int = 50,
        written_paper_header: bool = False,
        written_paper_title: str | None = None,
        exam_type: str | None = None,
        class_section: str | None = None,
        group: str | None = None,
        teacher_names: list | None = None,
        principal_name: str | None = None,
        written_paper_field_lines: dict | None = None,
        written_paper_field_hidden: dict | None = None,
        written_paper_field_labels: dict | None = None,
        layout_y_top_overrides: list | None = None,
    ) -> list:
        """Compute layout positions for preview - no PDF generation."""
        ak_mode = (answer_key_mode or "per_page").strip().lower()
        if written_paper_header and include_answer_key:
            ak_mode = "separate_page"
        opts = ExportOptions(
            test_title=title,
            school_name=school_name,
            answer_key_enabled=include_answer_key,
            answer_key_mode=ak_mode,
            columns=columns,
            question_gap_mm=question_gap_mm,
            question_gap_min_mm=question_gap_min_mm,
            auto_compact_spacing=auto_compact_spacing,
            page_preset=page_preset,
            page_width_mm=page_width_mm,
            page_height_mm=page_height_mm,
            orientation=orientation,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            header_style_id=header_style_id,
            theme_color=theme_color,
            include_description=include_description,
            test_description=test_description or "",
            description_column_count=description_column_count or 1,
            description_texts=description_texts or [],
            description_column_dividers=bool(description_column_dividers),
            center_line_enabled=add_text_on_line,
            center_line_text=center_line_text or "",
            center_line_bold=center_line_bold,
            center_line_italic=center_line_italic,
            center_line_color="",
            center_line_text_direction=center_line_text_direction or "up",
            watermark_enabled=watermark_enabled,
            watermark_mode=watermark_mode or "text",
            watermark_text=watermark_text or "",
            watermark_text_opacity_pct=watermark_text_opacity_pct,
            watermark_text_size_pct=watermark_text_size_pct,
            watermark_text_angle_deg=watermark_text_angle_deg,
            watermark_text_color=watermark_text_color or "#000000",
            watermark_image_base64=watermark_image_base64,
            watermark_image_opacity_pct=watermark_image_opacity_pct,
            watermark_image_size_pct=watermark_image_size_pct,
            written_paper_header=written_paper_header,
            written_paper_title=written_paper_title,
            exam_type=exam_type,
            class_section=class_section,
            group=group,
            teacher_names=teacher_names or [],
            principal_name=principal_name,
            written_paper_field_lines=written_paper_field_lines,
            written_paper_field_hidden=written_paper_field_hidden,
            written_paper_field_labels=written_paper_field_labels,
        )
        q_list = []
        for q in questions:
            if isinstance(q, dict):
                qd = q
            else:
                qd = q.model_dump() if hasattr(q, "model_dump") else (q.dict() if hasattr(q, "dict") else {})
            crop = qd.get("crop", {})
            if hasattr(crop, "model_dump"):
                crop = crop.model_dump()
            elif not isinstance(crop, dict):
                crop = {"x": 0, "y": 0, "width": 1, "height": 1}
            q_list.append({
                "id": qd.get("id", ""),
                "pdf_id": qd.get("pdf_id", ""),
                "page_number": qd.get("page_number", 1),
                "crop": crop,
                "answer_key": qd.get("answer_key", ""),
                "order_index": qd.get("order_index", 0),
                "content_type": qd.get("content_type") or "question",
                "remove_background": qd.get("remove_background", False),
                "image_base64": qd.get("image_base64"),
                "custom_gap_mm": qd.get("custom_gap_mm"),
                "display_scale": qd.get("display_scale"),
                "explanation_caption_enabled": bool(qd.get("explanation_caption_enabled", False)),
                "explanation_caption_text": qd.get("explanation_caption_text") or "",
                "explanation_caption_align": qd.get("explanation_caption_align") or "left",
                "explanation_caption_placement": qd.get("explanation_caption_placement") or "above",
                "explanation_caption_side_flow": qd.get("explanation_caption_side_flow") or "horizontal",
                "explanation_caption_color": qd.get("explanation_caption_color") or "#0f172a",
                "explanation_caption_bold": bool(qd.get("explanation_caption_bold", False)),
                "explanation_caption_italic": bool(qd.get("explanation_caption_italic", False)),
                "explanation_caption_font_pt": float(qd.get("explanation_caption_font_pt") or 9.0),
                "explanation_caption_box_enabled": bool(qd.get("explanation_caption_box_enabled", False)),
                "explanation_caption_box_color": qd.get("explanation_caption_box_color") or "#f1f5f9",
                "explanation_caption_box_corner": qd.get("explanation_caption_box_corner") or "rounded",
                "explanation_caption_box_width": qd.get("explanation_caption_box_width") or "full",
            })
        s_list = []
        for s in (sections or []):
            sd = s if isinstance(s, dict) else (s.model_dump() if hasattr(s, "model_dump") else s)
            if isinstance(sd, dict):
                s_list.append(sd)
        layout = compute_layout_from_payload(
            q_list,
            pdf_items,
            opts,
            sections=s_list,
            layout_y_top_overrides=layout_y_top_overrides,
        )
        w_pt, h_pt = page_size_pt(opts)
        return layout, w_pt, h_pt

    @staticmethod
    def _render_crop_png(
        path: Path,
        page_number: int,
        norm_x: float,
        norm_y: float,
        norm_w: float,
        norm_h: float,
    ) -> bytes:
        """Crop using normalized coords (0..1)."""
        with fitz.open(path) as doc:
            page = doc.load_page(page_number - 1)
            rect = page.rect
            x_pt = norm_x * rect.width
            y_pt = norm_y * rect.height
            w_pt = norm_w * rect.width
            h_pt = norm_h * rect.height
            clip = fitz.Rect(x_pt, y_pt, x_pt + w_pt, y_pt + h_pt)
            pix = page.get_pixmap(clip=clip, alpha=False)
            return pix.tobytes("png")
