# Desktop to Web Architecture Analysis

## 1) Desktop architecture analysis (PyQt5 -> Web)

Typical PyQt desktop apps in this domain mix UI and logic in the same classes. During migration, split into:

- `UI layer` (PyQt widgets, event handlers, drag/drop visuals) -> **React frontend**
- `Application services` (PDF load/render/crop, question operations, draft state, export pipeline) -> **FastAPI backend services**
- `Domain models` (Question, CropBox, PDF metadata, Draft payload) -> **Pydantic schemas in backend**
- `Persistence` (local files/settings) -> **backend storage adapters**

This avoids rewriting core behavior and removes toolkit coupling.

## 2) Reusable module mapping

Use this mapping when porting existing desktop files:

- **Reusable in backend with minimal change**
  - PDF processing and rendering helpers
  - Crop rectangle normalization
  - Question ordering logic
  - Answer key validation/rules
  - Draft serialization
  - PDF export/layout generation

- **Refactor into backend interfaces**
  - Anything currently calling PyQt file dialogs, scene coordinates, widget state directly
  - Replace with request DTOs and service methods

- **Replace entirely in frontend**
  - QWidget/QGraphicsView screens
  - Drag/drop widget code
  - Keyboard shortcuts and UI-only selection behavior

## 3) Clean full-stack structure

```text
backend/
  app/
    api/routes/         # HTTP controllers
    core/               # config, startup wiring
    models/             # pydantic schemas
    services/           # reusable business logic
    dependencies.py
    main.py
  storage/
    uploads/
    drafts/
    exports/
  requirements.txt

frontend/
  src/
    api.js              # backend client
    App.jsx             # MVP feature flow
    styles.css
    main.jsx
  index.html
  package.json
  vite.config.js
```

## 4) Incremental build plan

1. **MVP (implemented now)**: upload, list, page render, crop, question CRUD-lite, reorder, draft, simple export.
2. **V2**: auth, project-level state, DB storage, async jobs for heavy exports.
3. **V3**: advanced layout engine (themes/sections/watermarks/answer key modes) as configurable backend pipeline.
