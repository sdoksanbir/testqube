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

/** Soru numaralı blok | numarasız açıklama/yönerge bloğu (PDF ile aynı) */
export type QuestionContentType = "question" | "explanation";

export type ExplanationCaptionAlign = "left" | "center" | "right";
export type ExplanationCaptionPlacement = "above" | "below" | "left" | "right";
/** Solda/sağda: yatay satırlar veya dikey (yukarı okunur, PDF’te 90°). */
export type ExplanationCaptionSideFlow = "horizontal" | "vertical_up";
export type ExplanationCaptionBoxCorner = "rounded" | "sharp";
/** Kutu: tüm satır genişliği | yalnızca metin genişliği (+ yan padding). */
export type ExplanationCaptionBoxWidth = "full" | "tight";

/** Soru görseli üzerine eklenen düz metin katmanı (görüntü pikseli, sol-üst köşe). */
export type QuestionImageTextOverlay = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  fontSizePx: number;
};

export interface QuestionItem {
  id: string;
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key: string;
  order_index: number;
  /** Varsayılan: question. explanation = numara yok, cevap anahtarına girmez. */
  content_type?: QuestionContentType;
  /** Açıklama bloğunda isteğe bağlı metin (kapalıyken PDF’te başlık/metin yok). */
  explanation_caption_enabled?: boolean;
  explanation_caption_text?: string;
  explanation_caption_align?: ExplanationCaptionAlign;
  explanation_caption_placement?: ExplanationCaptionPlacement;
  explanation_caption_side_flow?: ExplanationCaptionSideFlow;
  explanation_caption_color?: string;
  explanation_caption_bold?: boolean;
  explanation_caption_italic?: boolean;
  explanation_caption_font_pt?: number;
  explanation_caption_box_enabled?: boolean;
  explanation_caption_box_color?: string;
  explanation_caption_box_corner?: ExplanationCaptionBoxCorner;
  explanation_caption_box_width?: ExplanationCaptionBoxWidth;
  remove_background?: boolean;
  /** Set when from local PDF mode (persisted) */
  image_path?: string;
  /** Cache-only: base64 PNG for pending local questions (not persisted) */
  image_base64?: string;
  /** Metin katmanları varken: silgi/arka plan öncesi düz görüntü (yalnızca yerel/taslak). */
  image_underlay_b64?: string;
  /** Görüntüye eklenen metin kutuları; birleşik önizleme image_base64’te tutulur. */
  image_text_overlays?: QuestionImageTextOverlay[];
  /** Cache-only: local PDF id for pending local questions (crop sayfasına gitmek için) */
  localPdfId?: string;
  /** Kağıt hazırla: Soru görsel boyut ölçeği (0.5..2, 1=varsayılan) - original-desktop display_scale */
  display_scale?: number;
  /** Kağıt hazırla: Bu sorudan sonra özel boşluk (mm), yoksa genel questionGapMm kullanılır */
  custom_gap_mm?: number;
}

export interface CreateQuestionRequest {
  pdf_id: string;
  page_number: number;
  crop: CropBox;
  answer_key?: string;
  remove_background?: boolean;
}

/** Local PDF mode: client sends cropped image, no server PDF. */
export interface CreateFromLocalPdfRequest {
  image_base64: string;
  page: number;
  selection: CropBox;
  answer_key?: string;
  remove_background?: boolean;
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

/** Bölüm bilgisi - original-desktop SectionRange parity */
export interface SectionRange {
  start_idx: number;
  end_idx: number;
  title: string;
  restart_numbering?: boolean;
  start_new_page?: boolean;
  fill_color?: string;
  text_color?: string;
  line_color?: string;
  font_pt?: number;
}
