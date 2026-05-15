from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator

class PdfItem(BaseModel):
    id: str
    filename: str
    path: str
    page_count: int
    created_at: datetime


class CropBox(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class QuestionItem(BaseModel):
    id: str
    pdf_id: str = ""  # Empty when image_path (local PDF mode)
    page_number: int = Field(ge=0, default=0)  # 0 when image_path
    crop: CropBox
    answer_key: Optional[str] = ""
    order_index: int = Field(ge=0)
    # question | explanation — explanation: numara ve cevap anahtarı yok
    content_type: str = Field(default="question")
    remove_background: bool = False
    image_path: Optional[str] = None  # Set when from local PDF mode
    # Açıklama bloğu: isteğe bağlı metin (PDF’te konum/hizalama)
    explanation_caption_enabled: bool = False
    explanation_caption_text: str = ""
    explanation_caption_align: str = Field(default="left")
    explanation_caption_placement: str = Field(default="above")
    explanation_caption_side_flow: str = Field(default="horizontal")
    explanation_caption_color: str = Field(default="#0f172a")
    explanation_caption_bold: bool = False
    explanation_caption_italic: bool = False
    explanation_caption_font_pt: float = Field(default=9.0, ge=6.0, le=16.0)
    explanation_caption_box_enabled: bool = False
    explanation_caption_box_color: str = Field(default="#f1f5f9")
    explanation_caption_box_corner: str = Field(default="rounded")
    explanation_caption_box_width: str = Field(default="full")

    @field_validator("content_type", mode="before")
    @classmethod
    def _normalize_content_type(cls, v: Any) -> str:
        s = str(v or "question").strip().lower()
        return s if s in ("question", "explanation") else "question"

    @field_validator("explanation_caption_box_corner", mode="before")
    @classmethod
    def _norm_cap_box_corner(cls, v: Any) -> str:
        s = str(v or "rounded").strip().lower()
        return s if s in ("rounded", "sharp") else "rounded"

    @field_validator("explanation_caption_box_width", mode="before")
    @classmethod
    def _norm_cap_box_width(cls, v: Any) -> str:
        s = str(v or "full").strip().lower()
        return s if s in ("full", "tight") else "full"

    @field_validator("explanation_caption_align", mode="before")
    @classmethod
    def _norm_cap_align(cls, v: Any) -> str:
        s = str(v or "left").strip().lower()
        return s if s in ("left", "center", "right") else "left"

    @field_validator("explanation_caption_placement", mode="before")
    @classmethod
    def _norm_cap_place(cls, v: Any) -> str:
        s = str(v or "above").strip().lower()
        return s if s in ("above", "below", "left", "right") else "above"

    @field_validator("explanation_caption_side_flow", mode="before")
    @classmethod
    def _norm_cap_side_flow(cls, v: Any) -> str:
        s = str(v or "horizontal").strip().lower()
        return s if s in ("horizontal", "vertical_up") else "horizontal"


class CreateQuestionRequest(BaseModel):
    pdf_id: str
    page_number: int = Field(ge=1)
    crop: CropBox
    answer_key: Optional[str] = ""
    remove_background: bool = False


class UpdateAnswerRequest(BaseModel):
    answer_key: str


class UpdateRemoveBackgroundRequest(BaseModel):
    remove_background: bool


class UpdateCropRequest(BaseModel):
    crop: CropBox


class UpdateContentTypeRequest(BaseModel):
    content_type: str = Field(default="question")

    @field_validator("content_type", mode="before")
    @classmethod
    def _normalize_content_type(cls, v: Any) -> str:
        s = str(v or "question").strip().lower()
        if s not in ("question", "explanation"):
            raise ValueError("content_type must be 'question' or 'explanation'")
        return s


class UpdateExplanationCaptionRequest(BaseModel):
    explanation_caption_enabled: bool = False
    explanation_caption_text: str = ""
    explanation_caption_align: str = Field(default="left")
    explanation_caption_placement: str = Field(default="above")
    explanation_caption_side_flow: str = Field(default="horizontal")
    explanation_caption_color: str = Field(default="#0f172a")
    explanation_caption_bold: bool = False
    explanation_caption_italic: bool = False
    explanation_caption_font_pt: float = Field(default=9.0, ge=6.0, le=16.0)
    explanation_caption_box_enabled: bool = False
    explanation_caption_box_color: str = Field(default="#f1f5f9")
    explanation_caption_box_corner: str = Field(default="rounded")
    explanation_caption_box_width: str = Field(default="full")

    @field_validator("explanation_caption_align", mode="before")
    @classmethod
    def _norm_ec_align(cls, v: Any) -> str:
        s = str(v or "left").strip().lower()
        if s not in ("left", "center", "right"):
            raise ValueError("align must be left, center, or right")
        return s

    @field_validator("explanation_caption_box_corner", mode="before")
    @classmethod
    def _norm_ec_box_corner(cls, v: Any) -> str:
        s = str(v or "rounded").strip().lower()
        if s not in ("rounded", "sharp"):
            raise ValueError("box_corner must be rounded or sharp")
        return s

    @field_validator("explanation_caption_box_width", mode="before")
    @classmethod
    def _norm_ec_box_width(cls, v: Any) -> str:
        s = str(v or "full").strip().lower()
        if s not in ("full", "tight"):
            raise ValueError("box_width must be full or tight")
        return s

    @field_validator("explanation_caption_placement", mode="before")
    @classmethod
    def _norm_ec_place(cls, v: Any) -> str:
        s = str(v or "above").strip().lower()
        if s not in ("above", "below", "left", "right"):
            raise ValueError("placement must be above, below, left, or right")
        return s

    @field_validator("explanation_caption_side_flow", mode="before")
    @classmethod
    def _norm_ec_side_flow(cls, v: Any) -> str:
        s = str(v or "horizontal").strip().lower()
        if s not in ("horizontal", "vertical_up"):
            raise ValueError("side_flow must be horizontal or vertical_up")
        return s


class CreateFromLocalPdfRequest(BaseModel):
    """Local PDF mode: client sends cropped image, no server PDF."""
    image_base64: str  # PNG base64 (with or without data:image/png;base64, prefix)
    page: int = Field(ge=1)
    selection: CropBox  # Normalized rect 0..1
    answer_key: Optional[str] = ""
    remove_background: bool = False


class ReorderQuestionsRequest(BaseModel):
    ordered_ids: List[str]


class DraftPayload(BaseModel):
    """Matches desktop Draft: selections + export_settings + test_info."""
    name: str
    questions: List[QuestionItem]
    notes: Optional[str] = ""
    export_settings: Optional[Dict[str, Any]] = None
    test_info: Optional[Dict[str, str]] = None


class DraftInfo(BaseModel):
    name: str
    path: str
    updated_at: datetime


class ExportRequest(BaseModel):
    """Simple and extended export - desktop ExportOptions parity."""
    title: str = "Exported Test"
    school_name: str = ""
    include_answer_key: bool = True
    columns: int = 2
    question_gap_mm: float = 35.0
    page_preset: str = "A4"
    header_style_id: str = "style3"
    theme_color: str = "#AECBFA"


class QuestionForExport(BaseModel):
    """Question with optional image_base64 for cache-only export (no persist)."""
    id: str
    pdf_id: str = ""
    page_number: int = 0
    crop: CropBox
    answer_key: str = ""
    order_index: int = 0
    content_type: str = Field(default="question")
    remove_background: bool = False
    image_base64: Optional[str] = None  # PNG base64 (no data URL prefix)
    custom_gap_mm: Optional[float] = None  # Soru bazlı boşluk (mm), yoksa genel kullanılır
    display_scale: Optional[float] = None  # Soru görsel ölçeği (0.5..2)
    explanation_caption_enabled: bool = False
    explanation_caption_text: str = ""
    explanation_caption_align: str = Field(default="left")
    explanation_caption_placement: str = Field(default="above")
    explanation_caption_side_flow: str = Field(default="horizontal")
    explanation_caption_color: str = Field(default="#0f172a")
    explanation_caption_bold: bool = False
    explanation_caption_italic: bool = False
    explanation_caption_font_pt: float = Field(default=9.0, ge=6.0, le=16.0)
    explanation_caption_box_enabled: bool = False
    explanation_caption_box_color: str = Field(default="#f1f5f9")
    explanation_caption_box_corner: str = Field(default="rounded")
    explanation_caption_box_width: str = Field(default="full")

    @field_validator("content_type", mode="before")
    @classmethod
    def _normalize_export_content_type(cls, v: Any) -> str:
        s = str(v or "question").strip().lower()
        return s if s in ("question", "explanation") else "question"

    @field_validator("explanation_caption_box_corner", mode="before")
    @classmethod
    def _norm_ef_box_corner(cls, v: Any) -> str:
        s = str(v or "rounded").strip().lower()
        return s if s in ("rounded", "sharp") else "rounded"

    @field_validator("explanation_caption_box_width", mode="before")
    @classmethod
    def _norm_ef_box_width(cls, v: Any) -> str:
        s = str(v or "full").strip().lower()
        return s if s in ("full", "tight") else "full"

    @field_validator("explanation_caption_align", mode="before")
    @classmethod
    def _norm_ef_align(cls, v: Any) -> str:
        s = str(v or "left").strip().lower()
        return s if s in ("left", "center", "right") else "left"

    @field_validator("explanation_caption_placement", mode="before")
    @classmethod
    def _norm_ef_place(cls, v: Any) -> str:
        s = str(v or "above").strip().lower()
        return s if s in ("above", "below", "left", "right") else "above"

    @field_validator("explanation_caption_side_flow", mode="before")
    @classmethod
    def _norm_ef_side_flow(cls, v: Any) -> str:
        s = str(v or "horizontal").strip().lower()
        return s if s in ("horizontal", "vertical_up") else "horizontal"


class LayoutYTopOverride(BaseModel):
    """Önizlemede manuel dikey konum — export/layout çıktısında y_top_pt ezilir."""
    order_index: int = Field(ge=0)
    y_top_pt: float


class SectionRangeForExport(BaseModel):
    """Bölüm aralığı - PDF'te bölüm başlığı çizimi için."""
    start_idx: int = 0
    end_idx: int = 0
    title: str = ""
    restart_numbering: bool = False
    start_new_page: bool = False
    fill_color: str = "#FFFFFF"
    text_color: str = "#000000"
    line_color: str = "#000000"
    font_pt: float = 12.0


class ExportWithQuestionsRequest(BaseModel):
    """Export with questions payload - no persist, PDF from cache."""
    title: str = "Exported Test"
    school_name: str = ""
    include_answer_key: bool = True
    answer_key_mode: str = Field(
        default="per_page",
        validation_alias=AliasChoices("answer_key_mode", "answerKeyMode"),
    )  # per_page | separate_page | end_of_test
    columns: int = 2
    question_gap_mm: float = 35.0  # preferred spacing (mm)
    question_gap_min_mm: float = 12.0  # min spacing when compacting (mm)
    auto_compact_spacing: bool = True  # reduce spacing within min..preferred before next column
    page_preset: str = "A4"
    page_width_mm: float = 210.0  # CUSTOM preset için
    page_height_mm: float = 297.0  # CUSTOM preset için
    orientation: str = "portrait"  # portrait | landscape (Dikey | Yatay)
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 15.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0
    header_style_id: str = "style3"
    theme_color: str = "#AECBFA"
    quality: str = "high"  # normal:288dpi | high:432dpi | best:576dpi
    questions: List[QuestionForExport]
    sections: Optional[List[SectionRangeForExport]] = None  # Bölüm başlıkları (PDF'te görünür)
    skip_images: bool = False  # Layout API: görselleri atla (canlı önizleme için)
    include_description: bool = False  # Test ile ilgili açıklama ekle
    test_description: str = ""  # Açıklama metni (tek sütun geriye uyum)
    description_column_count: int = 1  # Sütun sayısı (1–3)
    description_texts: Optional[List[str]] = None  # Sütun bazlı metinler (HTML)
    description_column_dividers: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "description_column_dividers",
            "descriptionColumnDividers",
        ),
    )  # Çok sütunda açıklama kutusu içi dikey ayırıcı çizgiler
    add_text_on_line: bool = False  # Çizgi üzerine yazı ekle
    center_line_text: str = ""  # Çizgi üzeri metin
    center_line_bold: bool = False
    center_line_italic: bool = False
    center_line_text_direction: str = "up"  # up | down
    # Filigran
    watermark_enabled: bool = False
    watermark_mode: str = "text"  # text | image
    watermark_text: str = ""
    watermark_text_opacity_pct: int = 20
    watermark_text_size_pct: int = 90
    watermark_text_angle_deg: int = 45
    watermark_text_color: str = "#000000"
    watermark_image_base64: Optional[str] = None  # PNG/JPEG base64
    watermark_image_opacity_pct: int = 15
    watermark_image_size_pct: int = 50
    # Yazılı Kağıdı
    written_paper_header: bool = False  # Okul, sınıf, sınav türü formatında başlık
    written_paper_title: Optional[str] = None  # Tam başlık metni (yoksa title ile oluşturulur)
    # Başlık altı sütun satırları: ad_soyad, numara, puan, sinif, grup -> metin listesi
    written_paper_field_lines: Optional[Dict[str, List[str]]] = None
    # True ise ilgili alan PDF başlığında çizilmez (modal Gizle)
    written_paper_field_hidden: Optional[Dict[str, bool]] = None
    # Özel etiket metinleri (boş anahtar = varsayılan); sol blokta ':' eklenir, PUAN kutusu üstünde olduğu gibi
    written_paper_field_labels: Optional[Dict[str, str]] = Field(
        default=None,
        validation_alias=AliasChoices(
            "written_paper_field_labels",
            "writtenPaperFieldLabels",
        ),
    )
    exam_type: Optional[str] = None  # Sınav türü
    footer_nav_page_turn_texts: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "footer_nav_page_turn_texts",
            "footerNavPageTurnTexts",
        ),
    )  # False: test kağıdı — alt sağ "Diğer sayfaya geçiniz" / "TEST BİTTİ" yok; deneme için True
    class_section: Optional[str] = None  # Sınıf/Şube
    group: Optional[str] = None  # Grup (A, B vb.)
    teacher_names: Optional[List[Dict[str, str]]] = None  # [{name, title}, ...] sayfa sonu imza
    principal_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("principal_name", "principalName"),
    )  # Yazılı son sayfa: okul müdürü adı soyadı
    layout_y_top_overrides: Optional[List[LayoutYTopOverride]] = Field(
        default=None,
        validation_alias=AliasChoices(
            "layout_y_top_overrides",
            "layoutYTopOverrides",
        ),
    )

    @field_validator("written_paper_field_labels", mode="before")
    @classmethod
    def _coerce_written_field_labels(cls, v: object) -> Optional[Dict[str, str]]:
        if v is None:
            return None
        if isinstance(v, dict):
            out: Dict[str, str] = {}
            for k, val in v.items():
                sk = str(k).strip()
                if not sk:
                    continue
                if val is None:
                    out[sk] = ""
                else:
                    out[sk] = str(val).strip()[:80]
            return out
        return None
