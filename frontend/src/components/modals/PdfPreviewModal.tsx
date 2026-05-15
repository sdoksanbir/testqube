import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, rectSortingStrategy } from "@dnd-kit/sortable";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, type LayoutItem } from "../../api/client";
import {
  columnContentRectsPx,
  computePageColumnBand,
  mmToPdfPt,
  type LayoutGeometryInput,
} from "../../utils/pdfLayoutGeometry";
import {
  getColumnItemsSortedTopFirst,
  redistributeColumnQuestions,
  restoreLayoutItemsByOrderIndices,
} from "../../utils/columnRedistribute";
import ColumnOverlaySelector from "../pdf/ColumnOverlaySelector";
import ColumnRedistributePopover, {
  type ColumnRedistributeMode,
} from "./ColumnRedistributePopover";
import { useEditorStore } from "../../store/editorStore";
import { getPaperSizePayload } from "../../utils/paperSizePayload";
import {
  emptyWrittenHeaderFieldHidden,
  emptyWrittenHeaderFieldLabels,
  emptyWrittenHeaderFieldLines,
  type WrittenHeaderFieldHidden,
  type WrittenHeaderFieldLabels,
  type WrittenHeaderFieldLines,
} from "../../constants/writtenHeaderFields";
import { bookletLetterFromGroup, buildWrittenPaperTitle } from "../../utils/writtenPaperTitle";
import { layoutYTopOverridesApiPayload } from "../../utils/layoutYTopOverridesPayload";
import { pdfPreviewTheme as theme } from "../../styles/pdfPreviewTheme";
import type { QuestionItem } from "../../types";
import SectionAddModal from "./SectionAddModal";
import CanvasPdfPreview from "../pdf/CanvasPdfPreview";
import { countSeparateAnswerKeyPages } from "../../utils/separateAnswerKeyPageCount";

/** Canvas / layout — 96 DPI CSS px ↔ PDF pt */
const PREVIEW_PT_TO_PX = 96 / 72;

type PdfPreviewModalProps = {
  isOpen: boolean;
  onClose: () => void;
  /** Yazılı: başlık şablonu + öğretmen satırı; deneme: cevap anahtarı ayrı sayfa şablonu */
  variant?: "test" | "written" | "trial";
};

function writtenFieldLinesPayload(lines: WrittenHeaderFieldLines) {
  return {
    ad_soyad: [...lines.ad_soyad],
    numara: [...lines.numara],
    puan: [...lines.puan],
    sinif: [...lines.sinif],
    grup: [...lines.grup],
  };
}

function writtenFieldHiddenPayload(hidden: WrittenHeaderFieldHidden) {
  return {
    ad_soyad: !!hidden.ad_soyad,
    numara: !!hidden.numara,
    puan: !!hidden.puan,
    sinif: !!hidden.sinif,
    grup: !!hidden.grup,
  };
}

function writtenFieldLabelsPayload(labels: WrittenHeaderFieldLabels) {
  return {
    ad_soyad: (labels.ad_soyad ?? "").trim(),
    numara: (labels.numara ?? "").trim(),
    puan: (labels.puan ?? "").trim(),
    sinif: (labels.sinif ?? "").trim(),
    grup: (labels.grup ?? "").trim(),
  };
}

const { colors, sizes, font, fontWeight, lineHeight, fontFamily } = theme;

type SortableQuestionBoxProps = {
  questionId: string;
  index: number;
  selectedQuestion: number;
  onSelect: () => void;
  theme: typeof theme;
};

function SortableQuestionBox({
  questionId,
  index,
  selectedQuestion,
  onSelect,
  theme: t,
}: SortableQuestionBoxProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: questionId,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const isSelected = selectedQuestion === index;
  return (
    <button
      ref={setNodeRef}
      type="button"
      style={{
        ...style,
        width: t.sizes.questionBoxSize,
        height: t.sizes.questionBoxSize,
      }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      className={`shrink-0 rounded-md border-2 text-xs font-bold transition cursor-grab active:cursor-grabbing ${
        isSelected ? "border-blue-500 bg-blue-600 text-white" : "border-slate-500 bg-slate-600 text-slate-200 hover:border-slate-400 hover:bg-slate-500"
      } ${isDragging ? "opacity-70 z-50" : ""}`}
      {...attributes}
      {...listeners}
    >
      {index + 1}
    </button>
  );
}

/** PDF önizleme modalı - tema ile boyutlandırma ve renklendirme */
export default function PdfPreviewModal({ isOpen, onClose, variant = "test" }: PdfPreviewModalProps) {
  const navigate = useNavigate();
  const isWritten = variant === "written";
  const isTrial = variant === "trial";
  const questions = useEditorStore((s) => s.questions);
  const testName = useEditorStore((s) => s.testName);
  const schoolName = useEditorStore((s) => s.schoolName);
  const options = useEditorStore((s) => s.options);
  const centerLineText = useEditorStore((s) => s.centerLineText);
  const centerLineBold = useEditorStore((s) => s.centerLineBold);
  const centerLineItalic = useEditorStore((s) => s.centerLineItalic);
  const centerLineTextDirection = useEditorStore((s) => s.centerLineTextDirection);
  const descriptionColumnCount = useEditorStore((s) => s.descriptionColumnCount);
  const descriptionTexts = useEditorStore((s) => s.descriptionTexts);
  const descriptionColumnDividers = useEditorStore((s) => s.descriptionColumnDividers);
  const questionGapMm = useEditorStore((s) => s.questionGapMm);
  const questionGapMinMm = useEditorStore((s) => s.questionGapMinMm);
  const autoCompactSpacing = useEditorStore((s) => s.autoCompactSpacing);
  const headerStyleId = useEditorStore((s) => s.headerStyleId);
  const themeColor = useEditorStore((s) => s.themeColor);
  const answerKeyMode = useEditorStore((s) => s.answerKeyMode);
  const toggleOption = useEditorStore((s) => s.toggleOption);
  const swapQuestions = useEditorStore((s) => s.swapQuestions);
  const insertQuestionAfter = useEditorStore((s) => s.insertQuestionAfter);
  const reorderQuestions = useEditorStore((s) => s.reorderQuestions);
  const setQuestionDisplayScale = useEditorStore((s) => s.setQuestionDisplayScale);
  const setQuestionCustomGapMm = useEditorStore((s) => s.setQuestionCustomGapMm);
  const sections = useEditorStore((s) => s.sections);
  const paperSize = useEditorStore((s) => s.paperSize);
  const paperWidthMm = useEditorStore((s) => s.paperWidthMm);
  const paperHeightMm = useEditorStore((s) => s.paperHeightMm);
  const orientation = useEditorStore((s) => s.orientation);
  const columns = useEditorStore((s) => s.columns);
  const watermarkEnabled = useEditorStore((s) => s.watermarkEnabled);
  const watermarkSettings = useEditorStore((s) => s.watermarkSettings);
  const marginTopMm = useEditorStore((s) => s.marginTopMm);
  const marginBottomMm = useEditorStore((s) => s.marginBottomMm);
  const marginLeftMm = useEditorStore((s) => s.marginLeftMm);
  const marginRightMm = useEditorStore((s) => s.marginRightMm);
  const examType = useEditorStore((s) => s.examType);
  const classSection = useEditorStore((s) => s.classSection);
  const group = useEditorStore((s) => s.group);
  const writtenPaperOptions = useEditorStore((s) => s.writtenPaperOptions);
  const teacherNames = useEditorStore((s) => s.teacherNames);
  const principalName = useEditorStore((s) => s.principalName);
  const writtenHeaderFieldLines = useEditorStore((s) => s.writtenHeaderFieldLines);
  const writtenHeaderFieldLabels = useEditorStore((s) => s.writtenHeaderFieldLabels);
  const writtenHeaderFieldHidden = useEditorStore((s) => s.writtenHeaderFieldHidden);
  const mergeLayoutYTopOverridesByQuestionId = useEditorStore(
    (s) => s.mergeLayoutYTopOverridesByQuestionId
  );
  const clearLayoutYTopOverrides = useEditorStore((s) => s.clearLayoutYTopOverrides);
  const removeLayoutYTopOverridesForQuestionIds = useEditorStore(
    (s) => s.removeLayoutYTopOverridesForQuestionIds
  );

  const writtenTitleForPreview = useMemo(
    () =>
      buildWrittenPaperTitle({
        schoolName: schoolName ?? "",
        classSection,
        testName: testName ?? "",
        examType,
      }),
    [schoolName, classSection, testName, examType]
  );

  /** Yazılı ve deneme sınavında cevap anahtarı ayrı sayfada (footer’da değil) */
  const previewAnswerKeyMode = useMemo(() => {
    if ((isWritten || isTrial) && options.includeAnswerKey) return "separate_page" as const;
    return (answerKeyMode ?? "per_page") as "per_page" | "separate_page" | "end_of_test";
  }, [isWritten, isTrial, options.includeAnswerKey, answerKeyMode]);

  /** İmza bloğu: en az bir öğretmen adı veya müdür adı doluysa göster */
  const writtenTeachersForPreview = useMemo(() => {
    const mapped = teacherNames.map((t) => ({ name: t.name ?? "", title: t.title ?? "" }));
    if (!writtenPaperOptions.addTeacherName) return [];
    return mapped.length > 0 ? mapped : [{ name: "", title: "" }];
  }, [teacherNames, writtenPaperOptions.addTeacherName]);
  /** Son sayfa imzası: öğretmen listesi (seçenek açıksa) ve/veya müdür adı */
  const writtenShowTeachers =
    isWritten &&
    ((writtenPaperOptions.addTeacherName &&
      writtenTeachersForPreview.some((t) => (t.name ?? "").trim())) ||
      !!(principalName ?? "").trim());

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layoutReady, setLayoutReady] = useState(false);
  const [selectedQuestion, setSelectedQuestion] = useState(0);
  const [gapMm, setGapMm] = useState(35);
  const [gapMmInput, setGapMmInput] = useState("");
  const [sizePct, setSizePct] = useState(100);
  const [placeMode, setPlaceMode] = useState<"swap" | "insert" | "">("");
  const [swapTarget, setSwapTarget] = useState<string>("");
  const [insertTarget, setInsertTarget] = useState<string>("");
  const [sectionModalOpen, setSectionModalOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [currentPage, setCurrentPage] = useState(1);
  const [layout, setLayout] = useState<LayoutItem[]>([]);
  const [pageWpt, setPageWpt] = useState(595.28);
  const [pageHpt, setPageHpt] = useState(841.89);
  const [quality, setQuality] = useState<"normal" | "high" | "best">("high");
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [lastOverId, setLastOverId] = useState<string | null>(null);
  const [showThumbnailsPanel, setShowThumbnailsPanel] = useState(true);
  const [columnAdjustEnabled, setColumnAdjustEnabled] = useState(false);
  const [columnPanel, setColumnPanel] = useState<{
    pageNum: number;
    columnIndex0: number;
    anchor: { x: number; y: number };
  } | null>(null);
  const [columnRedistBaseLayout, setColumnRedistBaseLayout] = useState<LayoutItem[] | null>(null);
  const [columnRedistPreviewActive, setColumnRedistPreviewActive] = useState(false);
  const [columnRedistMode, setColumnRedistMode] = useState<ColumnRedistributeMode>("equal");
  /** Önceki varsayılan 24 CSS px ≈ 18 pt ≈ 6,35 mm (soru boşluğu birimi: mm) */
  const [columnBottomGapMmInput, setColumnBottomGapMmInput] = useState("6.35");
  const [columnDistInlineError, setColumnDistInlineError] = useState<string | null>(null);
  /** Panel açıldığı layout — Sıfırla her zaman buraya döner (state güncellemelerinden etkilenmez). */
  const columnPanelOpenLayoutRef = useRef<LayoutItem[] | null>(null);
  /** Tıklanan sütundaki order_index listesi — sütun eşlemesi hatalarında da sıfırlama doğru çalışır. */
  const [columnPanelOrderIndices, setColumnPanelOrderIndices] = useState<number[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);
  const layoutRef = useRef<LayoutItem[]>([]);

  const maxQuestionPage = layout.length > 0 ? Math.max(...layout.map((l) => l.page_num)) : 1;
  const answerKeyItemCount = useMemo(
    () => layout.filter((l) => l.display_number != null).length,
    [layout]
  );
  const answerKeyPages = useMemo(() => {
    if (!options.includeAnswerKey || previewAnswerKeyMode !== "separate_page") return 0;
    return countSeparateAnswerKeyPages({
      itemCount: answerKeyItemCount,
      pageHpt,
      marginTopMm,
      marginBottomMm,
    });
  }, [
    options.includeAnswerKey,
    previewAnswerKeyMode,
    answerKeyItemCount,
    pageHpt,
    marginTopMm,
    marginBottomMm,
  ]);
  const totalPages = maxQuestionPage + answerKeyPages;

  const layoutGeometryInput: LayoutGeometryInput = useMemo(
    () => ({
      pageWpt,
      pageHpt,
      marginTopMm,
      marginBottomMm,
      marginLeftMm,
      marginRightMm,
      columns,
      columnGapMm: 8,
      pageNum: currentPage,
      writtenPaperHeader: isWritten,
      writtenPaperTitle: isWritten ? writtenTitleForPreview : undefined,
      writtenPaperFieldLines: isWritten ? writtenHeaderFieldLines : emptyWrittenHeaderFieldLines(),
      writtenPaperFieldHidden: isWritten ? writtenHeaderFieldHidden : emptyWrittenHeaderFieldHidden(),
      includeDescription: options.includeDescription,
      descriptionColumnCount: descriptionColumnCount ?? 1,
      descriptionTexts: descriptionTexts ?? [],
    }),
    [
      pageWpt,
      pageHpt,
      marginTopMm,
      marginBottomMm,
      marginLeftMm,
      marginRightMm,
      columns,
      currentPage,
      isWritten,
      writtenTitleForPreview,
      writtenHeaderFieldLines,
      writtenHeaderFieldHidden,
      options.includeDescription,
      descriptionColumnCount,
      descriptionTexts,
    ]
  );

  const columnBandLive = useMemo(
    () => computePageColumnBand(layoutGeometryInput),
    [layoutGeometryInput]
  );

  const columnOverlayRectsPx = useMemo(
    () => columnContentRectsPx(columnBandLive, pageHpt, PREVIEW_PT_TO_PX * zoom),
    [columnBandLive, pageHpt, zoom]
  );

  const columnPanelItems = useMemo(() => {
    if (!columnPanel || !columnRedistBaseLayout) return [];
    const gi: LayoutGeometryInput = {
      ...layoutGeometryInput,
      pageNum: columnPanel.pageNum,
    };
    const band = computePageColumnBand(gi);
    return getColumnItemsSortedTopFirst(
      columnRedistBaseLayout,
      columnPanel.pageNum,
      columnPanel.columnIndex0,
      band
    );
  }, [columnPanel, columnRedistBaseLayout, layoutGeometryInput]);

  const columnEqualDisabled = columnPanelItems.length < 1;
  const columnAnchoredDisabled = columnPanelItems.length < 3;

  const runColumnRedistribution = useCallback(() => {
    if (!columnRedistBaseLayout || !columnPanel) {
      return { ok: false as const, error: "Panel kapalı." };
    }
    const geometry: LayoutGeometryInput = {
      ...layoutGeometryInput,
      pageNum: columnPanel.pageNum,
    };
    const bottomGapPt = mmToPdfPt(Math.max(0, parseFloat(columnBottomGapMmInput) || 0));
    return redistributeColumnQuestions({
      fullLayout: columnRedistBaseLayout,
      pageNum: columnPanel.pageNum,
      columnIndex: columnPanel.columnIndex0,
      geometry,
      mode: columnRedistMode === "equal" ? "equal" : "anchored",
      bottomGapPt: columnRedistMode === "anchored" ? bottomGapPt : undefined,
    });
  }, [
    columnRedistBaseLayout,
    columnPanel,
    layoutGeometryInput,
    columnRedistMode,
    columnBottomGapMmInput,
  ]);

  const handleColumnOverlayPointerDown = useCallback(
    (col0: number, clientX: number, clientY: number) => {
      const snap = JSON.parse(JSON.stringify(layout)) as LayoutItem[];
      columnPanelOpenLayoutRef.current = snap;
      const gi: LayoutGeometryInput = {
        ...layoutGeometryInput,
        pageNum: currentPage,
      };
      const band = computePageColumnBand(gi);
      const inCol = getColumnItemsSortedTopFirst(snap, currentPage, col0, band);
      setColumnPanelOrderIndices(inCol.map((q) => q.order_index));
      setColumnRedistBaseLayout(snap);
      setColumnPanel({
        pageNum: currentPage,
        columnIndex0: col0,
        anchor: { x: clientX, y: clientY },
      });
      setColumnRedistPreviewActive(false);
      setColumnDistInlineError(null);
      setColumnRedistMode("equal");
    },
    [layout, currentPage, layoutGeometryInput]
  );

  const handleColumnRedistPreview = useCallback(() => {
    const r = runColumnRedistribution();
    if (!r.ok) {
      setColumnDistInlineError(r.error);
      return;
    }
    setLayout(r.layout);
    setColumnRedistPreviewActive(true);
    setColumnDistInlineError(null);
  }, [runColumnRedistribution]);

  const handleColumnRedistApply = useCallback(() => {
    const r = runColumnRedistribution();
    if (!r.ok) {
      setColumnDistInlineError(r.error);
      return;
    }
    const nextLayout = r.layout;
    const qsApply = useEditorStore.getState().questions;
    const partial: Record<string, number> = {};
    for (const it of columnPanelItems) {
      const found = nextLayout.find((l) => l.order_index === it.order_index);
      const q = qsApply.find((x) => x.order_index === it.order_index);
      if (found && q) partial[q.id] = found.y_top_pt;
    }
    mergeLayoutYTopOverridesByQuestionId(partial);
    setLayout(nextLayout);
    setColumnPanel(null);
    setColumnRedistBaseLayout(null);
    columnPanelOpenLayoutRef.current = null;
    setColumnPanelOrderIndices([]);
    setColumnRedistPreviewActive(false);
    setColumnDistInlineError(null);
  }, [runColumnRedistribution, columnPanelItems, mergeLayoutYTopOverridesByQuestionId]);

  const handleColumnRedistCancel = useCallback(() => {
    if (columnRedistPreviewActive && columnRedistBaseLayout) {
      setLayout(JSON.parse(JSON.stringify(columnRedistBaseLayout)) as LayoutItem[]);
    }
    setColumnPanel(null);
    setColumnRedistBaseLayout(null);
    columnPanelOpenLayoutRef.current = null;
    setColumnPanelOrderIndices([]);
    setColumnRedistPreviewActive(false);
    setColumnDistInlineError(null);
  }, [columnRedistPreviewActive, columnRedistBaseLayout]);

  const handleColumnRedistReset = useCallback(() => {
    const openSnap = columnPanelOpenLayoutRef.current;
    if (!columnPanel || !openSnap || columnPanelOrderIndices.length === 0) return;
    const next = restoreLayoutItemsByOrderIndices(
      layout,
      openSnap,
      columnPanelOrderIndices
    );
    setLayout(next);
    const qsReset = useEditorStore.getState().questions;
    const idsToClear = columnPanelOrderIndices
      .map((oi) => qsReset.find((q) => q.order_index === oi)?.id)
      .filter((id): id is string => Boolean(id));
    removeLayoutYTopOverridesForQuestionIds(idsToClear);
    setColumnDistInlineError(null);
    setColumnRedistPreviewActive(false);
  }, [columnPanel, columnPanelOrderIndices, layout, removeLayoutYTopOverridesForQuestionIds]);

  useEffect(() => {
    layoutRef.current = layout;
  }, [layout]);

  useEffect(() => {
    if (!isOpen) {
      setColumnAdjustEnabled(false);
      setColumnPanel(null);
      setColumnRedistBaseLayout(null);
      columnPanelOpenLayoutRef.current = null;
      setColumnPanelOrderIndices([]);
      setColumnRedistPreviewActive(false);
      setColumnDistInlineError(null);
    }
  }, [isOpen]);

  const sortableSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 3 } })
  );

  const handleSortableDragStart = (event: DragStartEvent) => {
    setActiveDragId(String(event.active.id));
    setLastOverId(null);
  };

  const handleSortableDragOver = (event: DragOverEvent) => {
    if (event.over) setLastOverId(String(event.over.id));
  };

  const handleSortableDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    const overId = over ? String(over.id) : lastOverId;
    setActiveDragId(null);
    setLastOverId(null);
    if (!overId || String(active.id) === overId) return;
    const ids = questions.map((q) => q.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(overId);
    if (from < 0 || to < 0 || from === to) return;
    const reorderedIds = arrayMove(ids, from, to);
    reorderQuestions(reorderedIds).then(() => {
      setSelectedQuestion(to);
      setLoading(true);
      const qs = useEditorStore.getState().questions;
      fetchLayout(undefined, qs)
        .then(() => setLoading(false))
        .catch((e) => {
          setError(e instanceof Error ? e.message : "Önizleme güncellenemedi");
          setLoading(false);
        });
    });
  };

  const fetchLayout = useCallback(
    async (
      localGapMm?: number,
      qsOverride?: QuestionItem[],
      opts?: { skipImages?: boolean }
    ) => {
      const qs = qsOverride ?? questions;
      if (qs.length === 0) return;
      const gap = localGapMm ?? (options.addSpacingBetweenQuestions ? questionGapMm : 35);
      const paper = getPaperSizePayload(paperSize, paperWidthMm, paperHeightMm, orientation);
      const yOv = useEditorStore.getState().layoutYTopOverridesByQuestionIdPt;
      const layoutYTopPayload = layoutYTopOverridesApiPayload(yOv, qs);
      const payload = {
        title: isWritten ? testName?.trim() || "Yazılı" : testName?.trim() || "TEST",
        school_name: schoolName?.trim() || "",
        include_answer_key: options.includeAnswerKey,
        answer_key_mode:
          (isWritten || isTrial) && options.includeAnswerKey
            ? "separate_page"
            : answerKeyMode ?? "per_page",
        columns,
        question_gap_mm: gap,
        question_gap_min_mm: questionGapMinMm,
        auto_compact_spacing: autoCompactSpacing,
        page_preset: paper.page_preset,
        page_width_mm: paper.page_width_mm,
        page_height_mm: paper.page_height_mm,
        orientation: paper.orientation,
        margin_top_mm: marginTopMm,
        margin_bottom_mm: marginBottomMm,
        margin_left_mm: marginLeftMm,
        margin_right_mm: marginRightMm,
        watermark_enabled: watermarkEnabled,
        watermark_mode: watermarkSettings.mode,
        watermark_text: watermarkSettings.text,
        watermark_text_opacity_pct: watermarkSettings.textOpacityPct,
        watermark_text_size_pct: watermarkSettings.textSizePct,
        watermark_text_angle_deg: watermarkSettings.textAngleDeg,
        watermark_text_color: themeColor,
        watermark_image_base64: watermarkSettings.imageBase64,
        watermark_image_opacity_pct: watermarkSettings.imageOpacityPct,
        watermark_image_size_pct: watermarkSettings.imageSizePct,
        header_style_id: headerStyleId,
        theme_color: themeColor,
        questions: qs.map((q) => ({
          id: q.id,
          pdf_id: q.pdf_id,
          page_number: q.page_number,
          crop: q.crop,
          answer_key: q.answer_key,
          order_index: q.order_index,
          content_type: q.content_type ?? "question",
          explanation_caption_enabled: q.explanation_caption_enabled ?? false,
          explanation_caption_text: q.explanation_caption_text ?? "",
          explanation_caption_align: q.explanation_caption_align ?? "left",
          explanation_caption_placement: q.explanation_caption_placement ?? "above",
          explanation_caption_side_flow: q.explanation_caption_side_flow ?? "horizontal",
          explanation_caption_color: q.explanation_caption_color ?? "#0f172a",
          explanation_caption_bold: q.explanation_caption_bold ?? false,
          explanation_caption_italic: q.explanation_caption_italic ?? false,
          explanation_caption_font_pt: q.explanation_caption_font_pt ?? 9,
          explanation_caption_box_enabled: q.explanation_caption_box_enabled ?? false,
          explanation_caption_box_color: q.explanation_caption_box_color ?? "#f1f5f9",
          explanation_caption_box_corner: q.explanation_caption_box_corner ?? "rounded",
          explanation_caption_box_width: q.explanation_caption_box_width ?? "full",
          remove_background: q.remove_background ?? false,
          image_base64: q.image_base64,
          custom_gap_mm: q.custom_gap_mm,
          display_scale: q.display_scale,
        })),
        sections: sections.length > 0 ? sections : undefined,
        skip_images: opts?.skipImages ?? false,
        include_description: options.includeDescription,
        description_column_count: descriptionColumnCount ?? 1,
        description_texts: descriptionTexts ?? [],
        description_column_dividers: descriptionColumnDividers,
        add_text_on_line: options.addTextOnLine,
        center_line_text: centerLineText ?? "",
        center_line_bold: centerLineBold,
        center_line_italic: centerLineItalic,
        center_line_text_direction: centerLineTextDirection ?? "up",
        ...(isWritten
          ? {
              written_paper_header: true,
              written_paper_title: buildWrittenPaperTitle({
                schoolName: schoolName ?? "",
                classSection,
                testName: testName ?? "",
                examType,
              }),
              exam_type: examType || undefined,
              class_section: classSection || undefined,
              group: group !== "Grup Yok" ? group : undefined,
              teacher_names: writtenPaperOptions.addTeacherName
                ? writtenTeachersForPreview.map((t) => ({ name: t.name, title: t.title }))
                : undefined,
              principal_name: (principalName ?? "").trim() || undefined,
              written_paper_field_lines: writtenFieldLinesPayload(writtenHeaderFieldLines),
              written_paper_field_hidden: writtenFieldHiddenPayload(writtenHeaderFieldHidden),
              written_paper_field_labels: writtenFieldLabelsPayload(writtenHeaderFieldLabels),
            }
          : { footer_nav_page_turn_texts: isTrial }),
        ...layoutYTopPayload,
      };
      const data = await api.exports.layout(payload);
      let layoutToSet = data.layout;
      // skipImages kullanıldığında: yeni pozisyonlar gelir, görseller gelmez. Eski layout'taki image_base64'leri koru.
      const prevLayout = layoutRef.current;
      if (opts?.skipImages && prevLayout.length > 0) {
        const byOrder = new Map(prevLayout.map((l) => [l.order_index, l]));
        layoutToSet = data.layout.map((item) => {
          const prev = byOrder.get(item.order_index);
          if (prev?.image_base64 && !item.image_base64) {
            return { ...item, image_base64: prev.image_base64 };
          }
          return item;
        });
      }
      setLayout(layoutToSet);
      setPageWpt(data.page_w_pt);
      setPageHpt(data.page_h_pt);
      return data;
    },
    [
      questions,
      testName,
      schoolName,
      options.includeAnswerKey,
      answerKeyMode,
      options.addSpacingBetweenQuestions,
      questionGapMm,
      questionGapMinMm,
      autoCompactSpacing,
      headerStyleId,
      themeColor,
      sections,
      options.includeDescription,
      descriptionColumnCount,
      descriptionTexts,
      descriptionColumnDividers,
      paperSize,
      paperWidthMm,
      paperHeightMm,
      orientation,
      columns,
      marginTopMm,
      marginBottomMm,
      marginLeftMm,
      marginRightMm,
      isWritten,
      isTrial,
      examType,
      classSection,
      group,
      writtenPaperOptions.addTeacherName,
      teacherNames,
      writtenTeachersForPreview,
      principalName,
      writtenHeaderFieldLines,
      writtenHeaderFieldLabels,
      writtenHeaderFieldHidden,
      options.addTextOnLine,
      centerLineText,
      centerLineBold,
      centerLineItalic,
      centerLineTextDirection,
      watermarkEnabled,
      watermarkSettings.mode,
      watermarkSettings.text,
      watermarkSettings.textOpacityPct,
      watermarkSettings.textSizePct,
      watermarkSettings.textAngleDeg,
      watermarkSettings.imageBase64,
      watermarkSettings.imageOpacityPct,
      watermarkSettings.imageSizePct,
    ]
  );

  /** Seçili soru değişince boşluk/boyut değerlerini senkronize et - sadece soru değişince (layout değil) */
  const prevSelectedRef = useRef(selectedQuestion);
  useEffect(() => {
    if (questions.length === 0) return;
    if (prevSelectedRef.current !== selectedQuestion) {
      prevSelectedRef.current = selectedQuestion;
      const q = questions[selectedQuestion];
      if (q) {
        const synced = q.custom_gap_mm ?? (options.addSpacingBetweenQuestions ? questionGapMm : 35);
        setGapMm(synced);
        setGapMmInput(String(synced));
        setSizePct(Math.round((q.display_scale ?? 1) * 100));
      }
    }
  }, [selectedQuestion, questions, options.addSpacingBetweenQuestions, questionGapMm]);

  /**
   * Sayfa numarasını yalnızca (1) önizleme layout’u ilk kez dolduğunda veya (2) kullanıcı soldan başka soru
   * seçtiğinde o sorunun sayfasına al. Layout yeniden hesaplanınca (sütun uygula/önizle, fetchLayout vb.)
   * mevcut sayfada kal — aksi halde seçili soru 1. sayfadaysa her güncellemede 1. sayfaya sıçranıyordu.
   */
  const layoutSyncHadContentRef = useRef(false);
  const layoutSyncPrevSelectedRef = useRef(selectedQuestion);

  useEffect(() => {
    if (!isOpen) {
      layoutSyncHadContentRef.current = false;
      return;
    }
    if (layout.length === 0) {
      layoutSyncHadContentRef.current = false;
      return;
    }
    const item = layout.find((l) => l.order_index === selectedQuestion);
    if (!item) return;

    const firstLayoutContent = !layoutSyncHadContentRef.current;
    layoutSyncHadContentRef.current = true;

    const selectedChanged = layoutSyncPrevSelectedRef.current !== selectedQuestion;
    layoutSyncPrevSelectedRef.current = selectedQuestion;

    if (firstLayoutContent || selectedChanged) {
      setCurrentPage(item.page_num);
    }
  }, [isOpen, layout, selectedQuestion]);

  /** Bölüm eklendi/düzenlendi/silindi - layout'u bölüm başlıklarıyla yeniden yükle */
  const prevSectionsRef = useRef<string>("");
  useEffect(() => {
    if (!isOpen || questions.length === 0) return;
    if (!layoutReady) {
      prevSectionsRef.current = JSON.stringify(sections);
      return;
    }
    const key = JSON.stringify(sections);
    if (prevSectionsRef.current === key) return;
    prevSectionsRef.current = key;
    clearLayoutYTopOverrides();
    setLoading(true);
    fetchLayout()
      .then(() => setLoading(false))
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Önizleme güncellenemedi");
        setLoading(false);
      });
  }, [sections, isOpen, layoutReady, questions.length, fetchLayout, clearLayoutYTopOverrides]);

  /** Yazılı başlık alanları değişince soru yerleşimini yeniden hesapla (export ile aynı y_top) */
  const writtenHeaderLayoutSigRef = useRef("");
  useEffect(() => {
    if (!isOpen) writtenHeaderLayoutSigRef.current = "";
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !isWritten || questions.length === 0 || !layoutReady) return;
    const sig = JSON.stringify({
      lines: writtenHeaderFieldLines,
      hidden: writtenHeaderFieldHidden,
    });
    if (writtenHeaderLayoutSigRef.current === sig) return;
    const isInitial = writtenHeaderLayoutSigRef.current === "";
    writtenHeaderLayoutSigRef.current = sig;
    if (isInitial) return;
    clearLayoutYTopOverrides();
    setLoading(true);
    fetchLayout(undefined, undefined, { skipImages: true })
      .then(() => setLoading(false))
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Önizleme güncellenemedi");
        setLoading(false);
      });
  }, [
    isOpen,
    isWritten,
    layoutReady,
    questions.length,
    writtenHeaderFieldLines,
    writtenHeaderFieldHidden,
    fetchLayout,
    clearLayoutYTopOverrides,
  ]);

  /** Uygula butonuna basıldığında store + layout günceller */
  const applyGapSizeToPreview = useCallback(
    (clampedGap: number, clampedSize: number) => {
      clearLayoutYTopOverrides();
      const q = questions[selectedQuestion];
      if (!q) return;
      setQuestionCustomGapMm(q.id, clampedGap);
      setQuestionDisplayScale(q.id, clampedSize / 100);
      const updatedQs = questions.map((x) =>
        x.id === q.id
          ? {
              ...x,
              custom_gap_mm: clampedGap,
              display_scale: clampedSize / 100,
            }
          : x
      );
      setLoading(true);
      fetchLayout(undefined, updatedQs, { skipImages: true })
        .then(() => setLoading(false))
        .catch((e) => {
          setError(e instanceof Error ? e.message : "Önizleme güncellenemedi");
          setLoading(false);
        });
    },
    [
      questions,
      selectedQuestion,
      setQuestionCustomGapMm,
      setQuestionDisplayScale,
      fetchLayout,
      clearLayoutYTopOverrides,
    ]
  );

  /** Boşluk & Boyut değişikliklerini Uygula butonu ile uygula */
  const handleApplyGapSize = () => {
    if (!layoutReady || questions.length === 0) return;
    const q = questions[selectedQuestion];
    if (!q) return;
    const gapFromInput = gapMmInput.trim() === "" ? 6 : parseFloat(gapMmInput);
    const clampedGap = Math.max(6, Math.min(100, gapFromInput || 6));
    const clampedSize = Math.max(50, Math.min(200, sizePct));
    setGapMm(clampedGap);
    setGapMmInput(String(clampedGap));
    setSizePct(clampedSize);
    applyGapSizeToPreview(clampedGap, clampedSize);
  };

  /** Sadece modal ilk açıldığında state sıfırla ve layout oluştur (her değişiklikte sıfırlamıyoruz) */
  const prevIsOpenRef = useRef(false);
  useEffect(() => {
    if (!isOpen) {
      prevIsOpenRef.current = false;
      return;
    }
    const justOpened = !prevIsOpenRef.current;
    prevIsOpenRef.current = true;
    if (!justOpened) return;

    setError(null);
    setLayoutReady(false);
    setLayout([]);
    setSelectedQuestion(0);
    setSwapTarget("");
    setInsertTarget("");
    setPlaceMode("");
    if (questions.length > 0) {
      const q = questions[0];
      const synced = q.custom_gap_mm ?? (options.addSpacingBetweenQuestions ? questionGapMm : 35);
      setGapMm(synced);
      setGapMmInput(String(synced));
      setSizePct(Math.round((q.display_scale ?? 1) * 100));
      setLoading(true);
      const gap = options.addSpacingBetweenQuestions ? questionGapMm : 5;
      fetchLayout(gap)
        .then(() => {
          setLayoutReady(true);
          setLoading(false);
        })
        .catch((e) => {
          setError(e instanceof Error ? e.message : "Önizleme yüklenemedi");
          setLoading(false);
        });
    } else {
      const def = options.addSpacingBetweenQuestions ? questionGapMm : 35;
      setGapMm(def);
      setGapMmInput(String(def));
      setSizePct(100);
    }
    setZoom(1);
  }, [isOpen, questions.length, options.addSpacingBetweenQuestions, questionGapMm, fetchLayout]);

  const handleGeneratePreview = () => {
    setLoading(true);
    setError(null);
    const gap = options.addSpacingBetweenQuestions ? questionGapMm : 5;
    fetchLayout(gap)
      .then(() => {
        setLayoutReady(true);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Önizleme yüklenemedi");
        setLoading(false);
      });
  };

  const handleApplyPlace = () => {
    if (questions.length === 0 || !placeMode) return;
    const fromIdx = selectedQuestion;
    const targetNum =
      placeMode === "swap"
        ? Math.max(1, Math.min(questions.length, parseInt(swapTarget, 10) || 1))
        : Math.max(1, Math.min(questions.length, parseInt(insertTarget, 10) || 1));
    const targetIdx = targetNum - 1;
    if (fromIdx === targetIdx) return;
    if (placeMode === "swap") {
      swapQuestions(fromIdx, targetIdx);
    } else {
      insertQuestionAfter(fromIdx, targetIdx);
    }
    const newSelectedIdx =
      placeMode === "swap"
        ? targetIdx
        : fromIdx < targetIdx
          ? targetIdx
          : Math.min(targetIdx + 1, questions.length - 1);
    setSelectedQuestion(newSelectedIdx);
    setSwapTarget("");
    setInsertTarget("");
    setLoading(true);
    setTimeout(() => {
      const qs = useEditorStore.getState().questions;
      fetchLayout(undefined, qs)
        .then(() => setLoading(false))
        .catch((e) => {
          setError(e instanceof Error ? e.message : "Önizleme güncellenemedi");
          setLoading(false);
        });
    }, 0);
  };

  const [savingPdf, setSavingPdf] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSavePdf = async () => {
    if (questions.length === 0) return;
    setSavingPdf(true);
    setSaveError(null);
    try {
      const safeName = (testName?.trim() || "test").replace(/[^\w\u00C0-\u024F\u4E00-\u9FFF-]/gi, "-") || "test";

      // Kullanıcı hareketi kaybolmadan önce dosya seçicisini aç (zorunlu)
      let fileHandle: FileSystemFileHandle | null = null;
      const savePicker = (window as Window & {
        showSaveFilePicker?: (opts: {
          suggestedName?: string;
          types?: { description: string; accept: Record<string, string[]> }[];
        }) => Promise<FileSystemFileHandle>;
      }).showSaveFilePicker;
      if (typeof savePicker === "function") {
        fileHandle = await savePicker({
          suggestedName: `${safeName}.pdf`,
          types: [
            { description: "PDF Dosyası", accept: { "application/pdf": [".pdf"] } },
          ],
        });
      }

      const defaultGap = options.addSpacingBetweenQuestions ? questionGapMm : 35;
      const paper = getPaperSizePayload(paperSize, paperWidthMm, paperHeightMm, orientation);
      const yOvSave = useEditorStore.getState().layoutYTopOverridesByQuestionIdPt;
      const qsSave = useEditorStore.getState().questions;
      const layoutYTopSavePayload = layoutYTopOverridesApiPayload(yOvSave, qsSave);
      const blob = await api.exports.fromQuestions({
        title: isWritten ? testName?.trim() || "Yazılı" : testName?.trim() || "TEST",
        school_name: schoolName?.trim() || "",
        include_answer_key: options.includeAnswerKey,
        answer_key_mode:
          (isWritten || isTrial) && options.includeAnswerKey
            ? "separate_page"
            : answerKeyMode ?? "per_page",
        columns,
        question_gap_mm: defaultGap,
        question_gap_min_mm: questionGapMinMm,
        auto_compact_spacing: autoCompactSpacing,
        page_preset: paper.page_preset,
        page_width_mm: paper.page_width_mm,
        page_height_mm: paper.page_height_mm,
        orientation: paper.orientation,
        margin_top_mm: marginTopMm,
        margin_bottom_mm: marginBottomMm,
        margin_left_mm: marginLeftMm,
        margin_right_mm: marginRightMm,
        watermark_enabled: watermarkEnabled,
        watermark_mode: watermarkSettings.mode,
        watermark_text: watermarkSettings.text,
        watermark_text_opacity_pct: watermarkSettings.textOpacityPct,
        watermark_text_size_pct: watermarkSettings.textSizePct,
        watermark_text_angle_deg: watermarkSettings.textAngleDeg,
        watermark_text_color: themeColor,
        watermark_image_base64: watermarkSettings.imageBase64,
        watermark_image_opacity_pct: watermarkSettings.imageOpacityPct,
        watermark_image_size_pct: watermarkSettings.imageSizePct,
        header_style_id: headerStyleId,
        theme_color: themeColor,
        quality,
        questions: questions.map((q) => ({
          id: q.id,
          pdf_id: q.pdf_id,
          page_number: q.page_number,
          crop: q.crop,
          answer_key: q.answer_key,
          order_index: q.order_index,
          content_type: q.content_type ?? "question",
          explanation_caption_enabled: q.explanation_caption_enabled ?? false,
          explanation_caption_text: q.explanation_caption_text ?? "",
          explanation_caption_align: q.explanation_caption_align ?? "left",
          explanation_caption_placement: q.explanation_caption_placement ?? "above",
          explanation_caption_side_flow: q.explanation_caption_side_flow ?? "horizontal",
          explanation_caption_color: q.explanation_caption_color ?? "#0f172a",
          explanation_caption_bold: q.explanation_caption_bold ?? false,
          explanation_caption_italic: q.explanation_caption_italic ?? false,
          explanation_caption_font_pt: q.explanation_caption_font_pt ?? 9,
          explanation_caption_box_enabled: q.explanation_caption_box_enabled ?? false,
          explanation_caption_box_color: q.explanation_caption_box_color ?? "#f1f5f9",
          explanation_caption_box_corner: q.explanation_caption_box_corner ?? "rounded",
          explanation_caption_box_width: q.explanation_caption_box_width ?? "full",
          remove_background: q.remove_background ?? false,
          image_base64: q.image_base64,
          custom_gap_mm: q.custom_gap_mm,
          display_scale: q.display_scale,
        })),
        sections: sections.length > 0 ? sections : undefined,
        include_description: options.includeDescription,
        description_column_count: descriptionColumnCount ?? 1,
        description_texts: descriptionTexts ?? [],
        description_column_dividers: descriptionColumnDividers,
        add_text_on_line: options.addTextOnLine,
        center_line_text: centerLineText ?? "",
        center_line_bold: centerLineBold,
        center_line_italic: centerLineItalic,
        center_line_text_direction: centerLineTextDirection ?? "up",
        ...(isWritten
          ? {
              written_paper_header: true,
              written_paper_title: writtenTitleForPreview,
              exam_type: examType || undefined,
              class_section: classSection || undefined,
              group: group !== "Grup Yok" ? group : undefined,
              teacher_names: writtenPaperOptions.addTeacherName
                ? writtenTeachersForPreview.map((t) => ({ name: t.name, title: t.title }))
                : undefined,
              principal_name: (principalName ?? "").trim() || undefined,
              written_paper_field_lines: writtenFieldLinesPayload(writtenHeaderFieldLines),
              written_paper_field_hidden: writtenFieldHiddenPayload(writtenHeaderFieldHidden),
              written_paper_field_labels: writtenFieldLabelsPayload(writtenHeaderFieldLabels),
            }
          : { footer_nav_page_turn_texts: isTrial }),
        ...layoutYTopSavePayload,
      });

      if (fileHandle) {
        const writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeName}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      }
      // PDF kaydettikten sonra modal açık kalsın, ana editöre dönme
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setSaveError(e instanceof Error ? e.message : "PDF kaydedilemedi");
    } finally {
      setSavingPdf(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-slate-900"
      style={{ fontFamily }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="pdf-preview-title"
    >
      <div className="flex min-h-0 flex-1 overflow-hidden pdf-preview-scroll">
        {/* Sol panel - Düzenleme */}
        <div
          className="flex min-w-0 shrink-0 flex-col overflow-y-auto border-r border-slate-700 bg-slate-800"
          style={{ width: sizes.sidebarWidth, padding: sizes.padding }}
        >
          <div
            className="flex items-center justify-center rounded-lg border border-slate-600 bg-slate-700/80 py-3 shadow-inner"
            style={{ marginBottom: sizes.gapSection }}
          >
            <h2 className="text-center text-base font-bold tracking-wide text-slate-100">
              PDF Düzenleme Paneli
            </h2>
          </div>

          <div
            className="min-w-0 rounded-lg border border-slate-600 bg-slate-700/50"
            style={{ marginBottom: sizes.gapSection }}
          >
            <div
              className="flex h-7 items-center justify-center rounded-t-lg text-xs font-bold text-white"
              style={{ backgroundColor: "#1E3A5F" }}
            >
              Soru Numaraları
            </div>
            <div
              className="overflow-y-auto"
              style={{
                maxHeight: 200,
                padding: sizes.gap,
              }}
            >
              <DndContext
                sensors={sortableSensors}
                collisionDetection={pointerWithin}
                onDragStart={handleSortableDragStart}
                onDragOver={handleSortableDragOver}
                onDragEnd={handleSortableDragEnd}
              >
                <SortableContext
                  items={questions.map((q) => q.id)}
                  strategy={rectSortingStrategy}
                >
                  <div
                    className="grid content-start"
                    style={{
                      gridTemplateColumns: `repeat(${sizes.questionBoxColumns}, ${sizes.questionBoxSize}px)`,
                      gap: sizes.questionBoxGap,
                    }}
                  >
                    {questions.map((q, i) => (
                      <SortableQuestionBox
                        key={q.id}
                        questionId={q.id}
                        index={i}
                        selectedQuestion={selectedQuestion}
                        onSelect={() => setSelectedQuestion(i)}
                        theme={theme}
                      />
                    ))}
                  </div>
                </SortableContext>
                <DragOverlay dropAnimation={null}>
                  {activeDragId ? (
                    (() => {
                      const idx = questions.findIndex((q) => q.id === activeDragId);
                      if (idx < 0) return null;
                      return (
                        <div
                          className="flex shrink-0 cursor-grabbing items-center justify-center rounded-md border-2 border-blue-500 bg-blue-600 text-xs font-bold text-white shadow-xl"
                          style={{
                            width: sizes.questionBoxSize,
                            height: sizes.questionBoxSize,
                          }}
                        >
                          {idx + 1}
                        </div>
                      );
                    })()
                  ) : null}
                </DragOverlay>
              </DndContext>
            </div>
          </div>

          {questions.length > 0 && (
            <div
              className="min-w-0 rounded-lg border border-slate-600 bg-slate-700/50"
              style={{
                marginBottom: sizes.gapSection,
                padding: sizes.gap,
              }}
            >
              <div
                className="mb-3 flex h-7 items-center justify-center rounded text-xs font-bold text-white"
                style={{ backgroundColor: "#1E3A5F" }}
              >
                {selectedQuestion + 1}. SORU
              </div>

              <div
                className="rounded-lg border-b-2 border-t-2"
                style={{
                  borderTopColor: colors.accent,
                  borderBottomColor: colors.accent,
                  backgroundColor: "rgba(59, 130, 246, 0.12)",
                  padding: sizes.gap,
                  marginBottom: sizes.gapSection,
                }}
              >
                <label
                  className="mb-3 flex items-center gap-2 text-xs font-semibold"
                  style={{ color: colors.accentMuted }}
                >
                  <span
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
                    style={{ backgroundColor: colors.accent, color: "white", fontSize: "0.625rem" }}
                  >
                    ◇
                  </span>
                  Boşluk & Boyut
                  <span className="text-slate-500 font-normal">(sadece bu soru)</span>
                </label>
                <div style={{ marginBottom: sizes.gapSection }}>
                  <label className="mb-2 block text-xs text-slate-400">Boşluk</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={6}
                      max={100}
                      step={0.5}
                      value={gapMmInput === "" ? gapMm : (parseFloat(gapMmInput) || gapMm)}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setGapMm(v);
                        setGapMmInput(String(v));
                      }}
                      className="min-w-0 flex-1"
                      style={{ accentColor: colors.accent, height: 6 }}
                    />
                    <input
                      type="number"
                      min={6}
                      max={100}
                      step={0.25}
                      value={gapMmInput}
                      onChange={(e) => setGapMmInput(e.target.value)}
                      onWheel={(e) => {
                        e.preventDefault();
                        const step = 0.25;
                        const delta = e.deltaY > 0 ? -step : step;
                        const current = parseFloat(gapMmInput) || 6;
                        const next = Math.max(6, Math.min(100, Math.round((current + delta) * 4) / 4));
                        setGapMm(next);
                        setGapMmInput(String(next));
                      }}
                      placeholder="6"
                      className="shrink-0 rounded border border-slate-600 bg-slate-700 px-2 py-1 text-center text-xs text-slate-200 w-16 placeholder:text-slate-500 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    <span className="shrink-0 text-xs text-slate-400">mm</span>
                  </div>
                </div>
                <div style={{ marginBottom: sizes.gapSection }}>
                  <label className="mb-2 block text-xs text-slate-400">Boyut</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={50}
                      max={200}
                      value={sizePct}
                      onChange={(e) => setSizePct(Number(e.target.value))}
                      className="min-w-0 flex-1"
                      style={{ accentColor: colors.accent, height: 6 }}
                    />
                    <input
                      type="number"
                      min={50}
                      max={200}
                      step={1}
                      value={sizePct}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10);
                        if (!isNaN(v)) setSizePct(v);
                      }}
                      onBlur={() => {
                        setSizePct((v) => Math.max(50, Math.min(200, v)));
                      }}
                      onWheel={(e) => {
                        e.preventDefault();
                        const step = 1;
                        const delta = e.deltaY > 0 ? -step : step;
                        setSizePct((v) => Math.max(50, Math.min(200, v + delta)));
                      }}
                      className="shrink-0 rounded border border-slate-600 bg-slate-700 px-2 py-1 text-center text-xs text-slate-200 w-16 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    <span className="shrink-0 text-xs text-slate-400">%</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleApplyGapSize}
                  disabled={loading || questions.length === 0}
                  className="w-full rounded bg-blue-600 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-blue-600"
                >
                  Uygula
                </button>
              </div>

              <div
                className="rounded-lg border-b-2 border-t-2"
                style={{
                  borderTopColor: colors.success,
                  borderBottomColor: colors.success,
                  backgroundColor: "rgba(34, 197, 94, 0.12)",
                  padding: sizes.gap,
                  marginTop: sizes.gapSection,
                }}
              >
                <label
                  className="mb-2 flex items-center gap-2 text-xs font-semibold"
                  style={{ color: colors.success }}
                >
                  <span
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
                    style={{ backgroundColor: colors.success, color: "white", fontSize: "0.625rem" }}
                  >
                    ↔
                  </span>
                  Soru Yerleştir
                </label>
                <div className="text-xs text-slate-300" style={{ lineHeight: lineHeight.relaxed }}>
                  <label
                    className="flex items-center gap-2"
                    style={{ marginBottom: sizes.gap }}
                  >
                    <input
                      type="radio"
                      name="place"
                      checked={placeMode === "swap"}
                      onChange={() => setPlaceMode("swap")}
                      style={{ accentColor: colors.primary }}
                    />
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={questions.length}
                      value={swapTarget}
                      onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") { setSwapTarget(""); return; }
                        const v = parseInt(raw, 10);
                        if (!isNaN(v)) setSwapTarget(String(Math.max(1, Math.min(questions.length, v))));
                      }}
                      disabled={placeMode !== "swap"}
                      className="w-10 shrink-0 rounded border border-slate-400 bg-white px-2 py-1 text-center text-xs font-semibold text-black [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <span>sorusu ile yer değiştir</span>
                  </label>
                  <label
                    className="flex items-center gap-2"
                    style={{ marginBottom: sizes.gap }}
                  >
                    <input
                      type="radio"
                      name="place"
                      checked={placeMode === "insert"}
                      onChange={() => setPlaceMode("insert")}
                      style={{ accentColor: colors.primary }}
                    />
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={questions.length}
                      value={insertTarget}
                      onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") { setInsertTarget(""); return; }
                        const v = parseInt(raw, 10);
                        if (!isNaN(v)) setInsertTarget(String(Math.max(1, Math.min(questions.length, v))));
                      }}
                      disabled={placeMode !== "insert"}
                      className="w-10 shrink-0 rounded border border-slate-400 bg-white px-2 py-1 text-center text-xs font-semibold text-black [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <span>sorunun altına ekle</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleApplyPlace}
                    disabled={!placeMode || (placeMode === "swap" ? !swapTarget.trim() : !insertTarget.trim())}
                    className="mt-2 w-full rounded bg-blue-600 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-blue-600"
                  >
                    Uygula
                  </button>
                </div>
              </div>
            </div>
          )}

          {!isWritten && (
            <button
              type="button"
              onClick={() => setSectionModalOpen(true)}
              className="w-full shrink-0 rounded-lg border border-[#FF9800] bg-[#FF9800] py-2 text-xs font-bold text-white hover:bg-[#FFB74D]"
            >
              BÖLÜM EKLE
            </button>
          )}
        </div>

        {/* Sayfa thumbnails - Sol panelin sağında (gizle/göster toggle) */}
        {!loading && !error && layoutReady && layout.length > 0 && totalPages > 0 && (
          showThumbnailsPanel ? (
            <div
              className="flex shrink-0 flex-col overflow-hidden border-r border-slate-700 bg-slate-800 shadow-inner"
              style={{ width: 155 }}
            >
              <div
                className="flex shrink-0 items-center justify-between gap-1 py-2 px-2"
                style={{ borderBottom: "1px solid #475569" }}
              >
                <span className="text-xs font-bold text-slate-300">Sayfalar</span>
                <button
                  type="button"
                  onClick={() => setShowThumbnailsPanel(false)}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-400 transition hover:bg-slate-600 hover:text-slate-200"
                  aria-label="Sayfa panelini gizle"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M19 12H5M12 19l-7-7 7-7" />
                  </svg>
                </button>
              </div>
              <div
                className="flex flex-col gap-2 overflow-y-auto px-2 py-2"
                style={{ maxHeight: "100%" }}
              >
                {Array.from({ length: totalPages }, (_, i) => {
                  const pageNum = i + 1;
                  const isActive = currentPage === pageNum;
                  return (
                    <button
                      key={pageNum}
                      type="button"
                      onClick={() => setCurrentPage(pageNum)}
                      className="flex w-full justify-center overflow-hidden rounded-md transition hover:opacity-95"
                      style={{ padding: 2 }}
                      aria-label={`Sayfa ${pageNum}`}
                      aria-pressed={isActive}
                    >
                      <CanvasPdfPreview
                        layout={layout}
                        pageWpt={pageWpt}
                        pageHpt={pageHpt}
                        currentPage={pageNum}
                        zoom={0.16}
                        thumbnailWidthPx={131}
                        selectedQuestion={selectedQuestion}
                        onQuestionSelect={() => {}}
                        testTitle={testName?.trim() || "TEST"}
                        schoolName={schoolName?.trim() || ""}
                        themeColor={themeColor}
                        includeAnswerKey={options.includeAnswerKey}
                        answerKeyMode={previewAnswerKeyMode}
                        columns={columns}
                        marginTopMm={marginTopMm}
                        marginBottomMm={marginBottomMm}
                        marginLeftMm={marginLeftMm}
                        marginRightMm={marginRightMm}
                        columnGapMm={8}
                        interactive={false}
                        includeDescription={options.includeDescription}
                        descriptionColumnCount={descriptionColumnCount ?? 1}
                        descriptionTexts={descriptionTexts ?? []}
                        descriptionColumnDividers={descriptionColumnDividers}
                        addTextOnLine={options.addTextOnLine}
                        centerLineText={centerLineText}
                        centerLineBold={centerLineBold}
                        centerLineItalic={centerLineItalic}
                        centerLineTextDirection={centerLineTextDirection}
                        watermarkEnabled={watermarkEnabled}
                        watermarkSettings={watermarkSettings}
                        writtenPaperHeader={isWritten}
                        writtenPaperTitle={isWritten ? writtenTitleForPreview : undefined}
                        writtenPaperFieldLines={isWritten ? writtenHeaderFieldLines : emptyWrittenHeaderFieldLines()}
                        writtenPaperFieldLabels={isWritten ? writtenHeaderFieldLabels : emptyWrittenHeaderFieldLabels()}
                        writtenPaperFieldHidden={isWritten ? writtenHeaderFieldHidden : emptyWrittenHeaderFieldHidden()}
                        writtenPaperBookletLetter={isWritten ? bookletLetterFromGroup(group) : "A"}
                        writtenPaperShowTeachers={writtenShowTeachers}
                        writtenPaperTeachers={writtenTeachersForPreview}
                        writtenPaperPrincipalName={principalName ?? ""}
                        lastQuestionPage={!isWritten && isTrial ? maxQuestionPage : undefined}
                      />
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowThumbnailsPanel(true)}
              className="flex shrink-0 flex-col items-center justify-center gap-1 border-r border-slate-700 bg-slate-800 px-1.5 py-3 transition hover:bg-slate-700"
              style={{ width: 32 }}
              aria-label="Sayfa panelini göster"
              title="Sayfalar panelini göster"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-slate-400">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
              <span className="text-[0.5625rem] font-medium text-slate-500">Sayfa</span>
            </button>
          )
        )}

        {!isWritten && (
          <SectionAddModal
            isOpen={sectionModalOpen}
            onClose={() => setSectionModalOpen(false)}
            selectedQuestion={selectedQuestion}
          />
        )}

        {/* Orta panel - PDF önizleme */}
        <div
          ref={containerRef}
          className="relative flex min-w-0 flex-1 flex-col overflow-hidden"
          style={{ backgroundColor: colors.bgRoot }}
        >
          <div className="relative min-h-0 flex-1 overflow-auto p-6">
            {!layoutReady && !loading && !error && (
              <div
                className="flex min-h-full min-w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-600 bg-gradient-to-br from-slate-800 via-slate-700/80 to-slate-800 p-8"
                style={{ minHeight: 400 }}
              >
                <div className="mb-6 rounded-2xl bg-gradient-to-br from-blue-500/30 to-blue-600/20 p-6 shadow-lg ring-1 ring-blue-400/30">
                  <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                </div>
                <h3 className="mb-2 text-lg font-semibold text-slate-100">
                  {questions.length === 0 ? "Henüz soru seçilmedi" : "PDF Önizlemesi"}
                </h3>
                <p className="mb-6 max-w-sm text-center text-sm text-slate-400">
                  {questions.length === 0
                    ? "Kırpma Aracı ile PDF'den soru ekleyin. Sorular eklendiğinde önizleme otomatik oluşturulacak."
                    : "Yukarıdaki butona tıklayarak PDF önizlemesini oluşturabilirsiniz."}
                </p>
                {questions.length === 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      onClose();
                      navigate("/crop-tool");
                    }}
                    className="rounded-xl bg-gradient-to-r from-orange-500 to-orange-600 px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-orange-500/30 transition hover:from-orange-600 hover:to-orange-700 hover:shadow-orange-500/40"
                  >
                    Kırpma Aracına Git
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleGeneratePreview}
                    className="rounded-xl bg-gradient-to-r from-blue-500 to-blue-600 px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/30 transition hover:from-blue-600 hover:to-blue-700 hover:shadow-blue-500/40"
                  >
                    Önizleme Oluştur
                  </button>
                )}
              </div>
            )}
            {loading && (
              <div
                className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-2xl bg-gradient-to-br from-slate-800/98 via-slate-900/98 to-slate-800/98"
                style={{ backgroundColor: "rgba(15, 23, 42, 0.97)" }}
              >
                <div className="mb-6 rounded-2xl bg-gradient-to-br from-blue-500/20 to-blue-600/10 p-6 ring-1 ring-blue-400/20">
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="animate-pulse text-blue-400">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </div>
                <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
                <span className="mt-4 text-sm font-medium text-slate-300">
                  PDF önizlemesi hazırlanıyor...
                </span>
              </div>
            )}
            {error && (
              <div className="absolute inset-0 flex items-center justify-center">
                <p
                  className="rounded-lg border border-rose-300 bg-rose-50 px-8 py-5 text-rose-700"
                  style={{
                    fontSize: font.base,
                    fontWeight: fontWeight.medium,
                    lineHeight: lineHeight.normal,
                  }}
                >
                  {error}
                </p>
              </div>
            )}
            {!loading && !error && layoutReady && layout.length > 0 && (
              <div
                className="flex min-h-full min-w-full flex-1 items-start justify-center rounded-2xl bg-gradient-to-br from-slate-800/50 via-slate-800/30 to-slate-900/50 py-6"
                style={{ minHeight: 400 }}
              >
                <div className="relative inline-block">
                  <CanvasPdfPreview
                    layout={layout}
                    pageWpt={pageWpt}
                    pageHpt={pageHpt}
                    currentPage={currentPage}
                    zoom={zoom}
                    selectedQuestion={selectedQuestion}
                    onQuestionSelect={(idx) => {
                      setSelectedQuestion(idx);
                      const item = layout.find((l) => l.order_index === idx);
                      if (item) setCurrentPage(item.page_num);
                    }}
                    testTitle={testName?.trim() || "TEST"}
                    schoolName={schoolName?.trim() || ""}
                    themeColor={themeColor}
                    includeAnswerKey={options.includeAnswerKey}
                    answerKeyMode={previewAnswerKeyMode}
                    columns={columns}
                    marginTopMm={marginTopMm}
                    marginBottomMm={marginBottomMm}
                    marginLeftMm={marginLeftMm}
                    marginRightMm={marginRightMm}
                    columnGapMm={8}
                    includeDescription={options.includeDescription}
                    descriptionColumnCount={descriptionColumnCount ?? 1}
                    descriptionTexts={descriptionTexts ?? []}
                    descriptionColumnDividers={descriptionColumnDividers}
                    addTextOnLine={options.addTextOnLine}
                    centerLineText={centerLineText}
                    centerLineBold={centerLineBold}
                    centerLineItalic={centerLineItalic}
                    centerLineTextDirection={centerLineTextDirection}
                    watermarkEnabled={watermarkEnabled}
                    watermarkSettings={watermarkSettings}
                    writtenPaperHeader={isWritten}
                    writtenPaperTitle={isWritten ? writtenTitleForPreview : undefined}
                    writtenPaperFieldLines={isWritten ? writtenHeaderFieldLines : emptyWrittenHeaderFieldLines()}
                    writtenPaperFieldLabels={isWritten ? writtenHeaderFieldLabels : emptyWrittenHeaderFieldLabels()}
                    writtenPaperFieldHidden={isWritten ? writtenHeaderFieldHidden : emptyWrittenHeaderFieldHidden()}
                    writtenPaperBookletLetter={isWritten ? bookletLetterFromGroup(group) : "A"}
                    writtenPaperShowTeachers={writtenShowTeachers}
                    writtenPaperTeachers={writtenTeachersForPreview}
                    writtenPaperPrincipalName={principalName ?? ""}
                    lastQuestionPage={!isWritten && isTrial ? maxQuestionPage : undefined}
                  />
                  <ColumnOverlaySelector
                    enabled={
                      columnAdjustEnabled &&
                      currentPage <= maxQuestionPage &&
                      columns >= 1
                    }
                    columnRects={columnOverlayRectsPx}
                    selectedColumnIndex={columnPanel?.columnIndex0 ?? null}
                    onColumnPointerDown={handleColumnOverlayPointerDown}
                  />
                </div>
                <ColumnRedistributePopover
                  open={columnPanel != null}
                  anchor={columnPanel?.anchor ?? { x: 0, y: 0 }}
                  displayColumnNumber={(columnPanel?.columnIndex0 ?? 0) + 1}
                  mode={columnRedistMode}
                  onModeChange={setColumnRedistMode}
                  bottomGapMmInput={columnBottomGapMmInput}
                  onBottomGapMmChange={setColumnBottomGapMmInput}
                  anchoredDisabled={columnAnchoredDisabled}
                  equalDisabled={columnEqualDisabled}
                  inlineError={columnDistInlineError}
                  onPreview={handleColumnRedistPreview}
                  onApply={handleColumnRedistApply}
                  onCancel={handleColumnRedistCancel}
                  onReset={handleColumnRedistReset}
                />
              </div>
            )}
          </div>

          {!loading && !error && layoutReady && layout.length > 0 && (
            <div className="absolute bottom-6 left-1/2 flex -translate-x-1/2 shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5 py-1 shadow-md">
              <button
                type="button"
                title="Sütun seçip dikey dağıtım"
                onClick={() => {
                  if (columnAdjustEnabled) {
                    handleColumnRedistCancel();
                    setColumnAdjustEnabled(false);
                  } else {
                    setColumnAdjustEnabled(true);
                  }
                }}
                className={`rounded px-2 py-1 text-[0.625rem] font-bold uppercase tracking-wide transition ${
                  columnAdjustEnabled
                    ? "bg-blue-600 text-white hover:bg-blue-500"
                    : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                Sütun
              </button>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.max(0.3, z / 1.2))}
                className="rounded p-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                🔍−
              </button>
              <button
                type="button"
                onClick={() => setZoom(1)}
                className="rounded p-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                ⛶
              </button>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.min(3, z * 1.2))}
                className="rounded p-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                🔍+
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Alt bar - kırpma aracı bottom toolbar gibi */}
      <div
        className="flex shrink-0 items-center justify-between border-t border-slate-700 bg-slate-800"
        style={{
          padding: `${sizes.gap}px ${sizes.padding}px`,
          gap: sizes.gapSection,
        }}
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-700 text-slate-200 shadow-sm transition hover:bg-slate-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-slate-700"
            aria-label="Önceki sayfa"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <path fillRule="evenodd" d="M15.75 19.5L8.25 12l7.5-7.5" clipRule="evenodd" />
            </svg>
          </button>
          <span className="min-w-[4rem] shrink-0 text-center text-xs font-medium text-slate-300">
            {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            disabled={currentPage >= totalPages}
            onClick={() => setCurrentPage((p) => p + 1)}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-700 text-slate-200 shadow-sm transition hover:bg-slate-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-slate-700"
            aria-label="Sonraki sayfa"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <path fillRule="evenodd" d="M8.25 4.5l7.5 7.5-7.5 7.5" clipRule="evenodd" />
            </svg>
          </button>
          <select
            className="h-8 shrink-0 rounded-lg border-0 bg-slate-700 pl-3 pr-7 text-xs text-white transition hover:bg-slate-600 [&>option]:bg-slate-800"
            value={currentPage}
            onChange={(e) => setCurrentPage(Number(e.target.value))}
          >
            {Array.from({ length: totalPages },
              (_, i) => (
                <option key={i} value={i + 1}>
                  Sayfa {i + 1}
                </option>
              )
            )}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex shrink-0 items-center gap-1.5 text-xs text-slate-400">
            <span>Kalite:</span>
            <select
              value={quality}
              onChange={(e) => {
                const v = e.target.value as "normal" | "high" | "best";
                setQuality(v);
              }}
              className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-white"
            >
              <option value="normal">Normal (288 DPI)</option>
              <option value="high">Yüksek (432 DPI)</option>
              <option value="best">En İyi (576 DPI)</option>
            </select>
          </label>
          {saveError && (
            <span className="text-sm text-rose-400">{saveError}</span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border border-rose-600 bg-rose-600/20 px-3 py-1.5 text-xs font-medium text-rose-400 hover:bg-rose-600/40"
          >
            İptal
          </button>
          <button
            type="button"
            onClick={handleSavePdf}
            disabled={loading || savingPdf || questions.length === 0}
            className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {savingPdf ? "Kaydediliyor…" : "PDF'yi Kaydet"}
          </button>
        </div>
      </div>
    </div>
  );
}
