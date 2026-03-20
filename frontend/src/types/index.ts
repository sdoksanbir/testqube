/** Shared types aligned with backend schemas (backend/app/models/schemas.py) */

export type AnswerOption = "A" | "B" | "C" | "D" | "E";

/**
 * Crop coordinates. Uses normalized 0..1 format (desktop Selection.norm parity).
 * Zoom-invariant: backend converts to PDF points when cropping.
 */
export interface CropBox {
  x: number;   // 0..1
  y: number;   // 0..1
  width: number;
  height: number;
}

/** Normalized rect 0..1 (desktop Selection.norm parity) */
export interface NormRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PdfItem {
  id: string;
  filename: string;
  path: string;
  page_count: number;
  created_at: string;
}

export interface QuestionItem {
  id: string;
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key: string;
  order_index: number;
}

export interface CreateQuestionRequest {
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key?: string;
}

export interface DraftPayload {
  name: string;
  questions: QuestionItem[];
  notes?: string;
  export_settings?: Record<string, unknown>;
  test_info?: Record<string, string>;
}

export interface DraftInfo {
  name: string;
  path: string;
  updated_at: string;
}
