import io
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import fitz
from fastapi import UploadFile
from PIL import Image

from app.core.config import UPLOAD_DIR
from app.models.schemas import PdfItem

UUID_PREFIX = re.compile(r"^([a-f0-9-]{36})_(.+)$")


class PdfService:
    """
    Migration decision:
    - PDF-heavy logic stays in Python backend for reuse from desktop app modules.
    - Frontend only requests rendered/cropped results and metadata.
    """

    def __init__(self) -> None:
        self._pdfs: Dict[str, PdfItem] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load persisted PDFs from UPLOAD_DIR on startup."""
        if not UPLOAD_DIR.exists():
            return
        for path in UPLOAD_DIR.glob("*.pdf"):
            match = UUID_PREFIX.match(path.name)
            if match:
                pdf_id, filename = match.group(1), match.group(2)
                try:
                    with fitz.open(path) as doc:
                        page_count = doc.page_count
                    stat = path.stat()
                    self._pdfs[pdf_id] = PdfItem(
                        id=pdf_id,
                        filename=filename,
                        path=str(path),
                        page_count=page_count,
                        created_at=datetime.fromtimestamp(stat.st_mtime),
                    )
                except Exception:
                    pass

    async def save_uploads(self, files: List[UploadFile]) -> List[PdfItem]:
        created: List[PdfItem] = []
        for upload in files:
            pdf_id = str(uuid.uuid4())
            safe_name = f"{pdf_id}_{upload.filename}"
            file_path = UPLOAD_DIR / safe_name
            content = await upload.read()
            file_path.write_bytes(content)

            with fitz.open(file_path) as doc:
                page_count = doc.page_count

            item = PdfItem(
                id=pdf_id,
                filename=upload.filename or "unnamed.pdf",
                path=str(file_path),
                page_count=page_count,
                created_at=datetime.utcnow(),
            )
            self._pdfs[pdf_id] = item
            created.append(item)
        return created

    def list_pdfs(self) -> List[PdfItem]:
        return sorted(self._pdfs.values(), key=lambda x: x.created_at, reverse=True)

    def delete_pdf(self, pdf_id: str) -> None:
        item = self.get_pdf(pdf_id)
        path = Path(item.path)
        if path.exists():
            path.unlink()
        del self._pdfs[pdf_id]

    def get_pdf(self, pdf_id: str) -> PdfItem:
        item = self._pdfs.get(pdf_id)
        if not item:
            raise KeyError(f"PDF not found: {pdf_id}")
        return item

    def render_page_png(self, pdf_id: str, page_number: int, zoom: float = 2.0) -> bytes:
        item = self.get_pdf(pdf_id)
        if page_number < 1:
            raise ValueError("Page number must start from 1.")

        path = Path(item.path)
        with fitz.open(path) as doc:
            if page_number > doc.page_count:
                raise ValueError("Page out of range.")
            page = doc.load_page(page_number - 1)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png")

    def remove_background_from_png_bytes(self, png_bytes: bytes) -> bytes:
        """Make near-white/light pixels fully transparent. Public API."""
        return self._remove_background_from_png(png_bytes)

    def _remove_background_from_png(self, png_bytes: bytes) -> bytes:
        """Make near-white/light background pixels fully transparent (alpha=0)."""
        img = Image.open(io.BytesIO(png_bytes))
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        pixels = img.load()
        w, h = img.size
        threshold = 220

        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                avg = (r + g + b) / 3
                if avg >= threshold:
                    pixels[x, y] = (r, g, b, 0)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def crop_page_png(
        self,
        pdf_id: str,
        page_number: int,
        norm_x: float,
        norm_y: float,
        norm_w: float,
        norm_h: float,
        remove_background: bool = False,
    ) -> bytes:
        """Crop page region using normalized coordinates (0..1).
        If remove_background, whitens near-white pixels.
        """
        item = self.get_pdf(pdf_id)
        path = Path(item.path)
        with fitz.open(path) as doc:
            page = doc.load_page(page_number - 1)
            rect = page.rect
            x_pt = norm_x * rect.width
            y_pt = norm_y * rect.height
            w_pt = norm_w * rect.width
            h_pt = norm_h * rect.height
            clip = fitz.Rect(x_pt, y_pt, x_pt + w_pt, y_pt + h_pt)
            pix = page.get_pixmap(clip=clip, alpha=False)
            png_bytes = pix.tobytes("png")

        if remove_background:
            png_bytes = self._remove_background_from_png(png_bytes)
        return png_bytes
