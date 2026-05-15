from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import drafts, exports, pdfs, questions
from app.core.config import ensure_storage_dirs

ensure_storage_dirs()

app = FastAPI(title="TestQube Web Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pdfs.router, prefix="/api")
app.include_router(questions.router, prefix="/api")
app.include_router(drafts.router, prefix="/api")
app.include_router(exports.router, prefix="/api")


@app.get("/health")
def health():
    return {"ok": True}
