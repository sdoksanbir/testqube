import json
from datetime import datetime
from pathlib import Path
from typing import List

from app.core.config import DRAFT_DIR
from app.models.schemas import DraftInfo, DraftPayload


class DraftService:
    def list_drafts(self) -> List[DraftInfo]:
        infos: List[DraftInfo] = []
        for path in DRAFT_DIR.glob("*.json"):
            stat = path.stat()
            infos.append(
                DraftInfo(
                    name=path.stem,
                    path=str(path),
                    updated_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )
        return sorted(infos, key=lambda d: d.updated_at, reverse=True)

    def save_draft(self, payload: DraftPayload) -> DraftInfo:
        target = DRAFT_DIR / f"{payload.name}.json"
        target.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        stat = target.stat()
        return DraftInfo(
            name=payload.name,
            path=str(target),
            updated_at=datetime.fromtimestamp(stat.st_mtime),
        )

    def load_draft(self, name: str) -> DraftPayload:
        path = DRAFT_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Draft not found: {name}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        return DraftPayload(**raw)
