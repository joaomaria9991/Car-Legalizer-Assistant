#!/usr/bin/env python3
"""
E2E TEST (front-end accurate):
Split local -> Upload pages (parallel) -> classify -> extract/harmonize -> DAV_FLOW chat loop

Requisitos:
- Backend FastAPI a correr (ex: http://localhost:8000)
- Diretoria com docs (pdf/jpg/png/webp)

Contrato backend:
- GET  /processes/{pid}
- POST /processes/{pid}/events  (form field: event_json; opcional: file UploadFile)

Uso:
  python e2e_test.py --docs-dir "./docs" --process-id "e2e-demo-001"
  python e2e_test.py --docs-dir "./docs" --process-id "e2e-001" --api "http://localhost:8000" --concurrency 10 --auto
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import fitz  # PyMuPDF
from PIL import Image


DEFAULT_API = "http://localhost:8000"
ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


# =========================
# Timer
# =========================

@contextmanager
def timer(label: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"⏱️  {label}: {dt:.2f}s")


# =========================
# Docs discovery
# =========================

def list_docs(docs_dir: Path) -> List[Path]:
    paths = [p for p in docs_dir.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_EXTS]
    paths.sort(key=lambda x: x.name.lower())
    return paths


# =========================
# Split local like frontend (in-memory)
# =========================

def _img_to_jpg_bytes(img: Image.Image, quality: int = 85) -> bytes:
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def split_image_file_to_pages(img_path: Path) -> List[Tuple[str, bytes, str]]:
    """
    Any image -> 1 JPG page: {stem}_page_1.jpg
    """
    img = Image.open(img_path)
    jpg_bytes = _img_to_jpg_bytes(img, quality=85)
    filename = f"{img_path.stem}_page_1.jpg"
    return [(filename, jpg_bytes, "image/jpeg")]


def split_pdf_file_to_pages(pdf_path: Path) -> List[Tuple[str, bytes, str]]:
    """
    PDF -> JPG per page: {stem}_page_{n}.jpg
    Uses PyMuPDF like your simulator.
    """
    pages: List[Tuple[str, bytes, str]] = []
    doc = fitz.open(pdf_path)
    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # ~150dpi equivalent
            img = Image.open(BytesIO(pix.tobytes("ppm")))
            jpg_bytes = _img_to_jpg_bytes(img, quality=85)
            filename = f"{pdf_path.stem}_page_{page_num + 1}.jpg"
            pages.append((filename, jpg_bytes, "image/jpeg"))
    finally:
        doc.close()

    return pages


def split_docs_like_frontend(docs: List[Path]) -> List[Tuple[str, bytes, str]]:
    uploads: List[Tuple[str, bytes, str]] = []
    for p in docs:
        if p.suffix.lower() == ".pdf":
            uploads.extend(split_pdf_file_to_pages(p))
        else:
            uploads.extend(split_image_file_to_pages(p))
    return uploads


# =========================
# UI helpers
# =========================

def pretty_ui_out(state: Dict[str, Any]) -> Dict[str, Any]:
    return ((state.get("flags") or {}).get("ui_out") or {})


def print_phase(state: Dict[str, Any]) -> None:
    print(f"📍 fase={state.get('fase_atual')} | sub_fase={state.get('sub_fase')}")


def print_dav_question(ui_out: Dict[str, Any]) -> None:
    print("🧠 ui_out.type = dav_question")
    msg = ui_out.get("message") or ""
    if msg:
        print(f"🤖 {msg}")

    fields = ui_out.get("fields") or []
    if not fields:
        print("⚠️ sem fields")
        return

    print("\n🧾 Campos pedidos:")
    if isinstance(fields, list) and fields and isinstance(fields[0], dict):
        for f in fields:
            field = f.get("field")
            label = f.get("label")
            print(f"  - {field} :: {label}")
            if f.get("explain"):
                print(f"      • {f['explain']}")
            if f.get("where"):
                print(f"      • Onde: {f['where']}")
            ex = f.get("examples") or []
            if ex:
                print(f"      • Ex: {', '.join(map(str, ex))}")
    else:
        for f in fields:
            print(f"  - {f}")


def auto_answer_for_fields(fields) -> str:
    keys = []
    if fields and isinstance(fields, list) and isinstance(fields[0], dict):
        keys = [f.get("field") for f in fields if f.get("field")]
    else:
        keys = list(fields or [])

    defaults = {
        "78": "23",
        "66a": "Importação própria",
        "69": "Definitiva",
        "67": time.strftime("%Y-%m-%d"),
    }

    pairs = []
    for k in keys:
        v = defaults.get(k)
        if v is not None:
            pairs.append(f"{k}={v}")

    return "; ".join(pairs) if pairs else "não sei"


# =========================
# HTTP async helpers
# =========================

async def get_state(client: httpx.AsyncClient, api: str, pid: str) -> Dict[str, Any]:
    r = await client.get(f"{api}/processes/{pid}", timeout=60.0)
    r.raise_for_status()
    return r.json()


async def post_event(
    client: httpx.AsyncClient,
    api: str,
    pid: str,
    event: Dict[str, Any],
    file_tuple: Optional[Tuple[str, bytes, str]] = None,
) -> Dict[str, Any]:
    url = f"{api}/processes/{pid}/events"
    data = {"event_json": json.dumps(event, ensure_ascii=False)}
    files = None
    if file_tuple is not None:
        filename, content, mime = file_tuple
        files = {"file": (filename, content, mime)}

    r = await client.post(url, data=data, files=files, timeout=300.0)
    r.raise_for_status()
    return r.json()


async def upload_pages_parallel(
    client: httpx.AsyncClient,
    api: str,
    pid: str,
    uploads: List[Tuple[str, bytes, str]],
    concurrency: int = 8,
) -> Dict[str, Any]:
    """
    Parallel POST /events type=upload_doc with bounded concurrency.
    Returns last seen state (best-effort).
    """
    sem = asyncio.Semaphore(concurrency)
    last_state: Dict[str, Any] = {}

    async def _one(i: int, tup: Tuple[str, bytes, str]) -> None:
        nonlocal last_state
        fname, content, mime = tup
        async with sem:
            res = await post_event(
                client, api, pid,
                {"type": "upload_doc"},
                file_tuple=(fname, content, mime),
            )
            if "state" in res:
                last_state = res["state"]
            print(f"  ✅ [{i}/{len(uploads)}] {fname} ({len(content)} bytes)")

    await asyncio.gather(*[_one(i + 1, uploads[i]) for i in range(len(uploads))])
    return last_state


# =========================
# Main (async)
# =========================

async def main_async():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--process-id", required=True)
    ap.add_argument("--docs-dir", required=True)
    ap.add_argument("--auto", action="store_true", help="responde automaticamente a alguns campos no DAV_FLOW")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--concurrency", type=int, default=8, help="uploads em paralelo")
    args = ap.parse_args()

    api = args.api.rstrip("/")
    pid = args.process_id
    docs_dir = Path(args.docs_dir)

    if not docs_dir.exists():
        raise SystemExit(f"Diretoria não existe: {docs_dir}")

    docs = list_docs(docs_dir)
    if not docs:
        raise SystemExit(f"Sem docs válidos em: {docs_dir}")

    print("🚗 E2E TEST - Split->Upload(parallel)->Classify->Extract->DAV_FLOW")
    print("=" * 90)
    print(f"API: {api}")
    print(f"Process: {pid}")
    print(f"Docs dir: {docs_dir.resolve()} ({len(docs)} ficheiros)")
    print(f"Upload concurrency: {args.concurrency}")

    t_total = time.perf_counter()

    async with httpx.AsyncClient() as client:
        # 0) Estado inicial
        with timer("GET estado inicial"):
            state = await get_state(client, api, pid)
        print_phase(state)

        # 1) Reset opcional
        print("\n➡️ Reset (opcional) para INTAKE_DOCS...")
        with timer("Reset (opcional)"):
            try:
                res = await post_event(client, api, pid, {
                    "type": "advance_phase",
                    "data": {"nova_fase": "INTAKE_DOCS", "sub_fase": "AGUARDAR_UPLOAD"}
                })
                state = res.get("state", state)
                print("✅ reset ok")
            except httpx.HTTPStatusError:
                print("ℹ️ reset não suportado (ignorado).")
        print_phase(state)

        # 2) Split local
        print("\n🧩 Split local (igual ao front)...")
        with timer("Split local docs -> páginas JPG"):
            uploads = split_docs_like_frontend(docs)
        print(f"📄 páginas geradas: {len(uploads)}")

        # 3) Upload paralelo
        print("\n⬆️ Upload paralelo das páginas JPG...")
        with timer(f"Upload paralelo ({args.concurrency})"):
            state = await upload_pages_parallel(
                client, api, pid, uploads, concurrency=args.concurrency
            )
        print("✅ Upload concluído.")
        if state:
            print_phase(state)

        # 4) Classify
        print("\n🤖 classify_docs...")
        with timer("Classify (LLM)"):
            res = await post_event(client, api, pid, {"type": "classify_docs"})
            state = res["state"]
        print_phase(state)
        ui_out = pretty_ui_out(state)
        if ui_out:
            print("ui_out:", ui_out.get("type"))

        # 5) Extract + harmonize
        print("\n🧠 start_extract (extract + harmonize)...")
        with timer("Extract + Harmonize"):
            res = await post_event(client, api, pid, {"type": "start_extract"})
            state = res["state"]
        print_phase(state)

        # 6) DAV loop
        print("\n💬 DAV_FLOW loop...")
        with timer("DAV loop total"):
            for turn in range(1, args.max_turns + 1):
                t_turn = time.perf_counter()

                res = await post_event(client, api, pid, {"type": "noop"})
                state = res["state"]
                ui_out = pretty_ui_out(state)
                t = ui_out.get("type")

                print(f"⏱️  TURN {turn}: {time.perf_counter() - t_turn:.2f}s | ui_out={t}")
                print_phase(state)

                if t == "dav_ready":
                    print("✅ dav_ready:", ui_out.get("message"))
                    break

                if t == "request_upload":
                    print("📎 request_upload:", ui_out.get("message"))
                    break

                if t == "dav_question":
                    print_dav_question(ui_out)

                    if args.auto:
                        answer = auto_answer_for_fields(ui_out.get("fields") or [])
                        print(f"\n🧑 (auto) {answer}")
                    else:
                        answer = input("\n🧑 Responde (ex: '61=AB-12-CD; 67=2026-02-05'): ").strip() or "não sei"

                    await post_event(client, api, pid, {"type": "dav_user_message", "data": {"message": answer}})
                    continue

                if t == "info":
                    print("ℹ️", ui_out.get("message"))
                    continue

                if t == "error":
                    print("❌", ui_out.get("message"))
                    break

                print("⚠️ ui_out inesperado:", json.dumps(ui_out, indent=2, ensure_ascii=False))

        # 7) Estado final
        with timer("GET estado final"):
            final_state = await get_state(client, api, pid)
        print("\n" + "=" * 90)
        print("📦 Resumo final:")
        print_phase(final_state)

        docs_map = final_state.get("docs") or {}
        if docs_map:
            print("\n📄 Docs classificados:")
            for k, v in docs_map.items():
                print(f"  - {k}: {v.get('category')} ({len(v.get('pages') or [])} pages)")

    print(f"\n⏱️  TOTAL runtime: {time.perf_counter() - t_total:.2f}s")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
