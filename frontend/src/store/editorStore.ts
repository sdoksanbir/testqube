import { create } from "zustand";
import type { QuestionItem } from "../types";
import { api } from "../api/client";

export type SidebarTab = "test-paper" | "settings";
export type AnswerOption = "A" | "B" | "C" | "D" | "E";

type OptionFlags = {
  includeDescription: boolean;
  addSpacingBetweenQuestions: boolean;
  includeAnswerKey: boolean;
  addTextOnLine: boolean;
};

type ModalKey = "pdf-bank" | "question-editor" | "save-draft" | "load-draft";

type EditorState = {
  activeTab: SidebarTab;
  testName: string;
  schoolName: string;
  options: OptionFlags;
  questions: QuestionItem[];
  questionsLoaded: boolean;
  openModal: ModalKey | null;
  setActiveTab: (tab: SidebarTab) => void;
  setTestName: (value: string) => void;
  setSchoolName: (value: string) => void;
  toggleOption: (key: keyof OptionFlags) => void;
  setQuestionAnswer: (id: string, answer: AnswerOption) => Promise<void>;
  removeQuestion: (id: string) => Promise<void>;
  reorderQuestions: (orderedIds: string[]) => Promise<void>;
  addQuestion: (item: QuestionItem) => void;
  setQuestions: (items: QuestionItem[]) => void;
  fetchQuestions: () => Promise<void>;
  setOpenModal: (key: ModalKey | null) => void;
};

export const useEditorStore = create<EditorState>((set, get) => ({
  activeTab: "test-paper",
  testName: "",
  schoolName: "",
  options: {
    includeDescription: false,
    addSpacingBetweenQuestions: true,
    includeAnswerKey: true,
    addTextOnLine: false,
  },
  questions: [],
  questionsLoaded: false,
  openModal: null,
  setActiveTab: (tab) => set({ activeTab: tab }),
  setTestName: (value) => set({ testName: value }),
  setSchoolName: (value) => set({ schoolName: value }),
  toggleOption: (key) =>
    set((state) => ({
      options: { ...state.options, [key]: !state.options[key] },
    })),
  setQuestionAnswer: async (id, answer) => {
    try {
      const updated = await api.questions.updateAnswer(id, answer);
      set((state) => ({
        questions: state.questions.map((q) => (q.id === id ? updated : q)),
      }));
    } catch (e) {
      console.error("Failed to update answer:", e);
    }
  },
  removeQuestion: async (id) => {
    try {
      await api.questions.delete(id);
      set((state) => ({
        questions: state.questions
          .filter((q) => q.id !== id)
          .map((q, i) => ({ ...q, order_index: i })),
      }));
    } catch (e) {
      console.error("Failed to delete question:", e);
    }
  },
  reorderQuestions: async (orderedIds) => {
    try {
      const { items } = await api.questions.reorder(orderedIds);
      set({ questions: items });
    } catch (e) {
      console.error("Failed to reorder:", e);
    }
  },
  addQuestion: (item) => set((state) => ({ questions: [...state.questions, item] })),
  setQuestions: (items) => set({ questions: items }),
  fetchQuestions: async () => {
    try {
      const { items } = await api.questions.list();
      set({ questions: items, questionsLoaded: true });
    } catch (e) {
      console.error("Failed to fetch questions:", e);
      set({ questionsLoaded: true });
    }
  },
  setOpenModal: (key) => set({ openModal: key }),
}));
