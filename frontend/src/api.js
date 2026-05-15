const API_BASE = "http://localhost:8000/api";

async function asJson(res) {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Request failed");
  }
  return res.json();
}

export async function uploadPdfs(files) {
  const form = new FormData();
  Array.from(files).forEach((f) => form.append("files", f));
  const res = await fetch(`${API_BASE}/pdfs/upload`, { method: "POST", body: form });
  return asJson(res);
}

export async function listPdfs() {
  const res = await fetch(`${API_BASE}/pdfs`);
  return asJson(res);
}

export function pageImageUrl(pdfId, pageNumber) {
  return `${API_BASE}/pdfs/${pdfId}/pages/${pageNumber}/image?zoom=2`;
}

export async function listQuestions() {
  const res = await fetch(`${API_BASE}/questions`);
  return asJson(res);
}

export async function createQuestion(payload) {
  const res = await fetch(`${API_BASE}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return asJson(res);
}

export async function updateAnswer(questionId, answer_key) {
  const res = await fetch(`${API_BASE}/questions/${questionId}/answer`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer_key })
  });
  return asJson(res);
}

export async function reorderQuestions(ordered_ids) {
  const res = await fetch(`${API_BASE}/questions/reorder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_ids })
  });
  return asJson(res);
}

export async function listDrafts() {
  const res = await fetch(`${API_BASE}/drafts`);
  return asJson(res);
}

export async function saveDraft(payload) {
  const res = await fetch(`${API_BASE}/drafts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return asJson(res);
}

export async function loadDraft(name) {
  const res = await fetch(`${API_BASE}/drafts/${name}`);
  return asJson(res);
}

export async function exportSimple(payload) {
  const res = await fetch(`${API_BASE}/exports/simple`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return asJson(res);
}
