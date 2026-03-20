from app.services.draft_service import DraftService
from app.services.export_service import ExportService
from app.services.pdf_service import PdfService
from app.services.question_service import QuestionService

pdf_service = PdfService()
question_service = QuestionService()
draft_service = DraftService()
export_service = ExportService()
