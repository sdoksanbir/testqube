/**
 * PDF soru alanı geometrisi — backend `desktop_export._compute_layout_geometry` ile uyumlu.
 * Önizleme sütun seçimi ve dikey dağıtım sınırları için kullanılır.
 */

import {
  approxWrittenHeaderHeightPt,
  emptyWrittenHeaderFieldHidden,
  emptyWrittenHeaderFieldLines,
  type WrittenHeaderFieldHidden,
  type WrittenHeaderFieldLines,
} from "../constants/writtenHeaderFields";

const PT_PER_INCH = 72;
const MM_PER_INCH = 25.4;

/** Backend `_FIRST_PAGE_BANNER_H_PT` */
export const FIRST_PAGE_BANNER_H_PT = 22;
/** Backend `_FIRST_PAGE_BANNER_GAP_PT` */
export const FIRST_PAGE_BANNER_GAP_PT = 2;
/** Backend `_OTHER_PAGES_BANNER_BELOW_GAP_PT` */
export const OTHER_PAGES_BANNER_BELOW_GAP_PT = 4;
/** Backend `_OTHER_PAGES_HEADER_H_PT` */
export const OTHER_PAGES_HEADER_H_PT = 4;
/** Backend `_OTHER_PAGES_HEADER_GAP_PT` */
export const OTHER_PAGES_HEADER_GAP_PT = 8;
/** Backend `ExportOptions.footer_top_offset_mm` */
export const FOOTER_TOP_OFFSET_MM = 12.35;

const DESC_BOX_PAD_V_PT = 6;
const DESC_LINE_H_PT = 10;

export function mmToPdfPt(mm: number): number {
  return (mm * PT_PER_INCH) / MM_PER_INCH;
}

function decodeHtmlEntitiesForDescription(s: string): string {
  if (!s) return "";
  return s
    .replace(/&nbsp;/gi, " ")
    .replace(/&#x0*A0;/gi, " ")
    .replace(/&#160;/gi, " ")
    .replace(/&#(\d+);/g, (_, code) => {
      const c = Number(code);
      if (c === 160) return " ";
      return String.fromCharCode(c);
    })
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => {
      const c = parseInt(h, 16);
      if (c === 0xa0) return " ";
      return String.fromCharCode(c);
    })
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function descriptionHtmlToLines(html: string): string[] {
  let t = (html || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<p(?:\s[^>]*)?>/gi, "\n")
    .replace(/<li(?:\s[^>]*)?>/gi, "\n• ")
    .replace(/<\/li>/gi, "\n")
    .replace(/<[^>]+>/g, " ");
  t = decodeHtmlEntitiesForDescription(t);
  const lines = t
    .split("\n")
    .map((x) => x.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return lines.length ? lines : [""];
}

function descriptionBoxHeightPt(maxLines: number): number {
  return DESC_BOX_PAD_V_PT * 2 + maxLines * DESC_LINE_H_PT;
}

/** Backend `_DESC_BOX_GAP_BELOW_PT` */
const DESC_BOX_GAP_BELOW_PT = 6;

export type LayoutGeometryInput = {
  pageWpt: number;
  pageHpt: number;
  marginTopMm: number;
  marginBottomMm: number;
  marginLeftMm: number;
  marginRightMm: number;
  columns: number;
  columnGapMm: number;
  /** 1-based sayfa */
  pageNum: number;
  writtenPaperHeader: boolean;
  writtenPaperTitle?: string;
  writtenPaperFieldLines?: WrittenHeaderFieldLines;
  writtenPaperFieldHidden?: WrittenHeaderFieldHidden;
  includeDescription: boolean;
  descriptionColumnCount: number;
  descriptionTexts: string[];
};

export type PdfColumnBand = {
  /** Soru paketleme üst sınırı (PDF pt, y yukarı) — backend `content_top_*` */
  contentTopPt: number;
  /**
   * Footer bandının üst çizgisi (PDF pt) — backend `content_bottom`, Canvas `footerTopPt`.
   * Mod 2 alt boşluk: son soru görsel altı ile bu çizgi arası mesafe.
   */
  contentBottomPt: number;
  columnXPt: number[];
  colWidthPt: number;
  colGapPt: number;
};

function contentTopFirstPt(input: LayoutGeometryInput): number {
  const { pageHpt, marginTopMm } = input;
  const mt = mmToPdfPt(marginTopMm);
  if (input.writtenPaperHeader) {
    const h = approxWrittenHeaderHeightPt(
      input.writtenPaperFieldLines ?? emptyWrittenHeaderFieldLines(),
      input.writtenPaperTitle ?? "",
      Math.max(100, input.pageWpt - mmToPdfPt(input.marginLeftMm) - mmToPdfPt(input.marginRightMm) - 8),
      input.writtenPaperFieldHidden ?? emptyWrittenHeaderFieldHidden()
    );
    return pageHpt - mt - h;
  }
  if (input.includeDescription) {
    const colCount = Math.max(1, Math.min(3, input.descriptionColumnCount || 1));
    const textsIn = (input.descriptionTexts ?? []).slice(0, colCount);
    const maxLines = Math.max(
      1,
      ...textsIn.map((h) => descriptionHtmlToLines(h ?? "").length)
    );
    const boxHpt = descriptionBoxHeightPt(maxLines);
    return pageHpt - mt - FIRST_PAGE_BANNER_H_PT - FIRST_PAGE_BANNER_GAP_PT - boxHpt - DESC_BOX_GAP_BELOW_PT;
  }
  return pageHpt - mt - FIRST_PAGE_BANNER_H_PT - FIRST_PAGE_BANNER_GAP_PT;
}

function contentTopOtherPt(input: LayoutGeometryInput): number {
  const { pageHpt, marginTopMm } = input;
  const mt = mmToPdfPt(marginTopMm);
  if (input.writtenPaperHeader) {
    return pageHpt - mt - OTHER_PAGES_HEADER_H_PT - OTHER_PAGES_HEADER_GAP_PT;
  }
  return pageHpt - mt - FIRST_PAGE_BANNER_H_PT - OTHER_PAGES_BANNER_BELOW_GAP_PT;
}

/**
 * Belirli sayfa için içerik bandı ve sütun x konumları (PDF pt).
 */
export function computePageColumnBand(input: LayoutGeometryInput): PdfColumnBand {
  const ml = mmToPdfPt(input.marginLeftMm);
  const mr = mmToPdfPt(input.marginRightMm);
  const mb = mmToPdfPt(input.marginBottomMm);
  const cols = Math.max(1, Math.min(6, input.columns));
  const colGap = mmToPdfPt(input.columnGapMm);
  const contentW = input.pageWpt - ml - mr;
  const colW =
    cols > 1 ? (contentW - (cols - 1) * colGap) / cols : contentW;
  const columnXPt = Array.from({ length: cols }, (_, i) => ml + i * (colW + colGap));
  const contentBottomPt = mb + mmToPdfPt(FOOTER_TOP_OFFSET_MM);
  const contentTopPt =
    input.pageNum <= 1 ? contentTopFirstPt(input) : contentTopOtherPt(input);
  return {
    contentTopPt,
    contentBottomPt,
    columnXPt,
    colWidthPt: colW,
    colGapPt: colGap,
  };
}

const X_MATCH_EPS_PT = 1.5;

/**
 * Soru kutusunun `x_pt` değerinden sütun indeksi (0-based).
 */
export function columnIndexFromQuestionXPt(
  xPt: number,
  band: PdfColumnBand
): number {
  const { columnXPt, colWidthPt } = band;
  if (columnXPt.length <= 1) return 0;
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < columnXPt.length; i++) {
    const d = Math.abs(xPt - columnXPt[i]);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  if (bestD > colWidthPt + band.colGapPt) {
    for (let i = 0; i < columnXPt.length; i++) {
      if (xPt >= columnXPt[i] - X_MATCH_EPS_PT && xPt <= columnXPt[i] + colWidthPt + X_MATCH_EPS_PT) {
        return i;
      }
    }
  }
  return best;
}

export type ColumnContentRectPx = {
  leftPx: number;
  topPx: number;
  widthPx: number;
  heightPx: number;
};

/**
 * Önizleme canvas'ında sütun tıklama alanı (CSS px, canvas ile aynı ölçek).
 */
export function columnContentRectsPx(
  band: PdfColumnBand,
  pageHpt: number,
  canvasScale: number
): ColumnContentRectPx[] {
  const topPt = band.contentTopPt;
  const bottomPt = band.contentBottomPt;
  const heightPt = Math.max(0, topPt - bottomPt);
  const topPx = (pageHpt - topPt) * canvasScale;
  const heightPx = heightPt * canvasScale;
  return band.columnXPt.map((x) => ({
    leftPx: x * canvasScale,
    topPx,
    widthPx: band.colWidthPt * canvasScale,
    heightPx,
  }));
}
