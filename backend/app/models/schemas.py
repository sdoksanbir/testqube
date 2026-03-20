from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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
    pdf_id: str
    page_number: int = Field(ge=1)
    crop: CropBox
    answer_key: Optional[str] = ""
    order_index: int = Field(ge=0)


class CreateQuestionRequest(BaseModel):
    pdf_id: str
    page_number: int = Field(ge=1)
    crop: CropBox
    answer_key: Optional[str] = ""


class UpdateAnswerRequest(BaseModel):
    answer_key: str


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
