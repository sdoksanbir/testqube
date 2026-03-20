"""Taslak (proje) kaydetme/geri yükleme.

Kullanıcı ihtiyacı:
- Tek bir dosya (ör. taslak.db) içinde; sorular + tüm ayarlar + bölüm bilgileri
- Taslak yüklenince PDF'lere bağlı olmadan çalışsın (soru görselleri dosyanın içinde olsun)

Uygulama:
- Varsayılan format: SQLite (.db / .tmd)
- Geriye dönük uyumluluk: Eski .json taslakları da okunabilir.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from testmaker.models.selection import Selection


@dataclass
class Draft:
    selections: List[Selection]
    export_settings: Dict[str, Any] | None = None
    other_settings: Dict[str, Any] | None = None
    test_info: Dict[str, str] | None = None


# ---------------------------
# JSON legacy helpers
# ---------------------------
def _selection_to_dict(sel: Selection) -> Dict[str, Any]:
    return {
        'norm': sel.norm,
        'answer': sel.answer,
        'pdf_key': sel.pdf_key,
        'page_index': sel.page_index,
        'number': sel.number,
        'preview_scale': getattr(sel, 'preview_scale', 1.0),
        'display_scale': getattr(sel, 'display_scale', 1.0),
        'custom_gap_after_pt': getattr(sel, 'custom_gap_after_pt', None),
        'custom_gap_before_pt': getattr(sel, 'custom_gap_before_pt', None),
        'section_enabled': getattr(sel, 'section_enabled', False),
        'section_title': getattr(sel, 'section_title', "") or "",
        'section_restart_numbering': getattr(sel, 'section_restart_numbering', False),
        'section_start_new_page': getattr(sel, 'section_start_new_page', False),
        'section_end_number': getattr(sel, 'section_end_number', None),
        'section_fill_color': getattr(sel, 'section_fill_color', "#FFFFFF") or "#FFFFFF",
        'section_text_color': getattr(sel, 'section_text_color', "#000000") or "#000000",
        'section_line_color': getattr(sel, 'section_line_color', "#000000") or "#000000",
        'section_font_pt': float(getattr(sel, 'section_font_pt', 12.0) or 12.0),
    }


def _dict_to_selection(d: Dict[str, Any]) -> Selection:
    sel = Selection(
        norm_rect=d.get('norm', (0, 0, 1, 1)),
        answer=d.get('answer'),
        pdf_key=d.get('pdf_key', ''),
        page_index=d.get('page_index', 0),
        number=d.get('number', 0),
    )
    sel.preview_scale = d.get('preview_scale', 1.0)
    sel.display_scale = d.get('display_scale', 1.0)
    sel.custom_gap_after_pt = d.get('custom_gap_after_pt', None)
    sel.custom_gap_before_pt = d.get('custom_gap_before_pt', None)
    sel.section_enabled = bool(d.get('section_enabled', False))
    sel.section_title = d.get('section_title', "") or ""
    sel.section_restart_numbering = bool(d.get('section_restart_numbering', False))
    sel.section_start_new_page = bool(d.get('section_start_new_page', False))
    sel.section_end_number = d.get('section_end_number', None)
    sel.section_fill_color = d.get('section_fill_color', "#FFFFFF") or "#FFFFFF"
    sel.section_text_color = d.get('section_text_color', "#000000") or "#000000"
    sel.section_line_color = d.get('section_line_color', "#000000") or "#000000"
    try:
        sel.section_font_pt = float(d.get('section_font_pt', 12.0) or 12.0)
    except Exception:
        sel.section_font_pt = 12.0
    return sel


def _save_json(path: Path, draft: Draft) -> None:
    data = {
        'selections': [_selection_to_dict(sel) for sel in draft.selections],
        'export_settings': draft.export_settings or {},
        'other_settings': draft.other_settings or {},
        'test_info': draft.test_info or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_json(path: Path) -> Draft:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    selections = [_dict_to_selection(d) for d in data.get('selections', [])]
    return Draft(
        selections=selections,
        export_settings=data.get('export_settings'),
        other_settings=data.get('other_settings'),
        test_info=data.get('test_info'),
    )


# ---------------------------
# SQLite (single-file) format
# ---------------------------
SCHEMA_VERSION = 1


def _init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            idx INTEGER PRIMARY KEY,
            answer TEXT,
            number INTEGER,
            display_scale REAL,
            preview_scale REAL,
            custom_gap_after_pt REAL,
            custom_gap_before_pt REAL,

            section_enabled INTEGER,
            section_title TEXT,
            section_restart_numbering INTEGER,
            section_start_new_page INTEGER,
            section_end_number INTEGER,
            section_fill_color TEXT,
            section_text_color TEXT,
            section_line_color TEXT,
            section_font_pt REAL,

            img_png BLOB,
            img_w_px INTEGER,
            img_h_px INTEGER
        )
        """
    )
    conn.commit()


def _save_sqlite(path: Path, draft: Draft) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    try:
        _init_db(conn)
        cur = conn.cursor()

        meta = {
            'schema_version': SCHEMA_VERSION,
            'export_settings': draft.export_settings or {},
            'other_settings': draft.other_settings or {},
            'test_info': draft.test_info or {},
        }
        for k, v in meta.items():
            cur.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (k, json.dumps(v, ensure_ascii=False)),
            )

        for idx, sel in enumerate(draft.selections):
            cur.execute(
                """
                INSERT INTO questions(
                    idx, answer, number, display_scale, preview_scale,
                    custom_gap_after_pt, custom_gap_before_pt,
                    section_enabled, section_title, section_restart_numbering, section_start_new_page,
                    section_end_number, section_fill_color, section_text_color, section_line_color, section_font_pt,
                    img_png, img_w_px, img_h_px
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    idx,
                    sel.answer,
                    int(getattr(sel, 'number', idx + 1) or (idx + 1)),
                    float(getattr(sel, 'display_scale', 1.0) or 1.0),
                    float(getattr(sel, 'preview_scale', 1.0) or 1.0),
                    getattr(sel, 'custom_gap_after_pt', None),
                    getattr(sel, 'custom_gap_before_pt', None),
                    1 if getattr(sel, 'section_enabled', False) else 0,
                    getattr(sel, 'section_title', "") or "",
                    1 if getattr(sel, 'section_restart_numbering', False) else 0,
                    1 if getattr(sel, 'section_start_new_page', False) else 0,
                    getattr(sel, 'section_end_number', None),
                    getattr(sel, 'section_fill_color', "#FFFFFF") or "#FFFFFF",
                    getattr(sel, 'section_text_color', "#000000") or "#000000",
                    getattr(sel, 'section_line_color', "#000000") or "#000000",
                    float(getattr(sel, 'section_font_pt', 12.0) or 12.0),
                    getattr(sel, 'embedded_png', None),
                    getattr(sel, 'embedded_w_px', None),
                    getattr(sel, 'embedded_h_px', None),
                ),
            )

        conn.commit()
    finally:
        conn.close()


def _load_sqlite(path: Path) -> Draft:
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.cursor()
        # meta
        cur.execute("SELECT key, value FROM meta")
        meta_rows = cur.fetchall()
        meta: Dict[str, Any] = {}
        for k, v in meta_rows:
            try:
                meta[k] = json.loads(v)
            except Exception:
                meta[k] = v

        cur.execute(
            """
            SELECT
              idx, answer, number, display_scale, preview_scale,
              custom_gap_after_pt, custom_gap_before_pt,
              section_enabled, section_title, section_restart_numbering, section_start_new_page,
              section_end_number, section_fill_color, section_text_color, section_line_color, section_font_pt,
              img_png, img_w_px, img_h_px
            FROM questions
            ORDER BY idx ASC
            """
        )
        rows = cur.fetchall()

        selections: List[Selection] = []
        for r in rows:
            (
                _idx, answer, number, display_scale, preview_scale,
                gap_after, gap_before,
                section_enabled, section_title, section_restart, section_new_page,
                section_end, fill_c, text_c, line_c, font_pt,
                img_png, img_w_px, img_h_px,
            ) = r

            # PDF'e bağımlı olmayan seçim: pdf_key/page_index/norm dummy
            sel = Selection((0, 0, 1, 1), answer, pdf_key="__EMBEDDED__", page_index=0, number=int(number or 0))
            sel.display_scale = float(display_scale or 1.0)
            sel.preview_scale = float(preview_scale or 1.0)
            sel.custom_gap_after_pt = gap_after
            sel.custom_gap_before_pt = gap_before
            sel.section_enabled = bool(section_enabled)
            sel.section_title = section_title or ""
            sel.section_restart_numbering = bool(section_restart)
            sel.section_start_new_page = bool(section_new_page)
            sel.section_end_number = section_end
            sel.section_fill_color = fill_c or "#FFFFFF"
            sel.section_text_color = text_c or "#000000"
            sel.section_line_color = line_c or "#000000"
            try:
                sel.section_font_pt = float(font_pt or 12.0)
            except Exception:
                sel.section_font_pt = 12.0
            sel.embedded_png = img_png
            sel.embedded_w_px = img_w_px
            sel.embedded_h_px = img_h_px
            selections.append(sel)

        return Draft(
            selections=selections,
            export_settings=meta.get('export_settings') or {},
            other_settings=meta.get('other_settings') or {},
            test_info=meta.get('test_info') or {},
        )
    finally:
        conn.close()


def save_draft(path: Path, draft: Draft) -> None:
    """Taslağı kaydeder.

    - .json verilirse legacy JSON yazar
    - diğer uzantılarda SQLite yazar (varsayılan: .db)
    """
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix('.db')

    if path.suffix.lower() == '.json':
        _save_json(path, draft)
        return

    _save_sqlite(path, draft)


def load_draft(path: Path) -> Draft:
    """Taslağı yükler.

    - .json ise legacy okur
    - aksi halde sqlite okur
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Taslak dosyası bulunamadı: {path}")

    if path.suffix.lower() == '.json':
        return _load_json(path)
    return _load_sqlite(path)
