import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import ReactCrop, { type Crop, type PixelCrop } from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import type { CropBox, PdfItem } from "../../types";
import type { AnswerOption } from "../../types";
import { api } from "../../api/client";
import { useEditorStore } from "../../store/editorStore";
import {
  percentCropToNormalizedRect,
  trimCropToContent,
  normalizedRectToPercentCrop,
} from "../../utils/cropCoordUtils";
import InlineAnswerBar from "./InlineAnswerBar";
import PdfDeleteModal from "../modals/PdfDeleteModal";
import SelectionOverlay from "./SelectionOverlay";
import SortableSelectionItem from "./SortableSelectionItem";

type PendingSelection = {
  id: string;
  pdf_id: string;
  page_number: number;
  crop: CropBox; // norm 0..1
  answer_key?: string;
  number: number;
  /** Backend'de zaten kayıtlı mı (yüklemeden gelen) */
  backendId?: string;
};

export default function CropWorkspace() {
  const navigate = useNavigate();
  const location = useLocation();
  const questions = useEditorStore((s) => s.questions);
  const fetchQuestions = useEditorStore((s) => s.fetchQuestions);
  const addQuestion = useEditorStore((s) => s.addQuestion);

  const [pdfs, setPdfs] = useState<PdfItem[]>([]);
  const [selectedPdf, setSelectedPdf] = useState<PdfItem | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  /** Her PDF için son görüntülenen sayfa (PDF’ler arası geçişte hatırlamak için) */
  const pdfPageIndicesRef = useRef<Record<string, number>>({});
  const [zoom, setZoom] = useState(100); // Display zoom % (10–400)
  /** Fixed DPI for page image - never tied to zoom (desktop parity). */
  const FIXED_DPI = 150;
  const [pendingSelections, setPendingSelections] = useState<PendingSelection[]>([]);
  const [showSelectionsPanel, setShowSelectionsPanel] = useState(false);

  const [crop, setCrop] = useState<Crop>();
  const [completedCrop, setCompletedCrop] = useState<PixelCrop | null>(null);
  const [editingSelectionId, setEditingSelectionId] = useState<string | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inlineSelectedAnswer, setInlineSelectedAnswer] = useState<AnswerOption | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const imgRef = useRef<HTMLImageElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const lastFittedPageRef = useRef<string | null>(null);
  const [viewerSize, setViewerSize] = useState<{ w: number; h: number } | null>(null);
  const pendingAddPercentCropRef = useRef<{ x: number; y: number; width: number; height: number } | null>(null);

  // Viewer boyutunu ölç (ilk açılışta fit için)
  useEffect(() => {
    const el = viewerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (viewerRef.current)
        setViewerSize({ w: viewerRef.current.clientWidth, h: viewerRef.current.clientHeight });
    });
    ro.observe(el);
    setViewerSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [selectedPdf, showSelectionsPanel]);

  const fetchPdfs = useCallback(async () => {
    try {
      const { items } = await api.pdfs.list();
      setPdfs(items);
      setSelectedPdf((prev) => {
        if (!prev) return items[0] ?? null;
        const stillExists = items.some((p) => p.id === prev.id);
        return stillExists ? prev : items[0] ?? null;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "PDF listesi alınamadı");
    }
  }, []);

  const locationState = location.state as { pdfId?: string; pageNumber?: number } | null;

  useEffect(() => {
    fetchPdfs();
  }, [fetchPdfs]);

  // Mevcut soruları yükle, numaraları sıfırlamadan devam et
  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  // Soruları yükle, sıfırlamadan mevcut listeyle birleştir
  useEffect(() => {
    if (pdfs.length === 0) return;
    const loaded: PendingSelection[] = [...questions]
      .sort((a, b) => a.order_index - b.order_index)
      .map((q) => ({
        id: q.id,
        pdf_id: q.pdf_id,
        page_number: q.page_number,
        crop: q.crop,
        answer_key: q.answer_key ?? "",
        number: q.order_index + 1,
        backendId: q.id,
      }));
    setPendingSelections((prev) => {
      const prevNew = prev.filter((p) => !p.backendId);
      if (loaded.length === 0 && prevNew.length === 0) return prev;
      const loadedIds = new Set(loaded.map((l) => l.id));
      const merged = [
        ...loaded,
        ...prevNew.filter((p) => !loadedIds.has(p.id)),
      ].sort((a, b) => a.number - b.number);
      return merged;
    });
  }, [questions, pdfs.length]);

  useEffect(() => {
    if (locationState?.pdfId && pdfs.length > 0) {
      const pdf = pdfs.find((p) => p.id === locationState.pdfId);
      if (pdf) {
        const page = locationState.pageNumber ?? 1;
        setSelectedPdf(pdf);
        setCurrentPage(page);
        pdfPageIndicesRef.current[pdf.id] = page;
      }
    }
  }, [locationState?.pdfId, locationState?.pageNumber, pdfs]);

  // Sayfa değiştiğinde bu PDF için son sayfayı kaydet
  useEffect(() => {
    if (selectedPdf && currentPage >= 1) {
      pdfPageIndicesRef.current[selectedPdf.id] = currentPage;
    }
  }, [selectedPdf?.id, currentPage]);

  // Crop sayfasındayken tarayıcı zoom'unu engelle (sadece PDF zoom olsun)
  useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    const original = meta?.getAttribute("content") ?? "";
    if (meta) {
      meta.setAttribute("content", "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no");
    }
    return () => {
      if (meta) meta.setAttribute("content", original);
    };
  }, []);

  useEffect(() => {
    if (selectedPdf && currentPage > selectedPdf.page_count) {
      setCurrentPage(selectedPdf.page_count || 1);
    }
  }, [selectedPdf, currentPage]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    try {
      const { items: created } = await api.pdfs.upload(Array.from(files));
      await fetchPdfs();
      if (created.length > 0) setSelectedPdf(created[0]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Yükleme başarısız");
    }
  };

  const renumberSelections = useCallback((list: PendingSelection[]) => {
    return list.map((s, i) => ({ ...s, number: i + 1 }));
  }, []);

  const handlePdfDeleted = useCallback(
    (deletedId: string) => {
      setPendingSelections((prev) =>
        renumberSelections(prev.filter((s) => s.pdf_id !== deletedId))
      );
      if (selectedPdf?.id === deletedId) {
        setCurrentPage(1);
        setCrop(undefined);
        setCompletedCrop(null);
      }
      fetchPdfs();
    },
    [selectedPdf?.id, fetchPdfs, renumberSelections]
  );

  const onImageLoad = useCallback(() => {
    setImgLoaded(true);
    if (imgRef.current) {
      setImgSize({ w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight });
    }
  }, []);

  const handleAnswerPicked = (answer: AnswerOption | null) => {
    if (!selectedPdf) return;
    const percentCrop = pendingAddPercentCropRef.current;
    if (!percentCrop || percentCrop.width <= 0 || percentCrop.height <= 0) return;

    // Hemen temizle: çift tetiklenmede tekrar eklenmesin
    pendingAddPercentCropRef.current = null;
    setCompletedCrop(null);
    setCrop(undefined);
    setInlineSelectedAnswer(null);

    let box = percentCropToNormalizedRect(percentCrop);
    if (imgRef.current) {
      try {
        const trimmed = trimCropToContent(imgRef.current, percentCrop);
        if (trimmed) box = trimmed;
      } catch {
        /* CORS/tainted canvas: orijinal kutu kullan */
      }
    }

    setPendingSelections((prev) => {
      const nextNum = prev.length > 0 ? Math.max(...prev.map((s) => s.number)) + 1 : 1;
      const newSel: PendingSelection = {
        id: crypto.randomUUID(),
        pdf_id: selectedPdf.id,
        page_number: currentPage,
        crop: box,
        answer_key: answer ?? "",
        number: nextNum,
      };
      return [...prev, newSel].sort((a, b) => a.number - b.number);
    });
  };

  const handleAnswerChange = (sel: PendingSelection, answer: AnswerOption | null) => {
    setPendingSelections((prev) =>
      prev.map((s) => (s.id === sel.id ? { ...s, answer_key: answer ?? "" } : s))
    );
  };

  const handleDeleteSelection = (sel: PendingSelection) => {
    if (editingSelectionId === sel.id) setEditingSelectionId(null);
    setPendingSelections((prev) => renumberSelections(prev.filter((s) => s.id !== sel.id)));
  };

  const handleStartEditSelection = (sel: PendingSelection) => {
    if (editingSelectionId === sel.id) {
      setEditingSelectionId(null);
      setCrop(undefined);
    } else {
      setEditingSelectionId(sel.id);
      const norm = sel.crop as { x: number; y: number; width: number; height: number };
      setCrop({
        ...normalizedRectToPercentCrop(norm),
        unit: "%",
      });
    }
  };

  const handleEndEditSelection = () => {
    setEditingSelectionId(null);
    setCrop(undefined);
  };


  const handleSaveAll = async () => {
    const toSave = pendingSelections.filter((s) => !s.backendId);
    const hasExisting = pendingSelections.some((s) => s.backendId);
    if (pendingSelections.length === 0) {
      navigate("/");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const ordered = [...pendingSelections].sort((a, b) => a.number - b.number);
      const createdIds: string[] = [];

      for (const sel of ordered) {
        if (!sel.backendId) {
          const created = await api.questions.create({
            pdf_id: sel.pdf_id,
            page_number: sel.page_number,
            crop: sel.crop,
            answer_key: sel.answer_key,
          });
          addQuestion(created);
          createdIds.push(created.id);
        }
      }

      const orderedIds: string[] = [];
      let createdIndex = 0;
      for (const sel of ordered) {
        if (sel.backendId) orderedIds.push(sel.backendId);
        else orderedIds.push(createdIds[createdIndex++]);
      }

      if (orderedIds.length > 0) {
        await api.questions.reorder(orderedIds);
        await fetchQuestions();
      }
      setPendingSelections((prev) => prev.filter((s) => s.backendId));
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Seçimler kaydedilemedi");
    } finally {
      setSaving(false);
    }
  };

  const removePending = async (sel: PendingSelection) => {
    if (sel.backendId) {
      try {
        await api.questions.delete(sel.backendId);
        await fetchQuestions();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Soru silinemedi");
      }
    }
    setPendingSelections((prev) => renumberSelections(prev.filter((s) => s.id !== sel.id)));
  };

  const pageCount = selectedPdf?.page_count ?? 0;
  /** Fixed DPI - zoom is display-only (CSS transform). */
  const pageUrl = selectedPdf
    ? api.pdfs.pageImageUrl(selectedPdf.id, currentPage, { dpi: FIXED_DPI })
    : null;

  // ReactCrop onComplete -> percentCrop zoom'dan bağımsız, PixelCrop görüntüleme için (yeni seçim için)
  const handleCropComplete = useCallback(
    (pixelCrop: PixelCrop, percentCrop: { x: number; y: number; width: number; height: number }) => {
      if (editingSelectionId) return; // Düzenleme modundaysa yeni seçim olarak işleme
      setCompletedCrop(pixelCrop);
      pendingAddPercentCropRef.current = percentCrop;
      setInlineSelectedAnswer(null);
    },
    [editingSelectionId]
  );

  // URL değiştiğinde crop state ve yükleme durumunu sıfırla
  useEffect(() => {
    lastFittedPageRef.current = null;
    setEditingSelectionId(null);
    setImgLoaded(false);
    setImgSize(null);
    setCrop(undefined);
    setCompletedCrop(null);
    pendingAddPercentCropRef.current = null;
  }, [pageUrl]);

  const ZOOM_MIN = 10;
  const ZOOM_MAX = 400;
  const ZOOM_STEP = 10;

  // PDF genişliği ekrana sığacağı max zoom (taşınca zoom yapma, slider sabit kalsın)
  const effectiveMaxZoom =
    imgSize && viewerSize
      ? Math.min(
          ZOOM_MAX,
          Math.round((Math.max(1, viewerSize.w - 48) / imgSize.w) * 100)
        )
      : ZOOM_MAX;

  // Sadece yeni sayfa yüklendiğinde PDF genişliği sayfaya sığacak zoom (sonradan zoom out yapıldıysa değiştirme)
  useEffect(() => {
    if (!pageUrl || !imgSize || !viewerSize) return;
    if (lastFittedPageRef.current === pageUrl) return;
    lastFittedPageRef.current = pageUrl;
    const pad = 48; // p-6 * 2
    const availW = Math.max(1, viewerSize.w - pad);
    const scaleW = availW / imgSize.w;
    const fitZoom = Math.round(
      Math.max(ZOOM_MIN, Math.min(effectiveMaxZoom, scaleW * 100))
    );
    setZoom(fitZoom);
  }, [pageUrl, imgSize, viewerSize, effectiveMaxZoom]);

  // effectiveMaxZoom azalırsa (örn. pencere küçülür) zoom'u sınırla
  useEffect(() => {
    setZoom((z) => Math.min(z, effectiveMaxZoom));
  }, [effectiveMaxZoom]);

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(effectiveMaxZoom, z + ZOOM_STEP));
  }, [effectiveMaxZoom]);
  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP));
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!selectedPdf) return;
      const isZoomIn = (e.ctrlKey || e.metaKey) && (e.key === "=" || e.key === "+" || e.key === "Add");
      const isZoomOut = (e.ctrlKey || e.metaKey) && (e.key === "-" || e.key === "Subtract");
      if (isZoomIn) {
        e.preventDefault();
        e.stopPropagation();
        zoomIn();
      } else if (isZoomOut) {
        e.preventDefault();
        e.stopPropagation();
        zoomOut();
      }
    };
    const onWheel = (e: WheelEvent) => {
      if (!selectedPdf || !(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      e.stopPropagation();
      if (e.deltaY < 0) zoomIn();
      else if (e.deltaY > 0) zoomOut();
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    window.addEventListener("wheel", onWheel, { capture: true, passive: false });
    return () => {
      window.removeEventListener("keydown", onKeyDown, { capture: true });
      window.removeEventListener("wheel", onWheel, { capture: true });
    };
  }, [selectedPdf, zoomIn, zoomOut]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col overflow-hidden bg-slate-900" tabIndex={0}>
      {/* Top toolbar */}
      <div className="flex h-14 shrink-0 items-center gap-4 border-b border-slate-700 bg-slate-800 px-4">
        <select
          value={selectedPdf?.id ?? ""}
          onChange={(e) => {
            const prevId = selectedPdf?.id;
            if (prevId && selectedPdf) {
              pdfPageIndicesRef.current[prevId] = currentPage;
            }
            const p = pdfs.find((f) => f.id === e.target.value);
            setSelectedPdf(p ?? null);
            setCurrentPage(p ? (pdfPageIndicesRef.current[p.id] ?? 1) : 1);
          }}
          className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-white"
        >
          <option value="">PDF seçin</option>
          {pdfs.map((pdf) => (
            <option key={pdf.id} value={pdf.id}>
              {pdf.filename}
            </option>
          ))}
        </select>

        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          onChange={handleUpload}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
        >
          PDF Ekle
        </button>

        <button
          type="button"
          onClick={() => setShowDeleteModal(true)}
          className="rounded-lg border border-rose-600 bg-rose-600/20 px-4 py-2 text-sm font-medium text-rose-400 hover:bg-rose-600/40"
          title="PDF sil"
        >
          PDF Sil
        </button>

        <button
          type="button"
          onClick={() => setShowSelectionsPanel((v) => !v)}
          className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm text-white hover:bg-slate-600"
        >
          Soruları Listele {pendingSelections.length > 0 && `(${pendingSelections.length})`}
        </button>
        {selectedPdf && (
          <span className="text-xs text-slate-400">
            Toplam Soru: {pendingSelections.length}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate("/")}
            className="rounded-lg bg-slate-600 px-4 py-2 text-sm font-medium text-white hover:bg-slate-500"
          >
            Ana Editöre Dön
          </button>
        </div>
      </div>

      {/* Main canvas + optional selections panel */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div
          className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${showSelectionsPanel ? "border-r border-slate-700" : ""}`}
        >
          {/* Large central viewer - Başta sayfaya sığar, zoom sonrası scrollbar ile yukarı/aşağı/sağa/sola kaydırılır */}
          <div
            ref={viewerRef}
            className="min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-auto overscroll-contain bg-slate-900 p-6"
          >
            {!selectedPdf ? (
              <div className="flex min-h-full min-w-full items-center justify-center">
                <div className="rounded-xl border-2 border-dashed border-slate-600 bg-slate-800/50 p-12 text-center">
                  <p className="text-slate-400">PDF seçin veya yeni PDF ekleyin</p>
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="mt-4 rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white"
                  >
                    PDF Ekle
                  </button>
                </div>
              </div>
            ) : (
              <div
                className="relative mx-auto block shrink-0 overflow-visible"
                style={{
                  width: imgSize ? Math.round(imgSize.w * (zoom / 100)) : "auto",
                  height: imgSize ? Math.round(imgSize.h * (zoom / 100)) : "auto",
                  minWidth: imgSize ? Math.round(imgSize.w * (zoom / 100)) : 1,
                  minHeight: imgSize ? Math.round(imgSize.h * (zoom / 100)) : 1,
                }}
              >
                {!imgLoaded && (
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80">
                    <span className="text-slate-400">Yükleniyor…</span>
                  </div>
                )}
                <div className="relative h-full w-full overflow-visible">
                  <ReactCrop
                    key={pageUrl}
                    crop={crop}
                    onChange={(c, percentCrop) => {
                      setCrop(c);
                      if (editingSelectionId && percentCrop) {
                        const box = percentCropToNormalizedRect(percentCrop);
                        setPendingSelections((prev) =>
                          prev.map((s) =>
                            s.id === editingSelectionId ? { ...s, crop: box } : s
                          )
                        );
                      }
                    }}
                    onComplete={handleCropComplete}
                    className="cursor-crosshair"
                    renderSelectionAddon={
                      completedCrop && !editingSelectionId
                        ? () => (
                            <div className="absolute left-1/2 top-full z-10 mt-2 -translate-x-1/2 overflow-visible">
                              <InlineAnswerBar
                                dark
                                selectedAnswer={inlineSelectedAnswer}
                                onSelect={setInlineSelectedAnswer}
                                onConfirm={() => handleAnswerPicked(inlineSelectedAnswer)}
                                onCancel={() => {
                                  setCompletedCrop(null);
                                  setCrop(undefined);
                                  pendingAddPercentCropRef.current = null;
                                  setInlineSelectedAnswer(null);
                                }}
                              />
                            </div>
                          )
                        : undefined
                    }
                  >
                    <img
                      ref={imgRef}
                      src={pageUrl!}
                      alt={`Sayfa ${currentPage}`}
                      onLoad={onImageLoad}
                      className="block h-full w-full rounded border border-slate-600 object-fill shadow-2xl"
                    />
                  </ReactCrop>
                  {imgLoaded && imgSize && (
                    <SelectionOverlay
                      selections={pendingSelections}
                      currentPdfId={selectedPdf?.id ?? null}
                      currentPage={currentPage}
                      displayedW={Math.round(imgSize.w * (zoom / 100))}
                      displayedH={Math.round(imgSize.h * (zoom / 100))}
                      editingSelectionId={editingSelectionId}
                      onStartEdit={handleStartEditSelection}
                      onEndEdit={handleEndEditSelection}
                      onAnswerChange={handleAnswerChange}
                      onDelete={handleDeleteSelection}
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Bottom toolbar */}
          <div className="flex h-14 min-w-0 shrink-0 items-center gap-4 overflow-hidden border-t border-slate-700 bg-slate-800 px-4">
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              Önceki
            </button>
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
              disabled={currentPage >= pageCount}
              className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              Sonraki
            </button>

            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-400">Sayfa</label>
              <select
                value={currentPage}
                onChange={(e) => setCurrentPage(Number(e.target.value))}
                disabled={!pageCount}
                className="min-w-[4.5rem] rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {Array.from({ length: pageCount || 0 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-400">/ {pageCount}</span>
            </div>

            <button
              type="button"
              onClick={handleSaveAll}
              disabled={saving}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {saving ? "Kaydediliyor…" : pendingSelections.some((s) => !s.backendId)
                ? "Seçimleri Kaydet (Tüm PDF'ler)"
                : "Ana Editöre Dön"}
            </button>

            <div className="flex-1 min-w-0" />
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-slate-400">Zoom</span>
              <button
                type="button"
                onClick={zoomOut}
                disabled={!selectedPdf || zoom <= ZOOM_MIN}
                className="flex h-8 w-8 items-center justify-center rounded border border-slate-600 bg-slate-700 text-lg font-bold text-white hover:bg-slate-600 disabled:opacity-40"
                title="Zoom out (Ctrl+-)"
              >
                −
              </button>
              <input
                type="range"
                min={ZOOM_MIN}
                max={effectiveMaxZoom}
                step={ZOOM_STEP}
                value={Math.min(zoom, effectiveMaxZoom)}
                onChange={(e) =>
                  setZoom(Math.min(effectiveMaxZoom, Number(e.target.value)))
                }
                className="h-2 w-28 accent-blue-500"
              />
              <button
                type="button"
                onClick={zoomIn}
                disabled={!selectedPdf || zoom >= effectiveMaxZoom}
                className="flex h-8 w-8 items-center justify-center rounded border border-slate-600 bg-slate-700 text-lg font-bold text-white hover:bg-slate-600 disabled:opacity-40"
                title="Zoom in (Ctrl++)"
              >
                +
              </button>
              <span className="w-12 text-sm text-slate-300">{zoom}%</span>
            </div>
          </div>
        </div>

        {/* Selections panel */}
        {showSelectionsPanel && (
          <div className="w-72 shrink-0 overflow-auto border-l border-slate-700 bg-slate-800 p-3">
            <h4 className="mb-3 text-sm font-semibold text-white">Sorular</h4>
            <p className="mb-2 text-[10px] text-slate-400">Sürükle-bırak ile sıralama</p>
            {pendingSelections.length === 0 ? (
              <p className="text-xs text-slate-400">Henüz seçim yok</p>
            ) : (
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={(e: DragEndEvent) => {
                  const { active, over } = e;
                  if (!over || active.id === over.id) return;
                  const from = pendingSelections.findIndex((s) => s.id === active.id);
                  const to = pendingSelections.findIndex((s) => s.id === over.id);
                  if (from < 0 || to < 0 || from === to) return;
                  const next = [...pendingSelections];
                  const [removed] = next.splice(from, 1);
                  next.splice(to, 0, removed);
                  setPendingSelections(next.map((s, i) => ({ ...s, number: i + 1 })));
                }}
              >
                <SortableContext items={pendingSelections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                  <ul className="space-y-2">
                    {pendingSelections.map((s) => {
                      const pdf = pdfs.find((p) => p.id === s.pdf_id);
                      return (
                        <SortableSelectionItem
                          key={s.id}
                          sel={s}
                          pdf={pdf}
                          onRemove={removePending}
                          onNavigate={(pdfId, pageNumber) => {
                            const p = pdfs.find((f) => f.id === pdfId);
                            if (p) {
                              setSelectedPdf(p);
                              setCurrentPage(pageNumber);
                            }
                          }}
                        />
                      );
                    })}
                  </ul>
                </SortableContext>
              </DndContext>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 rounded-lg bg-rose-900/90 px-4 py-2 text-sm text-white">
          {error}
        </div>
      )}

      <PdfDeleteModal
        open={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          fetchPdfs();
        }}
        onPdfDeleted={handlePdfDeleted}
      />
    </div>
  );
}
