/**
 * Canvas-based PDF preview - original-desktop PDFPreviewWidget mantığıyla.
 * PDF blob yerine layout + soru görsellerini canvas'a çizer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { LayoutItem } from "../../api/client";
import {
  approxWrittenHeaderHeightPt,
  approxWrittenRuleDownFromInnerTopPt,
  emptyWrittenHeaderFieldHidden,
  emptyWrittenHeaderFieldLabels,
  emptyWrittenHeaderFieldLines,
  writtenHeaderBlockLayoutPt,
  writtenHeaderLabelPdfLeft,
  writtenHeaderLabelPdfPuan,
  wrapTitleLinesWithMeasure,
  type WrittenHeaderFieldHidden,
  type WrittenHeaderFieldLabels,
  type WrittenHeaderFieldLines,
} from "../../constants/writtenHeaderFields";
import {
  computeAnswerKeyLayout,
  ANSWER_KEY_LAYOUT,
} from "../../utils/answerKeyLayout";

const PT_PER_INCH = 72;
const SCREEN_DPI = 96;
const PT_TO_PX = SCREEN_DPI / PT_PER_INCH; // ~1.333
const PT_TO_MM = 25.4 / PT_PER_INCH;

function mmToPt(mm: number): number {
  return (mm * PT_PER_INCH) / 25.4;
}

function hexToRgb(hex: string): [number, number, number] {
  const s = (hex || "").trim().replace(/^#/, "");
  if (s.length !== 6) return [0.68, 0.8, 0.98];
  return [
    parseInt(s.slice(0, 2), 16) / 255,
    parseInt(s.slice(2, 4), 16) / 255,
    parseInt(s.slice(4, 6), 16) / 255,
  ];
}

/** PDF `desktop_export._html_to_lines` ile uyumlu: etiketler + `html.unescape` benzeri varlıklar. */
const DESC_BOX_PAD_V_PT = 6;
const DESC_LINE_H_PT = 10;

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

type CanvasPdfPreviewProps = {
  layout: LayoutItem[];
  pageWpt: number;
  pageHpt: number;
  currentPage: number;
  zoom: number;
  selectedQuestion: number;
  onQuestionSelect: (index: number) => void;
  testTitle: string;
  schoolName: string;
  themeColor: string;
  includeAnswerKey: boolean;
  /** per_page: footer | separate_page: ayrı sayfa | end_of_test: son soru altı */
  answerKeyMode?: "per_page" | "separate_page" | "end_of_test";
  columns: number;
  /** Backend layout ile uyum için margin değerleri (mm) */
  marginTopMm?: number;
  marginBottomMm?: number;
  marginLeftMm?: number;
  marginRightMm?: number;
  columnGapMm?: number;
  /** Test ile ilgili açıklama ekle - banner altında kutu */
  includeDescription?: boolean;
  /** Açıklama sütun sayısı (1–3) */
  descriptionColumnCount?: number;
  /** Sütun bazlı açıklama metinleri */
  descriptionTexts?: string[];
  /** 2+ sütunda açıklama kutusunda dikey ayırıcı çizgiler */
  descriptionColumnDividers?: boolean;
  /** Çizgi üzerine yazı ekle */
  addTextOnLine?: boolean;
  /** Çizgi üzeri metin */
  centerLineText?: string;
  /** Çizgi üzeri kalın */
  centerLineBold?: boolean;
  /** Çizgi üzeri italik */
  centerLineItalic?: boolean;
  /** Çizgi üzeri yazı yönü */
  centerLineTextDirection?: "up" | "down";
  /** Filigran etkin */
  watermarkEnabled?: boolean;
  /** Filigran ayarları */
  watermarkSettings?: {
    mode: "text" | "image";
    text: string;
    textOpacityPct: number;
    textSizePct: number;
    textAngleDeg: number;
    textColor: string;
    imageBase64: string | null;
    imageOpacityPct: number;
    imageSizePct: number;
  };
  /** Thumbnail modda tıklama devre dışı, sadece görüntü */
  interactive?: boolean;
  /** Thumbnail genişliği (px) - verilirse zoom otomatik hesaplanır, sütuna tam sığar */
  thumbnailWidthPx?: number;
  /** Yazılı kağıdı: üst blok başlığı (yükseklik satır sayısına göre) */
  writtenPaperHeader?: boolean;
  writtenPaperTitle?: string;
  writtenPaperFieldLines?: WrittenHeaderFieldLines;
  writtenPaperFieldLabels?: WrittenHeaderFieldLabels;
  writtenPaperFieldHidden?: WrittenHeaderFieldHidden;
  writtenPaperBookletLetter?: string;
  /** Yazılı: öğretmen adları + sağ sütun imza çizgileri (PDF ile uyumlu) */
  writtenPaperShowTeachers?: boolean;
  writtenPaperTeachers?: { name: string; title?: string }[];
  /** Yazılı son sayfa: okul müdürü adı soyadı */
  writtenPaperPrincipalName?: string;
  /** Test/deneme: son soru sayfası numarası — TEST BİTTİ bu sayfada; cevap anahtarı sayfalarında sağ metin yok */
  lastQuestionPage?: number;
};

export default function CanvasPdfPreview({
  layout,
  pageWpt,
  pageHpt,
  currentPage,
  zoom,
  selectedQuestion,
  onQuestionSelect,
  testTitle,
  schoolName,
  themeColor,
  includeAnswerKey,
  answerKeyMode = "per_page",
  columns,
  includeDescription = false,
  descriptionColumnCount = 1,
  descriptionTexts = [],
  descriptionColumnDividers = false,
  addTextOnLine = false,
  centerLineText = "",
  centerLineBold = false,
  centerLineItalic = false,
  centerLineTextDirection = "up",
  watermarkEnabled = false,
  watermarkSettings,
  interactive = true,
  thumbnailWidthPx,
  marginTopMm = 15,
  marginBottomMm = 15,
  marginLeftMm = 15,
  marginRightMm = 15,
  columnGapMm = 8,
  writtenPaperHeader = false,
  writtenPaperTitle = "",
  writtenPaperFieldLines = emptyWrittenHeaderFieldLines(),
  writtenPaperFieldLabels = emptyWrittenHeaderFieldLabels(),
  writtenPaperFieldHidden = emptyWrittenHeaderFieldHidden(),
  writtenPaperBookletLetter = "A",
  writtenPaperShowTeachers = false,
  writtenPaperTeachers = [],
  writtenPaperPrincipalName = "",
  lastQuestionPage,
}: CanvasPdfPreviewProps) {
  /** Obje referansı bazen güncellenmese bile içerik değişiminde çizimi tetikler (ör. PUAN etiketi) */
  const writtenFieldLabelsSig = JSON.stringify(writtenPaperFieldLabels);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [images, setImages] = useState<Map<number, HTMLImageElement>>(new Map());
  const [watermarkImage, setWatermarkImage] = useState<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!watermarkEnabled || !watermarkSettings?.imageBase64) {
      setWatermarkImage(null);
      return;
    }
    const img = new Image();
    const dataUrl = watermarkSettings.imageBase64.startsWith("data:")
      ? watermarkSettings.imageBase64
      : `data:image/png;base64,${watermarkSettings.imageBase64}`;
    img.onload = () => setWatermarkImage(img);
    img.onerror = () => setWatermarkImage(null);
    img.src = dataUrl;
    return () => setWatermarkImage(null);
  }, [watermarkEnabled, watermarkSettings?.imageBase64]);

  const effectiveZoom = thumbnailWidthPx != null
    ? thumbnailWidthPx / (pageWpt * PT_TO_PX)
    : zoom;
  const scale = PT_TO_PX * effectiveZoom;
  const pageWpx = pageWpt * scale;
  const pageHpx = pageHpt * scale;

  // Layout'tan gelen base64 görselleri yükle
  useEffect(() => {
    let cancelled = false;
    const next = new Map<number, HTMLImageElement>();
    let pending = 0;
    layout.forEach((item) => {
      const b64 = item.image_base64;
      if (!b64) return;
      const img = new Image();
      const orderIdx = item.order_index;
      pending++;
      img.onload = () => {
        if (cancelled) return;
        next.set(orderIdx, img);
        setImages((prev) => new Map([...prev.entries(), ...next.entries()]));
      };
      img.onerror = () => {
        if (cancelled) return;
        pending--;
        if (pending === 0) setImages((prev) => new Map([...prev.entries(), ...next.entries()]));
      };
      const prefix = b64.startsWith("data:") ? "" : "data:image/png;base64,";
      img.src = prefix + b64;
    });
    if (pending === 0 && layout.some((l) => l.image_base64)) {
      setImages(next);
    }
    return () => { cancelled = true; };
  }, [layout]);

  const ptToCanvas = useCallback(
    (xPt: number, yTopPt: number) => {
      return {
        x: xPt * scale,
        y: (pageHpt - yTopPt) * scale,
      };
    },
    [scale, pageHpt]
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || layout.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    try {

    const mlPt = mmToPt(marginLeftMm);
    const mrPt = mmToPt(marginRightMm);
    const mtPt = mmToPt(marginTopMm);
    const mbPt = mmToPt(marginBottomMm);
    const footerTopOffsetMm = 12.35;
    const footerBottomOffsetMm = 5.28;
    const footerTopPt = mbPt + mmToPt(footerTopOffsetMm);
    const footerBottomPt = mbPt + mmToPt(footerBottomOffsetMm);
    const ml = mlPt * scale;
    const mr = mrPt * scale;
    const theme = hexToRgb(themeColor);

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, pageWpx, pageHpx);

    // Header style3 - İlk sayfa: dış çerçeve + 3 kutu (boş, dolu, boş); Diğer: tek kutu sol başlık sağ okul
    const contentW = pageWpt - mlPt - mrPt;
    const themeRgb = `rgb(${Math.round(theme[0] * 255)}, ${Math.round(theme[1] * 255)}, ${Math.round(theme[2] * 255)})`;
    /** PDF `desktop_export._DIVIDER_LINE_WIDTH_PT` ile aynı — yazılı çizgiler tek kalınlık */
    const writtenRuleLw = 0.9 * scale;
    const writtenStrokeRgb = "#000000";

    const maxQuestionPage = layout.length > 0 ? Math.max(...layout.map((l) => l.page_num)) : 1;
    const answerKeyItems: [number, string][] = layout
      .filter((l) => l.display_number != null)
      .sort((a, b) => (a.display_number as number) - (b.display_number as number))
      .map((l) => [
        l.display_number as number,
        (l.answer_key || "?").trim().toUpperCase() || "?",
      ]);
    const isAnswerKeyOnlyPage =
      includeAnswerKey &&
      answerKeyMode === "separate_page" &&
      currentPage > maxQuestionPage;

    const drawRoundRectLeft = (
      x: number,
      y: number,
      w: number,
      h: number,
      r: number
    ) => {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w, y);
      ctx.lineTo(x + w, y + h);
      ctx.lineTo(x, y + h);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    };

    const drawAnswerKeyTable = (
      areaX: number,
      tableYTop: number,
      maxAreaW: number,
      items: [number, string][],
      entriesPerRow: number,
      title: string
    ) => {
      const layout = computeAnswerKeyLayout({
        items,
        totalWidthPx: maxAreaW,
        columnCount: entriesPerRow,
        scale,
      });
      const {
        tableWidthPx,
        tableHeightPx,
        headerHeightPx,
        rowHeightPx,
        cellWidthPx,
        rowCount,
        columnCount,
      } = layout;

      const tableX = areaX;
      const tableYBottom = tableYTop + tableHeightPx;

      ctx.fillStyle = "#ffffff";
      ctx.fillRect(tableX, tableYTop, tableWidthPx, tableHeightPx);

      const headerBg = `rgba(${Math.round(theme[0] * 255)}, ${Math.round(theme[1] * 255)}, ${Math.round(theme[2] * 255)}, 0.25)`;
      ctx.fillStyle = headerBg;
      ctx.fillRect(tableX, tableYTop, tableWidthPx, headerHeightPx);

      ctx.strokeStyle = themeRgb;
      ctx.lineWidth = ANSWER_KEY_LAYOUT.BORDER_WIDTH_PT * scale;
      ctx.strokeRect(tableX, tableYTop, tableWidthPx, tableHeightPx);

      ctx.fillStyle = themeRgb;
      ctx.font = `bold ${ANSWER_KEY_LAYOUT.TITLE_FONT_PT * scale}px Arial, Helvetica`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(
        ((title || "CEVAP ANAHTARI").trim().toUpperCase()).slice(0, 50),
        tableX + tableWidthPx / 2,
        tableYTop + headerHeightPx / 2
      );

      const cellFontSize = ANSWER_KEY_LAYOUT.CELL_FONT_PT * scale;
      ctx.font = `bold ${cellFontSize}px Arial, Helvetica`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#000000";

      for (let c = 0; c < columnCount; c++) {
        const cellCenterX = tableX + (c + 0.5) * cellWidthPx;
        for (let r = 0; r < rowCount; r++) {
          const idx = r * columnCount + c;
          if (idx >= items.length) break;
          const [num, ans] = items[idx];
          const cellCenterY =
            tableYTop +
            headerHeightPx +
            (r + 0.5) * rowHeightPx;
          const text = `${num}. ${(ans || "?").trim().toUpperCase() || "?"}`;
          ctx.font = `bold ${cellFontSize}px Arial, Helvetica`;
          ctx.fillText(text, cellCenterX, cellCenterY);
        }
      }

      ctx.strokeStyle = themeRgb;
      ctx.lineWidth = ANSWER_KEY_LAYOUT.GRID_LINE_WIDTH_PT * scale;
      for (let c = 1; c < columnCount; c++) {
        const lineX = tableX + c * cellWidthPx;
        ctx.beginPath();
        ctx.moveTo(lineX, tableYTop + headerHeightPx);
        ctx.lineTo(lineX, tableYBottom);
        ctx.stroke();
      }
      for (let r = 1; r <= rowCount; r++) {
        const rowY = tableYTop + headerHeightPx + r * rowHeightPx;
        ctx.beginPath();
        ctx.moveTo(tableX, rowY);
        ctx.lineTo(tableX + tableWidthPx, rowY);
        ctx.stroke();
      }
    };

    const drawRoundRect = (
      x: number,
      y: number,
      w: number,
      h: number,
      r: number
    ) => {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    };

    const drawRoundRectRight = (
      x: number,
      y: number,
      w: number,
      h: number,
      r: number
    ) => {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h);
      ctx.lineTo(x + w - r, y + h);
      ctx.lineTo(x, y + h);
      ctx.lineTo(x, y);
      ctx.lineTo(x + r, y);
      ctx.closePath();
    };

    const drawPremiumPattern = (
      x: number,
      y: number,
      w: number,
      h: number,
      pad: number,
      slope: number
    ) => {
      ctx.save();
      ctx.globalAlpha = 0.72;
      ctx.strokeStyle = themeRgb;
      ctx.fillStyle = themeRgb;
      ctx.lineWidth = 0.2 * scale;
      const ix = x + pad;
      const iy = y + pad;
      const iw = w - 2 * pad;
      const ih = h - 2 * pad;
      const dotR = 0.48 * scale;
      const step = 3.35 * scale;
      for (let px = ix; px < ix + iw; px += step) {
        for (let py = iy; py < iy + ih; py += step) {
          ctx.beginPath();
          ctx.arc(px, py, dotR, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.restore();
    };

    if (!isAnswerKeyOnlyPage && currentPage === 1 && writtenPaperHeader && (writtenPaperTitle || "").trim()) {
      const titleMaxWPt = Math.max(100, contentW - 8);
      const writtenHpt = approxWrittenHeaderHeightPt(
        writtenPaperFieldLines,
        writtenPaperTitle,
        titleMaxWPt,
        writtenPaperFieldHidden
      );
      const boxY = pageHpt - mtPt - writtenHpt;
      const boxYCanvas = (pageHpt - boxY - writtenHpt) * scale;
      const padTop = 2 * scale;
      const s = scale;

      const title = (writtenPaperTitle || "").trim();
      ctx.fillStyle = "#111827";
      ctx.font = `bold ${10 * s}px Helvetica, Arial`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      let yText = boxYCanvas + padTop;
      const titleLineH = 11 * s;
      const maxTitlePx = (titleMaxWPt - 2) * scale;
      const titleLines = wrapTitleLinesWithMeasure(title, (t) => ctx.measureText(t).width, maxTitlePx);
      const cxTitle = ml + (contentW * scale) / 2;
      for (const ln of titleLines) {
        ctx.fillText(ln.slice(0, 220), cxTitle, yText);
        yText += titleLineH;
      }

      const rulePdfY =
        boxY + mmToPt(2) + 0.9 / 2;
      const lineYCanvas = (pageHpt - rulePdfY) * scale;
      const yFields = yText + 17 * s;
      const xLeftPx = ml;
      const cxPx = ml + (contentW * scale) / 2;
      const formLineCapX = cxPx - 26 * s;
      const formLineLenPx = 100 * s;
      const lblGap = 4 * s;
      const rowH = 11 * s;
      const rowGap = 8 * s;

      const { nAd, nNum, nSin, blockBody } = writtenHeaderBlockLayoutPt(
        writtenPaperFieldLines,
        writtenPaperFieldHidden
      );

      const adiLbl = writtenHeaderLabelPdfLeft("ad_soyad", writtenPaperFieldLabels);
      const numLbl = writtenHeaderLabelPdfLeft("numara", writtenPaperFieldLabels);
      const sinLbl = writtenHeaderLabelPdfLeft("sinif", writtenPaperFieldLabels);
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#111827";

      ctx.font = `bold ${8 * s}px Helvetica, Arial`;
      const wLblSlot = Math.max(
        ctx.measureText(adiLbl).width,
        ctx.measureText(numLbl).width,
        ctx.measureText(sinLbl).width
      );
      const xLblRight = xLeftPx + wLblSlot;
      const xLine0 = xLblRight + lblGap;
      const xLineEnd = Math.min(xLine0 + formLineLenPx, formLineCapX);

      let yrCanvas = yFields;
      if (nAd > 0) {
        for (let j = 0; j < nAd; j++) {
          const yrow = yrCanvas + j * rowH;
          if (j === 0) {
            ctx.font = `bold ${8 * s}px Helvetica, Arial`;
            ctx.textAlign = "right";
            ctx.fillText(adiLbl, xLblRight, yrow);
            ctx.textAlign = "left";
          }
          ctx.font = `${8 * s}px Helvetica, Arial`;
          ctx.strokeStyle = writtenStrokeRgb;
          ctx.lineWidth = writtenRuleLw;
          ctx.beginPath();
          ctx.moveTo(xLine0, yrow + 2 * s);
          ctx.lineTo(xLineEnd, yrow + 2 * s);
          ctx.stroke();
        }
        yrCanvas += nAd * rowH;
        if (nNum || nSin) yrCanvas += rowGap;
      }
      if (nNum > 0) {
        const yNumBase = yrCanvas;
        for (let j = 0; j < nNum; j++) {
          const yrow = yNumBase + j * rowH;
          if (j === 0) {
            ctx.font = `bold ${8 * s}px Helvetica, Arial`;
            ctx.textAlign = "right";
            ctx.fillText(numLbl, xLblRight, yrow);
            ctx.textAlign = "left";
          }
          ctx.font = `${8 * s}px Helvetica, Arial`;
          ctx.strokeStyle = writtenStrokeRgb;
          ctx.lineWidth = writtenRuleLw;
          ctx.beginPath();
          ctx.moveTo(xLine0, yrow + 2 * s);
          ctx.lineTo(xLineEnd, yrow + 2 * s);
          ctx.stroke();
        }
        yrCanvas += nNum * rowH;
        if (nSin) yrCanvas += rowGap;
      }
      if (nSin > 0) {
        const ySinBase = yrCanvas;
        for (let j = 0; j < nSin; j++) {
          const yrow = ySinBase + j * rowH;
          if (j === 0) {
            ctx.font = `bold ${8 * s}px Helvetica, Arial`;
            ctx.textAlign = "right";
            ctx.fillText(sinLbl, xLblRight, yrow);
            ctx.textAlign = "left";
          }
          ctx.font = `${8 * s}px Helvetica, Arial`;
          ctx.strokeStyle = writtenStrokeRgb;
          ctx.lineWidth = writtenRuleLw;
          ctx.beginPath();
          ctx.moveTo(xLine0, yrow + 2 * s);
          ctx.lineTo(xLineEnd, yrow + 2 * s);
          ctx.stroke();
        }
      }

      const blockHPx = blockBody * scale;
      const yMid = yFields + blockHPx / 2 - 2 * s;

      const bookletLt = (writtenPaperBookletLetter || "").trim();
      if (bookletLt) {
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.font = `bold ${26 * s}px Helvetica, Arial`;
        ctx.fillStyle = themeRgb;
        ctx.fillText(bookletLt, cxPx, yMid);
      }

      if (!writtenPaperFieldHidden.puan) {
        const puanBoxSz = 40 * s;
        const puanR = 4 * s;
        const boxLeft = pageWpx - mr - puanBoxSz;
        const boxTopY = yMid - puanBoxSz / 2;

        ctx.strokeStyle = writtenStrokeRgb;
        ctx.lineWidth = writtenRuleLw;
        ctx.beginPath();
        ctx.roundRect(boxLeft, boxTopY, puanBoxSz, puanBoxSz, puanR);
        ctx.stroke();

        ctx.font = `bold ${8 * s}px Helvetica, Arial`;
        ctx.fillStyle = "#111827";
        ctx.textAlign = "center";
        ctx.textBaseline = "alphabetic";
        ctx.fillText(
          writtenHeaderLabelPdfPuan(writtenPaperFieldLabels).slice(0, 40),
          boxLeft + puanBoxSz / 2,
          boxTopY - 3 * s
        );
      }

      ctx.beginPath();
      ctx.strokeStyle = writtenStrokeRgb;
      ctx.lineWidth = writtenRuleLw;
      ctx.moveTo(ml, lineYCanvas);
      ctx.lineTo(pageWpx - mr, lineYCanvas);
      ctx.stroke();
    } else if (!isAnswerKeyOnlyPage && currentPage === 1) {
      const boxH = 22;
      const totalH = boxH;
      const boxY = pageHpt - mtPt - totalH;
      const boxYCanvas = (pageHpt - boxY - totalH) * scale;
      const gap = 2;
      const leftW = contentW * 0.35;
      const midW = contentW * 0.3;
      const rightW = contentW - leftW - midW - 2 * gap;
      // Yatay (sol-orta-sağ) ve dikey (banner altı) boşluk eşit
      const xLeft = mlPt;
      const xMid = mlPt + leftW + gap;
      const xRight = mlPt + leftW + midW + 2 * gap;
      const innerH = boxH;
      const leftWpx = leftW * scale;
      const midWpx = midW * scale;
      const rightWpx = rightW * scale;
      const innerBoxYCanvas = boxYCanvas;
      const r = 6 * scale;

      ctx.lineWidth = 1.0 * scale;
      ctx.strokeStyle = themeRgb;
      ctx.save();
      drawRoundRectLeft(xLeft * scale, innerBoxYCanvas, leftWpx, innerH * scale, r);
      ctx.clip();
      drawPremiumPattern(xLeft * scale, innerBoxYCanvas, leftWpx, innerH * scale, 2 * scale, 1);
      ctx.restore();
      drawRoundRectLeft(xLeft * scale, innerBoxYCanvas, leftWpx, innerH * scale, r);
      ctx.stroke();
      ctx.fillStyle = themeRgb;
      ctx.fillRect(xMid * scale, innerBoxYCanvas, midWpx, innerH * scale);
      ctx.strokeStyle = themeRgb;
      ctx.strokeRect(xMid * scale, innerBoxYCanvas, midWpx, innerH * scale);
      ctx.save();
      drawRoundRectRight(xRight * scale, innerBoxYCanvas, rightWpx, innerH * scale, r);
      ctx.clip();
      drawPremiumPattern(xRight * scale, innerBoxYCanvas, rightWpx, innerH * scale, 2 * scale, -1);
      ctx.restore();
      drawRoundRectRight(xRight * scale, innerBoxYCanvas, rightWpx, innerH * scale, r);
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = `bold ${12 * scale}px Helvetica, Arial`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(
        (testTitle || "TEST").slice(0, 40),
        xMid * scale + midWpx / 2,
        innerBoxYCanvas + (innerH * scale) / 2
      );

      if (includeDescription) {
        const colCount = Math.max(1, Math.min(3, descriptionColumnCount || 1));
        const textsIn = descriptionTexts && descriptionTexts.length >= colCount
          ? descriptionTexts.slice(0, colCount)
          : [""];
        const linesPerCol: string[][] = [];
        for (let i = 0; i < colCount; i++) {
          const l = descriptionHtmlToLines(textsIn[i] ?? "");
          linesPerCol.push(l.length ? l : [""]);
        }
        const maxLines = Math.max(1, ...linesPerCol.map((ll) => ll.length));
        const lineH = DESC_LINE_H_PT;
        const padTop = DESC_BOX_PAD_V_PT;
        const padBottom = DESC_BOX_PAD_V_PT;
        const boxH = padTop + maxLines * lineH + padBottom;
        const boxGapBelow = gap;
        const boxYCanvas = innerBoxYCanvas + innerH * scale + boxGapBelow * scale;
        const pad = 6 * scale;
        const r = 6 * scale;
        ctx.strokeStyle = themeRgb;
        ctx.fillStyle = "#ffffff";
        ctx.lineWidth = 1.0 * scale;
        ctx.beginPath();
        ctx.moveTo(ml, boxYCanvas);
        ctx.lineTo(pageWpx - mr, boxYCanvas);
        ctx.lineTo(pageWpx - mr, boxYCanvas + boxH * scale - r);
        ctx.quadraticCurveTo(pageWpx - mr, boxYCanvas + boxH * scale, pageWpx - mr - r, boxYCanvas + boxH * scale);
        ctx.lineTo(ml + r, boxYCanvas + boxH * scale);
        ctx.quadraticCurveTo(ml, boxYCanvas + boxH * scale, ml, boxYCanvas + boxH * scale - r);
        ctx.lineTo(ml, boxYCanvas);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        const contentW = pageWpx - ml - mr;
        const colW = contentW / colCount;
        ctx.fillStyle = "#262626";
        ctx.font = `${8 * scale}px Helvetica, Arial`;
        ctx.textBaseline = "middle";
        const textOffset = 3 * scale;
        for (let colIdx = 0; colIdx < colCount; colIdx++) {
          const xLeft = ml + colIdx * colW;
          const lines = linesPerCol[colIdx];
          ctx.save();
          ctx.beginPath();
          ctx.rect(xLeft + pad, boxYCanvas, colW - 2 * pad, boxH * scale);
          ctx.clip();
          for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
            const yLine = boxYCanvas + padTop * scale + (lineIdx + 0.5) * lineH * scale - textOffset;
            const txt = (lines[lineIdx] || "").slice(0, 120);
            if (!txt) continue;
            ctx.textAlign = "left";
            if (colCount === 1 && colIdx === 0) {
              if (lineIdx === 0) {
                ctx.fillText("AÇIKLAMA", ml + pad, yLine);
                ctx.fillText(txt, ml + pad + 55 * scale, yLine);
              } else {
                ctx.fillText(txt, ml + pad + 55 * scale, yLine);
              }
            } else {
              ctx.fillText(txt, xLeft + pad, yLine);
            }
          }
          ctx.restore();
        }
        if (colCount > 1 && descriptionColumnDividers) {
          ctx.strokeStyle = themeRgb;
          ctx.lineWidth = 0.55 * scale;
          for (let b = 1; b < colCount; b += 1) {
            const xDiv = ml + b * colW;
            ctx.beginPath();
            ctx.moveTo(xDiv, boxYCanvas);
            ctx.lineTo(xDiv, boxYCanvas + boxH * scale);
            ctx.stroke();
          }
        }
      }
    } else if (!isAnswerKeyOnlyPage && currentPage > 1 && writtenPaperHeader) {
      const linePdfY = pageHpt - mtPt - 2;
      const yLineCanvas = (pageHpt - linePdfY) * scale;
      ctx.strokeStyle = writtenStrokeRgb;
      ctx.lineWidth = writtenRuleLw;
      ctx.beginPath();
      ctx.moveTo(ml, yLineCanvas);
      ctx.lineTo(pageWpx - mr, yLineCanvas);
      ctx.stroke();
    } else if (!isAnswerKeyOnlyPage && currentPage > 1) {
      // Test / deneme diğer sayfalar: noktalı dolgu, dış çerçeve; yazılar beyaz zemin üstünde (çizgisiz)
      const boxHpt = 22;
      const boxY = pageHpt - mtPt - boxHpt;
      const innerBoxYCanvas = (pageHpt - boxY - boxHpt) * scale;
      const innerHPx = boxHpt * scale;
      const wPx = contentW * scale;
      const x0 = ml;
      const rPx = Math.min(5 * scale, wPx / 2 - 1, innerHPx / 2 - 1);
      const k = 0.5522847498;
      const traceOtherPageBannerPath = () => {
        ctx.beginPath();
        ctx.moveTo(x0, innerBoxYCanvas + innerHPx);
        ctx.lineTo(x0 + wPx, innerBoxYCanvas + innerHPx);
        ctx.lineTo(x0 + wPx, innerBoxYCanvas + rPx);
        ctx.bezierCurveTo(
          x0 + wPx,
          innerBoxYCanvas + rPx * (1 - k),
          x0 + wPx - rPx + k * rPx,
          innerBoxYCanvas,
          x0 + wPx - rPx,
          innerBoxYCanvas
        );
        ctx.lineTo(x0 + rPx, innerBoxYCanvas);
        ctx.bezierCurveTo(
          x0 + rPx - k * rPx,
          innerBoxYCanvas,
          x0,
          innerBoxYCanvas + rPx * (1 - k),
          x0,
          innerBoxYCanvas + rPx
        );
        ctx.lineTo(x0, innerBoxYCanvas + innerHPx);
        ctx.closePath();
      };

      traceOtherPageBannerPath();
      ctx.save();
      ctx.clip();
      drawPremiumPattern(x0, innerBoxYCanvas, wPx, innerHPx, 2 * scale, 1);
      ctx.restore();

      traceOtherPageBannerPath();
      ctx.strokeStyle = themeRgb;
      ctx.lineWidth = 1.0 * scale;
      ctx.stroke();

      const padX = 8 * scale;
      const padW = 4 * scale;
      const padV = 3 * scale;
      const halfPx = Math.max(30 * scale, wPx / 2 - 10 * scale);
      ctx.font = `bold ${10 * scale}px Helvetica, Arial`;
      let titleStr = ((testTitle || "TEST").trim() || "TEST").slice(0, 80);
      while (titleStr.length > 1 && ctx.measureText(titleStr).width > halfPx - padX) {
        titleStr = titleStr.slice(0, -1);
      }
      if (!titleStr.trim()) titleStr = "TEST";
      let schn = (schoolName || "").trim().slice(0, 80);
      while (schn.length > 0 && ctx.measureText(schn).width > halfPx - padX) {
        schn = schn.slice(0, -1);
      }
      const twT = ctx.measureText(titleStr).width;
      const twS = schn ? ctx.measureText(schn).width : 0;
      const midY = innerBoxYCanvas + innerHPx / 2;
      const asc = 7.2 * scale;
      const des = 2.2 * scale;
      const bandH = asc + des + 2 * padV;
      const yWhiteTop = midY - bandH / 2;

      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x0 + padX - padW, yWhiteTop, twT + 2 * padW, bandH);
      if (schn) {
        ctx.fillRect(x0 + wPx - padX - twS - padW, yWhiteTop, twS + 2 * padW, bandH);
      }

      ctx.fillStyle = "#262626";
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.fillText(titleStr, x0 + padX, midY);
      if (schn) {
        ctx.textAlign = "right";
        ctx.fillText(schn, x0 + wPx - padX, midY);
      }
      ctx.textAlign = "left";
    }

    // Sütun çizgileri - üst banner alt çizgisinden footer üst çizgisine kadar (2–6 sütun) - cevap anahtarı sayfasında değil
    if (columns > 1 && !isAnswerKeyOnlyPage) {
      const colGapPt = mmToPt(columnGapMm);
      const colWPt = (contentW - (columns - 1) * colGapPt) / columns;
      const linePositionsPx = Array.from({ length: columns - 1 }, (_, i) =>
        (mlPt + (i + 1) * colWPt + (i + 0.5) * colGapPt) * scale
      );
      let headerH: number;
      if (currentPage === 1 && writtenPaperHeader && (writtenPaperTitle || "").trim()) {
        const titleMax = Math.max(100, contentW - 8);
        headerH = approxWrittenRuleDownFromInnerTopPt(
          writtenPaperFieldLines,
          writtenPaperTitle,
          titleMax,
          writtenPaperFieldHidden
        );
      } else if (currentPage === 1 && includeDescription) {
        const colCount = Math.max(1, Math.min(3, descriptionColumnCount || 1));
        const textsIn = (descriptionTexts ?? []).slice(0, colCount);
        const maxLines = Math.max(
          1,
          ...textsIn.map((h) => descriptionHtmlToLines(h ?? "").length)
        );
        const boxHpt = descriptionBoxHeightPt(maxLines);
        headerH = 22 + 2 + boxHpt;
      } else if (writtenPaperHeader && currentPage > 1) {
        headerH = 2;
      } else {
        headerH = 22;
      }
      const yStart = (mtPt + headerH) * scale;
      const yEnd = (pageHpt - footerTopPt) * scale;
      ctx.strokeStyle = writtenPaperHeader ? writtenStrokeRgb : themeRgb;
      ctx.lineWidth = writtenRuleLw;
      linePositionsPx.forEach((lineX) => {
        ctx.beginPath();
        ctx.moveTo(lineX, yStart);
        ctx.lineTo(lineX, yEnd);
        ctx.stroke();
      });
    }

    // Soruları çiz (veya cevap anahtarı sayfasındaysak atla)
    const pageItems = layout.filter((l) => l.page_num === currentPage);

    pageItems.forEach((item) => {
      const hasImg =
        item.img_x_pt != null &&
        item.img_y_top_pt != null &&
        item.img_w_pt != null &&
        item.img_h_pt != null;
      if (!hasImg) return;

      const imgX = item.img_x_pt!;
      const imgY = item.img_y_top_pt!;
      const imgW = item.img_w_pt!;
      const imgH = item.img_h_pt!;
      const numX = item.x_pt;
      const sec = item.section;

      if (sec) {
        const secBoxH = (sec.box_h ?? 22) * scale;
        const secYTopPt = item.y_top_pt;
        const { x: secX, y: secY } = ptToCanvas(numX, secYTopPt);
        const secWpx = (item.w_pt ?? 250) * scale;
        ctx.fillStyle = sec.fill_color || "#FFFFFF";
        ctx.strokeStyle = sec.line_color || "#000000";
        ctx.lineWidth = 0.8 * scale;
        ctx.beginPath();
        const r = 6 * scale;
        ctx.moveTo(secX + r, secY);
        ctx.lineTo(secX + secWpx - r, secY);
        ctx.quadraticCurveTo(secX + secWpx, secY, secX + secWpx, secY + r);
        ctx.lineTo(secX + secWpx, secY + secBoxH - r);
        ctx.quadraticCurveTo(secX + secWpx, secY + secBoxH, secX + secWpx - r, secY + secBoxH);
        ctx.lineTo(secX + r, secY + secBoxH);
        ctx.quadraticCurveTo(secX, secY + secBoxH, secX, secY + secBoxH - r);
        ctx.lineTo(secX, secY + r);
        ctx.quadraticCurveTo(secX, secY, secX + r, secY);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = sec.text_color || "#000000";
        ctx.font = `bold ${(sec.font_pt ?? 12) * scale}px Arial, Helvetica`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(
          (sec.title || "Bölüm").slice(0, 40),
          secX + secWpx / 2,
          secY + secBoxH / 2
        );
      }

      const ec = item.explanation_caption;
      if (ec) {
        const ascentApprox = ec.font_pt * 0.72;
        const hex = ec.color_hex || "#0f172a";
        const [cr, cg, cb] = hexToRgb(hex);
        const fontStack =
          'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
        const fw = `${ec.bold ? "bold " : ""}${ec.italic ? "italic " : ""}`;
        ctx.font = `${fw}${ec.font_pt * scale}px ${fontStack}`;
        const sl = (ec.single_line || "").trim();
        const rd = ec.rotate_deg ?? 0;
        if (sl && rd !== 0 && ec.pivot_x_pt != null && ec.pivot_y_pt != null) {
          const { x: px, y: py } = ptToCanvas(ec.pivot_x_pt, ec.pivot_y_pt);
          ctx.save();
          ctx.translate(px, py);
          ctx.rotate((-rd * Math.PI) / 180);
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillStyle = `rgb(${Math.round(cr * 255)},${Math.round(cg * 255)},${Math.round(cb * 255)})`;
          ctx.fillText(sl, 0, 0);
          ctx.restore();
        } else if (ec.lines && ec.lines.length > 0) {
          const boxHpx = ec.h_pt * scale;
          const bgXpt = ec.box_bg_x_pt ?? ec.x_pt;
          const bgWpt = ec.box_bg_w_pt ?? ec.w_pt;
          const bgWpx = bgWpt * scale;
          if (ec.box_enabled && ec.box_fill_hex) {
            const [br, bgc, bb] = hexToRgb(ec.box_fill_hex);
            ctx.fillStyle = `rgb(${Math.round(br * 255)},${Math.round(bgc * 255)},${Math.round(bb * 255)})`;
            const { x: rx, y: ryTop } = ptToCanvas(bgXpt, ec.y_top_pt);
            const rnd = ec.box_rounded !== false;
            const rad = rnd ? Math.min(10, boxHpx * 0.18, bgWpx * 0.06) : 0;
            ctx.beginPath();
            if (rnd && rad > 0 && typeof ctx.roundRect === "function") {
              ctx.roundRect(rx, ryTop, bgWpx, boxHpx, rad);
            } else {
              ctx.rect(rx, ryTop, bgWpx, boxHpx);
            }
            ctx.fill();
          }
          ctx.fillStyle = `rgb(${Math.round(cr * 255)},${Math.round(cg * 255)},${Math.round(cb * 255)})`;
          const n = ec.lines.length;
          const descentApprox = ec.font_pt * 0.22;
          const textHPt = (n - 1) * ec.leading_pt + ascentApprox + descentApprox;
          const excessPt = Math.max(0, ec.h_pt - textHPt);
          const yBaselinePdf = ec.y_top_pt - excessPt / 2 - ascentApprox;
          const boxWpx = ec.w_pt * scale;
          ec.lines.forEach((line, i) => {
            const baselinePdf = yBaselinePdf - i * ec.leading_pt;
            ctx.textBaseline = "alphabetic";
            if (ec.box_enabled) {
              const cxPdf = bgXpt + bgWpt / 2;
              const { x: cx, y: cy } = ptToCanvas(cxPdf, baselinePdf);
              ctx.textAlign = "center";
              ctx.fillText(line || " ", cx, cy);
            } else {
              const { x: lx, y: ly } = ptToCanvas(ec.x_pt, baselinePdf);
              let tx = lx;
              if (ec.align === "center") {
                ctx.textAlign = "center";
                tx = lx + boxWpx / 2;
              } else if (ec.align === "right") {
                ctx.textAlign = "right";
                tx = lx + boxWpx;
              } else {
                ctx.textAlign = "left";
              }
              ctx.fillText(line || " ", tx, ly);
            }
          });
          ctx.textAlign = "left";
        }
      }

      const { x: cx, y: cy } = ptToCanvas(imgX, imgY);
      const imgWpx = imgW * scale;
      const imgHpx = imgH * scale;

      const imgEl = images.get(item.order_index);
      if (imgEl && imgEl.complete) {
        ctx.drawImage(imgEl, cx, cy, imgWpx, imgHpx);
      } else {
        ctx.fillStyle = "#f0f0f0";
        ctx.fillRect(cx, cy, imgWpx, imgHpx);
      }

      const dn = item.display_number;
      const slotPx = (item.num_slot_w_pt ?? 20) * scale;
      if (dn != null) {
        const numLabel = `${dn}.`;
        ctx.fillStyle = "#000000";
        ctx.font = `bold ${10 * scale}px Helvetica, Arial`;
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        const numTwPx = ctx.measureText(numLabel).width;
        const numLeftPx = numX * scale + Math.max(0, slotPx - numTwPx);
        ctx.fillText(numLabel, numLeftPx, cy);
      }

      if (item.order_index === selectedQuestion) {
        ctx.strokeStyle = "#3b82f6";
        ctx.lineWidth = 2;
        ctx.strokeRect(cx - 2, cy - 2, imgWpx + 4, imgHpx + 4);
      }
    });

    // Sorular arası ve sayfa altı boşluk göstergesi: ortada, uçları oklu çizgi + mm değeri
    const midX = pageWpt / 2;
    const arrowSize = 5 * scale;
    const drawGapLine = (
      lineXpt: number,
      yTopPt: number,
      yBottomPt: number,
      label: string
    ) => {
      const gapPt = yTopPt - yBottomPt;
      if (gapPt <= 0) return;
      const gapMm = Math.round(gapPt * PT_TO_MM * 10) / 10;
      const lineXpx = lineXpt * scale;
      const { y: yCurrBottom } = ptToCanvas(lineXpt, yBottomPt);
      const { y: yNextTop } = ptToCanvas(lineXpt, yTopPt);
      ctx.strokeStyle = "#22c55e";
      ctx.fillStyle = "#22c55e";
      ctx.lineWidth = 1.2 * scale;
      ctx.beginPath();
      ctx.moveTo(lineXpx, yCurrBottom);
      ctx.lineTo(lineXpx, yNextTop);
      ctx.stroke();
      const drawArrow = (tipX: number, tipY: number, pointingUp: boolean) => {
        const dx = arrowSize * 0.6;
        const dy = arrowSize * (pointingUp ? 1 : -1);
        ctx.beginPath();
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX - dx, tipY + dy);
        ctx.lineTo(tipX + dx, tipY + dy);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      };
      drawArrow(lineXpx, yCurrBottom, false);
      drawArrow(lineXpx, yNextTop, true);
      ctx.fillStyle = "#15803d";
      ctx.font = `bold ${9 * scale}px Helvetica, Arial`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      const txtY = (yCurrBottom + yNextTop) / 2;
      ctx.fillText(`${gapMm} mm`, lineXpx + arrowSize + 4, txtY);
    };

    pageItems.forEach((item) => {
      const hasImg =
        item.img_x_pt != null &&
        item.img_y_top_pt != null &&
        item.img_w_pt != null &&
        item.img_h_pt != null;
      if (!hasImg) return;
      const colCenter = (item.x_pt ?? 0) + (item.w_pt ?? 0) / 2;
      const currBottomPt = (item.img_y_top_pt ?? 0) - (item.img_h_pt ?? 0);
      const isLeft = (item.img_x_pt ?? 0) < midX;
      const below = pageItems.filter(
        (l) =>
          l.img_x_pt != null &&
          l.img_y_top_pt != null &&
          (l.img_x_pt ?? 0) < midX === isLeft &&
          (l.img_y_top_pt ?? 0) < (item.img_y_top_pt ?? 0)
      );
      const next = below.sort((a, b) => (b.img_y_top_pt ?? 0) - (a.img_y_top_pt ?? 0))[0];
      const yBottomPt = next?.img_y_top_pt ?? footerTopPt;
      const gapPt = currBottomPt - yBottomPt;
      if (gapPt > 0) {
        if (next?.img_y_top_pt != null) {
          drawGapLine(colCenter, currBottomPt, next.img_y_top_pt, "gap");
        } else {
          drawGapLine(colCenter, currBottomPt, footerTopPt, "footer");
        }
      }
    });

    // Yazılı: son sayfa — tam genişlikte Hazırlayan Öğretmenler (yan yana satır kırarak) + sağ altta Okul Müdürü
    if (
      !isAnswerKeyOnlyPage &&
      writtenPaperHeader &&
      writtenPaperShowTeachers &&
      pageItems.length > 0 &&
      currentPage === maxQuestionPage
    ) {
      const nameUpper = (s: string) => s.trim().toUpperCase();
      const teacherNamesOnly = writtenPaperTeachers
        .map((t) => nameUpper(t?.name ?? ""))
        .filter(Boolean);
      const principalU = nameUpper(writtenPaperPrincipalName ?? "");
      if (teacherNamesOnly.length > 0 || principalU) {
        const yCv = (py: number) => (pageHpt - py) * scale;
        const contentWPt = pageWpt - mlPt - mrPt;
        const gapXPt = 9;
        const minCellPt = 68;
        const maxCellPt = 132;
        const nameFsPt = 8;
        const titleFsPt = 10;
        const labelFsPt = 7;
        const roleFsPt = 9;
        const rowGapPt = 10;

        const packRows = (names: string[]): { name: string; w: number }[][] => {
          const rows: { name: string; w: number }[][] = [];
          if (names.length === 0) return rows;
          ctx.font = `bold ${nameFsPt * scale}px Helvetica, Arial`;
          let row: { name: string; w: number }[] = [];
          let rowW = 0;
          for (const nm of names) {
            const tw = ctx.measureText(nm).width / scale;
            const cellW = Math.min(maxCellPt, Math.max(minCellPt, tw + 14));
            const need = row.length === 0 ? cellW : gapXPt + cellW;
            if (row.length > 0 && rowW + need > contentWPt + 0.5) {
              rows.push(row);
              row = [];
              rowW = 0;
            }
            row.push({ name: nm, w: cellW });
            rowW += need;
          }
          if (row.length) rows.push(row);
          return rows;
        };

        const rows = packRows(teacherNamesOnly);
        const cellBlockPt = nameFsPt + 5 + labelFsPt + 14 + 6;
        const gapMidPt = rows.length > 0 && principalU ? 16 : 0;

        const bottoms = pageItems
          .filter(
            (it) =>
              it.img_y_top_pt != null &&
              it.img_h_pt != null &&
              (it.content_type ?? "question") === "question"
          )
          .map((it) => (it.img_y_top_pt ?? 0) - (it.img_h_pt ?? 0));
        const contentBottomPt = bottoms.length > 0 ? Math.min(...bottoms) : footerTopPt + 80;
        const yBandTopPt = contentBottomPt - 10;
        let yPdf = yBandTopPt - 8;

        ctx.fillStyle = "#000000";
        ctx.textBaseline = "alphabetic";

        if (rows.length > 0) {
          ctx.font = `bold ${titleFsPt * scale}px Helvetica, Arial`;
          ctx.textAlign = "center";
          ctx.fillText(
            "HAZIRLAYAN ÖĞRETMENLER",
            ((mlPt + pageWpt - mrPt) / 2) * scale,
            yCv(yPdf)
          );
          const titleDesc = titleFsPt * 0.72;
          ctx.strokeStyle = writtenStrokeRgb;
          ctx.lineWidth = writtenRuleLw;
          ctx.beginPath();
          ctx.moveTo(mlPt * scale, yCv(yPdf - titleDesc - 3));
          ctx.lineTo((pageWpt - mrPt) * scale, yCv(yPdf - titleDesc - 3));
          ctx.stroke();
          yPdf = yPdf - titleDesc - 12;

          for (const row of rows) {
            const totalRw =
              row.reduce((s, c) => s + c.w, 0) + gapXPt * (row.length - 1);
            let xCurPt = mlPt + Math.max(0, (contentWPt - totalRw) / 2);
            for (const cell of row) {
              ctx.font = `bold ${nameFsPt * scale}px Helvetica, Arial`;
              ctx.textAlign = "left";
              const tw = ctx.measureText(cell.name).width / scale;
              ctx.fillText(
                cell.name.slice(0, 44),
                (xCurPt + (cell.w - tw) / 2) * scale,
                yCv(yPdf)
              );
              ctx.font = `${labelFsPt * scale}px Helvetica, Arial`;
              ctx.textAlign = "center";
              ctx.fillText("İmza", (xCurPt + cell.w / 2) * scale, yCv(yPdf - nameFsPt - 4));
              const sigY = yPdf - nameFsPt - 4 - labelFsPt - 5;
              ctx.strokeStyle = writtenStrokeRgb;
              ctx.lineWidth = writtenRuleLw;
              ctx.beginPath();
              ctx.moveTo((xCurPt + 3) * scale, yCv(sigY));
              ctx.lineTo((xCurPt + cell.w - 3) * scale, yCv(sigY));
              ctx.stroke();
              xCurPt += cell.w + gapXPt;
            }
            yPdf = yPdf - cellBlockPt - rowGapPt;
          }
        }

        if (principalU) {
          yPdf -= gapMidPt;
          const xRightPt = pageWpt - mrPt;
          const xLeftPrPt = xRightPt - prWPt;
          ctx.font = `bold ${roleFsPt * scale}px Helvetica, Arial`;
          ctx.textAlign = "right";
          ctx.fillText("OKUL MÜDÜRÜ", xRightPt * scale, yCv(yPdf));
          yPdf -= roleFsPt + 8;
          ctx.font = `bold ${nameFsPt * scale}px Helvetica, Arial`;
          ctx.fillText(principalU.slice(0, 48), xRightPt * scale, yCv(yPdf));
          yPdf -= nameFsPt + 6;
          ctx.font = `${labelFsPt * scale}px Helvetica, Arial`;
          ctx.fillText("İmza", xRightPt * scale, yCv(yPdf));
          const lineY = yPdf - labelFsPt - 4;
          ctx.strokeStyle = writtenStrokeRgb;
          ctx.lineWidth = writtenRuleLw;
          ctx.beginPath();
          ctx.moveTo(xLeftPrPt * scale, yCv(lineY));
          ctx.lineTo(xRightPt * scale, yCv(lineY));
          ctx.stroke();
        }
      }
    }

    // Çizgi üzerine yazı (test kağıdı; sütun ayırıcıların ortasında, sorulardan sonra — PDF ile aynı)
    if (
      columns > 1 &&
      !isAnswerKeyOnlyPage &&
      addTextOnLine &&
      (centerLineText || "").trim() &&
      !writtenPaperHeader
    ) {
      const colGapPt = mmToPt(columnGapMm);
      const colWPt = (contentW - (columns - 1) * colGapPt) / columns;
      const linePositionsPx = Array.from({ length: columns - 1 }, (_, i) =>
        (mlPt + (i + 1) * colWPt + (i + 0.5) * colGapPt) * scale
      );
      let headerHPt: number;
      if (currentPage === 1 && includeDescription) {
        const colCount = Math.max(1, Math.min(3, descriptionColumnCount || 1));
        const textsIn = (descriptionTexts ?? []).slice(0, colCount);
        const maxLines = Math.max(
          1,
          ...textsIn.map((h) => descriptionHtmlToLines(h ?? "").length)
        );
        const boxHpt = descriptionBoxHeightPt(maxLines);
        headerHPt = 22 + 2 + boxHpt;
      } else {
        headerHPt = 22;
      }
      const yStart = (mtPt + headerHPt) * scale;
      const yEnd = (pageHpt - footerTopPt) * scale;
      const cy = (yStart + yEnd) / 2;
      const txt = centerLineText.trim();
      const fs = 9 * scale;
      const fontPrefix = [
        centerLineItalic ? "italic" : "",
        centerLineBold ? "bold" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const fontCss = fontPrefix ? `${fontPrefix} ${fs}px Arial, Helvetica` : `${fs}px Arial, Helvetica`;
      const rot =
        centerLineTextDirection === "down" ? Math.PI / 2 : -Math.PI / 2;
      linePositionsPx.forEach((lineX) => {
        ctx.save();
        ctx.font = fontCss;
        const tw = ctx.measureText(txt).width;
        const m = ctx.measureText(txt);
        const fontH =
          (m.actualBoundingBoxAscent ?? fs * 0.72) +
          (m.actualBoundingBoxDescent ?? fs * 0.22);
        ctx.translate(lineX, cy);
        ctx.rotate(rot);
        ctx.fillStyle = "#ffffff";
        const pad = 2 * scale;
        ctx.fillRect(-tw / 2 - pad, -fontH / 2 - pad, tw + 2 * pad, fontH + 2 * pad);
        ctx.fillStyle = themeRgb;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(txt, 0, 0);
        ctx.restore();
      });
    }

    // Footer - end_of_test: sadece testin son sayfasında (en son sorunun peşinde)
    // separate_page: cevap anahtarı sayfasında
    // Cevap anahtarı genişliği en fazla bir sorun genişliği kadar
    const maxAnswerKeyWidthPx = (layout[0]?.w_pt ?? (pageWpt - mlPt - mrPt) / columns) * scale;
    if (includeAnswerKey && (answerKeyMode === "end_of_test" || isAnswerKeyOnlyPage) && answerKeyItems.length > 0) {
      if (isAnswerKeyOnlyPage) {
        const entriesPerPage = 4 * 8;
        const pageIdx = currentPage - maxQuestionPage - 1;
        const startIdx = pageIdx * entriesPerPage;
        const chunk = answerKeyItems.slice(startIdx, startIdx + entriesPerPage);
        if (chunk.length > 0) {
          const contentTopPt = pageHpt - mtPt - 10;
          const tableYTopCanvas = (pageHpt - contentTopPt) * scale;
          const tableW = Math.min(pageWpx - ml - mr, maxAnswerKeyWidthPx);
          const tableX = ml + (pageWpx - ml - mr - tableW) / 2;
          drawAnswerKeyTable(tableX, tableYTopCanvas, tableW, chunk, 4, "Cevap Anahtarı");
        }
      } else if (answerKeyMode === "end_of_test" && currentPage === maxQuestionPage) {
        const contentW = pageWpt - mlPt - mrPt;
        const colGapPt = mmToPt(8);
        const colWPt = columns > 1
          ? (contentW - (columns - 1) * colGapPt) / columns
          : contentW;
        const rightColX = columns > 1
          ? mlPt + (columns - 1) * (colWPt + colGapPt)
          : mlPt;
        const layoutForTable = computeAnswerKeyLayout({
          items: answerKeyItems,
          totalWidthPx: maxAnswerKeyWidthPx,
          columnCount: 2,
          scale,
        });
        const tableBottomY = (pageHpt - footerTopPt) * scale - 8 * scale;
        const tableYTopCanvas = tableBottomY - layoutForTable.tableHeightPx;
        drawAnswerKeyTable(rightColX * scale, tableYTopCanvas, maxAnswerKeyWidthPx, answerKeyItems, 2, "Cevap Anahtarı");
      }
    }

    const footerTopPx = (pageHpt - footerTopPt) * scale;
    const footerBottomPx = (pageHpt - footerBottomPt) * scale;

    const showFooterAnswers = includeAnswerKey && answerKeyMode === "per_page" && pageItems.length > 0;
    const answersStr = showFooterAnswers
      ? pageItems
          .filter((i) => i.display_number != null)
          .sort((a, b) => (a.display_number as number) - (b.display_number as number))
          .map((i) => `${i.display_number}. ${i.answer_key || "?"}`)
          .join("  ")
          .slice(0, 120)
      : "";

    if (writtenPaperHeader) {
      ctx.strokeStyle = writtenStrokeRgb;
      ctx.lineWidth = writtenRuleLw;
      ctx.beginPath();
      ctx.moveTo(ml, footerTopPx);
      ctx.lineTo(pageWpx - mr, footerTopPx);
      ctx.stroke();
      if (showFooterAnswers) {
        ctx.fillStyle = writtenStrokeRgb;
        ctx.font = `${9 * scale}px Arial, Helvetica`;
        ctx.textAlign = "left";
        ctx.textBaseline = "bottom";
        ctx.fillText(answersStr, ml, footerTopPx - 3 * scale);
      }
    } else {
      const themeStroke = `rgb(${Math.round(theme[0] * 255)}, ${Math.round(theme[1] * 255)}, ${Math.round(theme[2] * 255)})`;
      ctx.strokeStyle = themeStroke;
      ctx.lineWidth = 0.4 * scale;
      ctx.beginPath();
      ctx.moveTo(ml, footerTopPx);
      ctx.lineTo(pageWpx - mr, footerTopPx);
      ctx.stroke();

      const yMid = (footerTopPx + footerBottomPx) / 2;
      const cx = (ml + pageWpx - mr) / 2;
      const bandPx = Math.abs(footerBottomPx - footerTopPx);
      const circleR = Math.min(11 * scale, Math.max(4 * scale, bandPx / 2 - 2 * scale));
      const leftLimit = cx - circleR - 10 * scale;

      if (showFooterAnswers) {
        ctx.font = `${9 * scale}px Arial, Helvetica`;
        ctx.fillStyle = themeStroke;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        let ans = answersStr;
        while (ans.length > 0 && ctx.measureText(ans).width > leftLimit - ml) {
          ans = ans.slice(0, -1);
        }
        if (ans.length < answersStr.length && ans.length > 0) ans = `${ans.slice(0, -1)}…`;
        if (ans) ctx.fillText(ans, ml, yMid);
      }

      ctx.beginPath();
      ctx.strokeStyle = themeStroke;
      ctx.lineWidth = 0.4 * scale;
      ctx.moveTo(ml, footerBottomPx);
      ctx.lineTo(pageWpx - mr, footerBottomPx);
      ctx.stroke();

      const pg = String(currentPage);
      const chord = circleR * 2 * 0.72;
      let fs = 10 * scale;
      const fitsInCircle = (size: number) => {
        ctx.font = `bold ${size}px Arial, Helvetica`;
        const m = ctx.measureText(pg);
        const w = m.width;
        const asc = m.actualBoundingBoxAscent ?? size * 0.72;
        const desc = m.actualBoundingBoxDescent ?? size * 0.22;
        const h = asc + desc;
        return w <= chord && h <= chord;
      };
      while (fs >= 5 * scale && !fitsInCircle(fs)) fs -= 0.5 * scale;

      ctx.beginPath();
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = themeStroke;
      ctx.lineWidth = 0.8 * scale;
      ctx.arc(cx, yMid, circleR, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = themeStroke;
      ctx.font = `bold ${fs}px Arial, Helvetica`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(pg, cx, yMid);

      if (
        lastQuestionPage != null &&
        lastQuestionPage >= 1 &&
        Number.isFinite(lastQuestionPage)
      ) {
        const fsNav = Math.max(5 * scale, 8 * scale);
        const rx = pageWpx - mr;
        ctx.fillStyle = "#000000";
        ctx.font = `bold ${fsNav}px Arial, Helvetica`;
        ctx.textAlign = "right";
        if (currentPage < lastQuestionPage) {
          ctx.textBaseline = "middle";
          ctx.fillText("Diğer sayfaya geçiniz.", rx, yMid);
        } else if (currentPage === lastQuestionPage) {
          ctx.textBaseline = "bottom";
          ctx.fillText("TEST BİTTİ.", rx, yMid - fsNav * 0.1);
          ctx.textBaseline = "top";
          ctx.fillText("CEVAPLARINIZI KONTROL EDİNİZ.", rx, yMid + fsNav * 0.1);
        }
      }
    }

    // Filigran - tüm içeriğin üstünde
    if (watermarkEnabled && watermarkSettings) {
      const w = watermarkSettings;
      if (w.mode === "text" && w.text.trim()) {
        const alpha = Math.max(0.05, Math.min(1, w.textOpacityPct / 100));
        const sizeFactor = Math.max(0.1, Math.min(2.5, w.textSizePct / 100));
        const base = Math.min(pageWpx, pageHpx) * 0.12;
        const fontSz = Math.max(10, base * sizeFactor);
        const ang = -(w.textAngleDeg * Math.PI) / 180;  // Saat yönünün tersi (CCW)
        const col = themeColor || "#1E88E5";  // Her zaman tema rengi
        const r = parseInt(col.slice(1, 3), 16) / 255;
        const g = parseInt(col.slice(3, 5), 16) / 255;
        const b = parseInt(col.slice(5, 7), 16) / 255;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.translate(pageWpx / 2, pageHpx / 2);
        ctx.rotate(ang);
        ctx.fillStyle = `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
        ctx.font = `bold ${fontSz}px Helvetica, Arial`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(w.text.trim().slice(0, 80), 0, 0);
        ctx.restore();
      } else if (w.mode === "image" && watermarkImage?.complete) {
        const alpha = Math.max(0.05, Math.min(1, w.imageOpacityPct / 100));
        const sizeFactor = Math.max(0.05, Math.min(2, w.imageSizePct / 100));
        const targetW = pageWpx * 0.7 * sizeFactor;
        const targetH = (watermarkImage.height / watermarkImage.width) * targetW;
        const x = (pageWpx - targetW) / 2;
        const y = (pageHpx - targetH) / 2;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.drawImage(watermarkImage, x, y, targetW, targetH);
        ctx.restore();
      }
    }
    } catch (err) {
      console.error("CanvasPdfPreview draw error:", err);
    }
  }, [
    layout,
    currentPage,
    scale,
    pageWpt,
    pageHpt,
    pageWpx,
    pageHpx,
    marginTopMm,
    marginBottomMm,
    marginLeftMm,
    marginRightMm,
    columnGapMm,
    themeColor,
    testTitle,
    schoolName,
    includeAnswerKey,
    answerKeyMode,
    columns,
    addTextOnLine,
    centerLineText,
    centerLineBold,
    centerLineItalic,
    centerLineTextDirection,
    includeDescription,
    descriptionColumnCount,
    descriptionTexts,
    descriptionColumnDividers,
    images,
    selectedQuestion,
    ptToCanvas,
    watermarkEnabled,
    watermarkSettings,
    watermarkImage,
    writtenPaperHeader,
    writtenPaperTitle,
    writtenPaperFieldLines,
    writtenFieldLabelsSig,
    writtenPaperFieldHidden,
    writtenPaperBookletLetter,
    writtenPaperShowTeachers,
    writtenPaperTeachers,
    writtenPaperPrincipalName,
    lastQuestionPage,
  ]);

  useEffect(() => {
    draw();
  }, [draw]);

  // Canvas boyutları
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = pageWpx * dpr;
    canvas.height = pageHpx * dpr;
    canvas.style.width = `${pageWpx}px`;
    canvas.style.height = `${pageHpx}px`;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.scale(dpr, dpr);
    draw();
  }, [pageWpx, pageHpx, draw]);

  // Tıklama ile soru seçimi
  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const relX = e.clientX - rect.left;
    const relY = e.clientY - rect.top;

    const pageItems = layout.filter((l) => l.page_num === currentPage);
    for (let i = pageItems.length - 1; i >= 0; i--) {
      const item = pageItems[i];
      const hasImg =
        item.img_x_pt != null &&
        item.img_y_top_pt != null &&
        item.img_w_pt != null &&
        item.img_h_pt != null;
      if (!hasImg) continue;

      const { x, y } = ptToCanvas(item.img_x_pt!, item.img_y_top_pt!);
      const w = item.img_w_pt! * scale;
      const h = item.img_h_pt! * scale;

      if (relX >= x && relX <= x + w && relY >= y && relY <= y + h) {
        onQuestionSelect(item.order_index);
        return;
      }
    }
  };

  return (
    <div ref={containerRef} className="relative inline-block">
      <canvas
        ref={canvasRef}
        className={`block rounded-lg border border-slate-200 bg-white shadow-lg ${interactive ? "cursor-pointer" : ""}`}
        style={interactive ? {} : { pointerEvents: "none" }}
        onClick={interactive ? handleClick : undefined}
      />
    </div>
  );
}
