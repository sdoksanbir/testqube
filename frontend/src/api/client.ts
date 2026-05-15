const API_BASE = "/api";

async function handleRes<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  if (res.status === 204 || res.headers.get("content-type")?.includes("image")) {
    return res as unknown as T;
  }
  return res.json();
}

export const api = {
  pdfs: {
    list: () => fetch(`${API_BASE}/pdfs`).then((r) => handleRes<{ items: import("../types").PdfItem[] }>(r)),
    upload: (files: File[]) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      return fetch(`${API_BASE}/pdfs/upload`, { method: "POST", body: fd }).then((r) =>
        handleRes<{ items: import("../types").PdfItem[] }>(r)
      );
    },
    delete: (pdfId: string) =>
      fetch(`${API_BASE}/pdfs/${pdfId}`, { method: "DELETE" }).then((r) =>
        handleRes<{ ok: boolean }>(r)
      ),
    pageImageUrl: (pdfId: string, pageNumber: number, opts?: { dpi?: number; zoom?: number }) => {
      const params = new URLSearchParams();
      if (opts?.dpi != null) params.set("dpi", String(opts.dpi));
      else if (opts?.zoom != null) params.set("zoom", String(opts.zoom));
      else params.set("dpi", "200");
      return `${API_BASE}/pdfs/${pdfId}/pages/${pageNumber}/image?${params}`;
    },
  },
  questions: {
    list: () => fetch(`${API_BASE}/questions`).then((r) => handleRes<{ items: import("../types").QuestionItem[] }>(r)),
    create: (payload: import("../types").CreateQuestionRequest) =>
      fetch(`${API_BASE}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    createFromLocalPdf: (payload: import("../types").CreateFromLocalPdfRequest) =>
      fetch(`${API_BASE}/questions/from-local-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    updateAnswer: (questionId: string, answerKey: string) =>
      fetch(`${API_BASE}/questions/${questionId}/answer`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer_key: answerKey }),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    updateRemoveBackground: (questionId: string, removeBackground: boolean) =>
      fetch(`${API_BASE}/questions/${questionId}/remove-background`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remove_background: removeBackground }),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    updateCrop: (questionId: string, crop: import("../types").CropBox) =>
      fetch(`${API_BASE}/questions/${questionId}/crop`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ crop }),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    updateContentType: (questionId: string, contentType: import("../types").QuestionContentType) =>
      fetch(`${API_BASE}/questions/${questionId}/content-type`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_type: contentType }),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    updateExplanationCaption: (
      questionId: string,
      body: {
        explanation_caption_enabled: boolean;
        explanation_caption_text: string;
        explanation_caption_align: import("../types").ExplanationCaptionAlign;
        explanation_caption_placement: import("../types").ExplanationCaptionPlacement;
        explanation_caption_side_flow: import("../types").ExplanationCaptionSideFlow;
        explanation_caption_color: string;
        explanation_caption_bold: boolean;
        explanation_caption_italic: boolean;
        explanation_caption_font_pt: number;
        explanation_caption_box_enabled: boolean;
        explanation_caption_box_color: string;
        explanation_caption_box_corner: import("../types").ExplanationCaptionBoxCorner;
        explanation_caption_box_width: import("../types").ExplanationCaptionBoxWidth;
      }
    ) =>
      fetch(`${API_BASE}/questions/${questionId}/explanation-caption`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((r) => handleRes<import("../types").QuestionItem>(r)),
    reorder: (orderedIds: string[]) =>
      fetch(`${API_BASE}/questions/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ordered_ids: orderedIds }),
      }).then((r) => handleRes<{ items: import("../types").QuestionItem[] }>(r)),
    delete: (questionId: string) =>
      fetch(`${API_BASE}/questions/${questionId}`, { method: "DELETE" }).then((r) => handleRes<{ ok: boolean }>(r)),
    imageUrl: (questionId: string) => `${API_BASE}/questions/${questionId}/image`,
  },
  drafts: {
    list: () => fetch(`${API_BASE}/drafts`).then((r) => handleRes<{ items: import("../types").DraftInfo[] }>(r)),
    save: (payload: import("../types").DraftPayload) =>
      fetch(`${API_BASE}/drafts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => handleRes<import("../types").DraftInfo>(r)),
    load: (name: string) =>
      fetch(`${API_BASE}/drafts/${encodeURIComponent(name)}`).then((r) =>
        handleRes<import("../types").DraftPayload>(r)
      ),
  },
  exports: {
    fromQuestions: (payload: {
      title: string;
      school_name: string;
      include_answer_key: boolean;
      answer_key_mode?: "per_page" | "separate_page" | "end_of_test";
      columns: number;
      question_gap_mm: number;
      question_gap_min_mm?: number;
      auto_compact_spacing?: boolean;
      page_preset: string;
      page_width_mm?: number;
      page_height_mm?: number;
      orientation?: string;
      margin_top_mm?: number;
      margin_bottom_mm?: number;
      margin_left_mm?: number;
      margin_right_mm?: number;
      header_style_id: string;
      theme_color: string;
      quality?: "normal" | "high" | "best";
      questions: import("../types").QuestionItem[];
      sections?: import("../types").SectionRange[];
      include_description?: boolean;
      description_column_count?: number;
      description_texts?: string[];
      description_column_dividers?: boolean;
      add_text_on_line?: boolean;
      center_line_text?: string;
      center_line_bold?: boolean;
      center_line_italic?: boolean;
      center_line_text_direction?: string;
      watermark_enabled?: boolean;
      watermark_mode?: string;
      watermark_text?: string;
      watermark_text_opacity_pct?: number;
      watermark_text_size_pct?: number;
      watermark_text_angle_deg?: number;
      watermark_text_color?: string;
      watermark_image_base64?: string | null;
      watermark_image_opacity_pct?: number;
      watermark_image_size_pct?: number;
      written_paper_header?: boolean;
      written_paper_title?: string;
      written_paper_field_lines?: Record<string, string[]>;
      written_paper_field_hidden?: Record<string, boolean>;
      written_paper_field_labels?: Record<string, string>;
      exam_type?: string;
      /** false: test kağıdı — alt sağ footer uyarı metinleri PDF’te yok; deneme için true */
      footer_nav_page_turn_texts?: boolean;
      class_section?: string;
      group?: string;
      teacher_names?: { name: string; title: string }[];
      principal_name?: string;
      layout_y_top_overrides?: { order_index: number; y_top_pt: number }[];
    }) =>
      fetch(`${API_BASE}/exports/from-questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({ detail: r.statusText }));
          throw new Error(err.detail ?? "Export failed");
        }
        return r.blob();
      }),
    layout: (payload: {
      title: string;
      school_name: string;
      include_answer_key: boolean;
      answer_key_mode?: "per_page" | "separate_page" | "end_of_test";
      columns: number;
      question_gap_mm: number;
      question_gap_min_mm?: number;
      auto_compact_spacing?: boolean;
      page_preset: string;
      page_width_mm?: number;
      page_height_mm?: number;
      orientation?: string;
      margin_top_mm?: number;
      margin_bottom_mm?: number;
      margin_left_mm?: number;
      margin_right_mm?: number;
      header_style_id: string;
      theme_color: string;
      questions: import("../types").QuestionItem[];
      sections?: import("../types").SectionRange[];
      skip_images?: boolean;
      include_description?: boolean;
      description_column_count?: number;
      description_texts?: string[];
      description_column_dividers?: boolean;
      add_text_on_line?: boolean;
      center_line_text?: string;
      center_line_bold?: boolean;
      center_line_italic?: boolean;
      center_line_text_direction?: string;
      watermark_enabled?: boolean;
      watermark_mode?: string;
      watermark_text?: string;
      watermark_text_opacity_pct?: number;
      watermark_text_size_pct?: number;
      watermark_text_angle_deg?: number;
      watermark_text_color?: string;
      watermark_image_base64?: string | null;
      watermark_image_opacity_pct?: number;
      watermark_image_size_pct?: number;
      written_paper_header?: boolean;
      written_paper_title?: string;
      written_paper_field_lines?: Record<string, string[]>;
      written_paper_field_hidden?: Record<string, boolean>;
      written_paper_field_labels?: Record<string, string>;
      exam_type?: string;
      footer_nav_page_turn_texts?: boolean;
      class_section?: string;
      group?: string;
      teacher_names?: { name: string; title: string }[];
      principal_name?: string;
      layout_y_top_overrides?: { order_index: number; y_top_pt: number }[];
    }) =>
      fetch(`${API_BASE}/exports/layout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) =>
        r.json().then((data) => {
          if (!r.ok) throw new Error(data.detail ?? "Layout failed");
          return data as { layout: LayoutItem[]; page_w_pt: number; page_h_pt: number };
        })
      ),
  },
};

export type LayoutItem = {
  order_index: number;
  page_num: number;
  x_pt: number;
  y_top_pt: number;
  w_pt: number;
  h_pt: number;
  /** Soru görselinin tam dikdörtgeni (numara hariç) - overlay için */
  img_x_pt?: number;
  img_y_top_pt?: number;
  img_w_pt?: number;
  img_h_pt?: number;
  /** Canvas önizleme için soru görseli (base64) */
  image_base64?: string;
  answer_key?: string;
  /** Bölüm başlığı bilgisi (varsa) */
  section?: {
    title: string;
    fill_color: string;
    text_color: string;
    line_color: string;
    font_pt: number;
    box_h: number;
    gap_after: number;
  };
  /** PDF'te görünen soru numarası; açıklama bloklarında null */
  display_number?: number | null;
  /** Layout satırı içerik türü (önizleme rozetleri için) */
  content_type?: string;
  explanation_caption?: {
    lines: string[];
    align: string;
    font_pt: number;
    leading_pt: number;
    x_pt: number;
    y_top_pt: number;
    w_pt: number;
    h_pt: number;
    color_hex?: string;
    bold?: boolean;
    italic?: boolean;
    single_line?: string;
    rotate_deg?: number;
    pivot_x_pt?: number;
    pivot_y_pt?: number;
    box_enabled?: boolean;
    box_fill_hex?: string;
    box_rounded?: boolean;
    box_tight?: boolean;
    box_bg_x_pt?: number;
    box_bg_w_pt?: number;
  } | null;
  /** Numara hizası için sütun genişliği (pt); sağa yaslama ile PDF ile aynı */
  num_slot_w_pt?: number;
};
