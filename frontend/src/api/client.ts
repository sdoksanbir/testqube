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
      else params.set("dpi", "150");
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
    updateAnswer: (questionId: string, answerKey: string) =>
      fetch(`${API_BASE}/questions/${questionId}/answer`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer_key: answerKey }),
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
};
