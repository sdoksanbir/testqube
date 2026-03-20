from pathlib import Path
from typing import List

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.core.config import EXPORT_DIR
from app.models.schemas import PdfItem, QuestionItem
from app.services.desktop_export import ExportOptions, export_desktop_style


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
            c.drawImage(str(img_path), 40, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True)
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
