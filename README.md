# TestQube Web Migration MVP

This repository contains a production-style MVP scaffold to migrate a PyQt5 desktop app into a web app.

## Stack

- Backend: FastAPI
- Frontend: React + Vite
- PDF processing: PyMuPDF (`fitz`)

## High-level migration strategy

- Keep business logic in backend services (`backend/app/services`).
- Keep domain models and validation in backend schemas (`backend/app/models`).
- Replace all PyQt UI logic with frontend interaction components (`frontend/src`).
- Keep file persistence in backend storage for MVP (`backend/storage`).

## Run backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

## MVP flow implemented

- Upload one or more PDFs
- List uploaded PDFs
- Render selected page as image
- Create crop selection from page image
- Add selection to question list
- Edit answer keys
- Reorder questions via drag-and-drop
- Save/load drafts
- Export simple PDF from selected regions
