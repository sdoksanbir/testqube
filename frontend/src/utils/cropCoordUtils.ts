/**
 * Crop/selection coordinate utilities.
 * Desktop parity: norm (0..1) is the only persistent format. Zoom is display-only.
 *
 * Coordinate systems:
 * - Display: pixel coords in the visible/rendered image container (includes any CSS scale)
 * - Image: pixel coords in the actual image dimensions (naturalWidth × naturalHeight)
 * - Norm: 0..1 relative to page, zoom-invariant persistent format
 */

export interface NormRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DisplayRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface ImageRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Convert client/screen point (relative to container) to image-local point.
 * Use displayed image dimensions (offsetWidth/Height or getBoundingClientRect) and
 * natural dimensions for correct scaling.
 */
export function clientPointToImagePoint(
  clientX: number,
  clientY: number,
  containerRect: DOMRect,
  displayedWidth: number,
  displayedHeight: number,
  naturalWidth: number,
  naturalHeight: number
): { x: number; y: number } {
  const localX = clientX - containerRect.left;
  const localY = clientY - containerRect.top;
  const scaleX = naturalWidth / Math.max(1, displayedWidth);
  const scaleY = naturalHeight / Math.max(1, displayedHeight);
  return {
    x: localX * scaleX,
    y: localY * scaleY,
  };
}

/**
 * Convert display rect (in displayed pixel coords) to normalized rect (0..1).
 * displayedWidth/Height = the rendered image size on screen (after any CSS scale).
 * naturalWidth/Height = image intrinsic dimensions (must be from fixed-DPI render).
 */
export function displayRectToNormalizedRect(
  displayRect: DisplayRect,
  displayedWidth: number,
  displayedHeight: number,
  naturalWidth: number,
  naturalHeight: number
): NormRect {
  const scaleX = naturalWidth / Math.max(1, displayedWidth);
  const scaleY = naturalHeight / Math.max(1, displayedHeight);
  const imgRect: ImageRect = {
    left: displayRect.left * scaleX,
    top: displayRect.top * scaleY,
    width: displayRect.width * scaleX,
    height: displayRect.height * scaleY,
  };
  return {
    x: imgRect.left / Math.max(1, naturalWidth),
    y: imgRect.top / Math.max(1, naturalHeight),
    width: imgRect.width / Math.max(1, naturalWidth),
    height: imgRect.height / Math.max(1, naturalHeight),
  };
}

/**
 * Convert PixelCrop from react-image-crop to normalized rect.
 * ReactCrop gives pixel coords in the displayed/croppable area.
 */
export function pixelCropToNormalizedRect(
  crop: { x: number; y: number; width: number; height: number },
  displayedWidth: number,
  displayedHeight: number,
  naturalWidth: number,
  naturalHeight: number
): NormRect {
  return displayRectToNormalizedRect(
    { left: crop.x, top: crop.y, width: crop.width, height: crop.height },
    displayedWidth,
    displayedHeight,
    naturalWidth,
    naturalHeight
  );
}

/**
 * Convert PercentCrop (0-100) to normalized rect (0-1).
 * Zoom/display independent - use this for reliable crop coordinates.
 */
export function percentCropToNormalizedRect(
  crop: { x: number; y: number; width: number; height: number }
): NormRect {
  return {
    x: crop.x / 100,
    y: crop.y / 100,
    width: crop.width / 100,
    height: crop.height / 100,
  };
}

/**
 * Convert normalized rect (0-1) to PercentCrop (0-100) for ReactCrop.
 */
export function normalizedRectToPercentCrop(
  norm: NormRect
): { x: number; y: number; width: number; height: number } {
  return {
    x: norm.x * 100,
    y: norm.y * 100,
    width: norm.width * 100,
    height: norm.height * 100,
  };
}

/**
 * Convert normalized rect to display rect for overlay rendering.
 * Use when drawing selection overlays on the image.
 */
export function normalizedRectToDisplayRect(
  norm: NormRect,
  displayedWidth: number,
  displayedHeight: number
): DisplayRect {
  return {
    left: norm.x * displayedWidth,
    top: norm.y * displayedHeight,
    width: norm.width * displayedWidth,
    height: norm.height * displayedHeight,
  };
}

/**
 * Clamp norm rect to valid 0..1 range.
 */
export function clampNormRect(norm: NormRect): NormRect {
  const x = Math.max(0, Math.min(1, norm.x));
  const y = Math.max(0, Math.min(1, norm.y));
  const w = Math.max(0, Math.min(1 - x, norm.width));
  const h = Math.max(0, Math.min(1 - y, norm.height));
  return { x, y, width: w, height: h };
}

/**
 * Validate norm rect (all in 0..1, non-degenerate).
 */
export function isValidNormRect(norm: NormRect): boolean {
  return (
    norm.x >= 0 &&
    norm.x <= 1 &&
    norm.y >= 0 &&
    norm.y <= 1 &&
    norm.width > 0 &&
    norm.width <= 1 &&
    norm.height > 0 &&
    norm.height <= 1 &&
    norm.x + norm.width <= 1 &&
    norm.y + norm.height <= 1
  );
}

/**
 * Desktop parity: Boşluk varsa seçim alanını içeriğe (soruya) sığacak kadar küçült.
 * Canvas ile görüntüden içerik bbox bulunur, padding eklenir.
 *
 * @param img - Yüklü PDF sayfa görseli
 * @param percentCrop - Seçim alanı (0-100)
 * @param options - padding (piksel)
 * @returns Trimlenmiş norm rect veya null (içerik bulunamazsa orijinal kullanılır)
 */
export function trimCropToContent(
  img: HTMLImageElement,
  percentCrop: { x: number; y: number; width: number; height: number },
  options?: { paddingH?: number; paddingV?: number; whiteThreshold?: number }
): NormRect | null {
  const padH = options?.paddingH ?? 10;
  const padV = options?.paddingV ?? 5;
  const whiteThreshold = options?.whiteThreshold ?? 200;

  const w = img.naturalWidth;
  const h = img.naturalHeight;
  if (w <= 0 || h <= 0) return null;

  const x0 = Math.floor((percentCrop.x / 100) * w);
  const y0 = Math.floor((percentCrop.y / 100) * h);
  const cw = Math.max(1, Math.floor((percentCrop.width / 100) * w));
  const ch = Math.max(1, Math.floor((percentCrop.height / 100) * h));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(x0, y0, cw, ch);
  const pixels = data.data;

  let xMin = cw;
  let yMin = ch;
  let xMax = 0;
  let yMax = 0;

  for (let py = 0; py < ch; py++) {
    for (let px = 0; px < cw; px++) {
      const i = (py * cw + px) * 4;
      const r = pixels[i];
      const g = pixels[i + 1];
      const b = pixels[i + 2];
      const avg = (r + g + b) / 3;
      if (avg < whiteThreshold) {
        xMin = Math.min(xMin, px);
        yMin = Math.min(yMin, py);
        xMax = Math.max(xMax, px + 1);
        yMax = Math.max(yMax, py + 1);
      }
    }
  }

  if (xMin >= xMax || yMin >= yMax) return null;

  xMin = Math.max(0, xMin - padH);
  yMin = Math.max(0, yMin - padV);
  xMax = Math.min(cw, xMax + padH);
  yMax = Math.min(ch, yMax + padV);

  const trimX = (x0 + xMin) / w;
  const trimY = (y0 + yMin) / h;
  const trimW = (xMax - xMin) / w;
  const trimH = (yMax - yMin) / h;

  return clampNormRect({
    x: trimX,
    y: trimY,
    width: trimW,
    height: trimH,
  });
}
