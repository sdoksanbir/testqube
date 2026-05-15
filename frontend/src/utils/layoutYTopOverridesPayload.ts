import type { QuestionItem } from "../types";

/**
 * Store (soru id → y_top_pt) → API’nin beklediği order_index listesi.
 * Soru sırası değişince güncel `questions` ile tekrar üretilir.
 */
export function buildLayoutYTopOverridesForApi(
  overridesByQuestionId: Record<string, number>,
  questions: QuestionItem[]
): { order_index: number; y_top_pt: number }[] {
  const out: { order_index: number; y_top_pt: number }[] = [];
  for (const [id, y_top_pt] of Object.entries(overridesByQuestionId)) {
    const q = questions.find((x) => x.id === id);
    if (q) out.push({ order_index: q.order_index, y_top_pt });
  }
  return out;
}

export function layoutYTopOverridesApiPayload(
  overridesByQuestionId: Record<string, number>,
  questions: QuestionItem[]
): { layout_y_top_overrides?: { order_index: number; y_top_pt: number }[] } {
  const list = buildLayoutYTopOverridesForApi(overridesByQuestionId, questions);
  return list.length > 0 ? { layout_y_top_overrides: list } : {};
}
