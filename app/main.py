# app/main.py

import os
import json
import asyncio
from datetime import datetime
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from dotenv import load_dotenv

from app.storage.blob_client import BlobClient  
from app.auth import (
    authenticate_request,
    auth_required,
    get_current_user,
    public_process_id,
    reset_current_user,
    scope_blob_path,
    set_current_user,
    user_processes_prefix,
)
from app.models.events import SimpleResponse
from app.models.state import ProcessState
from app.graph.progress import add_progress
from app.graph.dav_metadata import apply_dav_applicability, refresh_dav_field_metadata
from app.graph.workflow import (
    build_graph,
    extract_job_is_running,
    extract_job_is_stale,
    mark_extract_job_stale,
    prepare_extract_job,
    run_extract_pipeline,
)


# mais tarde: from app.graph.nodes import process_event

load_dotenv()

app = FastAPI(title="Car Legalização API", version="0.1.0")

def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# In production set CORS_ORIGINS to the Static Web Apps URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_context_middleware(request: Request, call_next):
    try:
        user = await authenticate_request(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    token = set_current_user(user)
    try:
        return await call_next(request)
    finally:
        reset_current_user(token)

blob_client = BlobClient()
graph = build_graph()
running_extract_jobs: set[str] = set()


def _is_empty_dav_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def summarize_process_state(state: dict[str, Any], last_modified: Any = None) -> dict[str, Any]:
    process_id = str(state.get("process_id") or "")
    docs = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    dados_carro = state.get("dados_carro") if isinstance(state.get("dados_carro"), dict) else {}
    flags = state.get("flags") if isinstance(state.get("flags"), dict) else {}
    meta = flags.get("dav_field_meta") if isinstance(flags.get("dav_field_meta"), dict) else {}

    total_fields = len(dados_carro)
    filled_fields = sum(1 for value in dados_carro.values() if not _is_empty_dav_value(value))
    not_applicable_fields = sum(
        1
        for field, entry in meta.items()
        if field in dados_carro and isinstance(entry, dict) and entry.get("status") == "not_applicable"
    )
    missing_fields = sum(
        1
        for field, value in dados_carro.items()
        if _is_empty_dav_value(value)
        and not (isinstance(meta.get(field), dict) and meta[field].get("status") == "not_applicable")
    )
    conflict_fields = sum(
        1
        for entry in meta.values()
        if isinstance(entry, dict) and entry.get("status") == "conflict"
    )

    if isinstance(last_modified, datetime):
        last_modified_value = last_modified.isoformat()
    elif last_modified is None:
        last_modified_value = None
    else:
        last_modified_value = str(last_modified)

    return {
        "process_id": process_id,
        "fase_atual": state.get("fase_atual") or "INTAKE_DOCS",
        "sub_fase": state.get("sub_fase"),
        "last_modified": last_modified_value,
        "docs_count": len(docs),
        "filled_fields": filled_fields,
        "total_fields": total_fields,
        "missing_fields": missing_fields,
        "conflict_fields": conflict_fields,
        "not_applicable_fields": not_applicable_fields,
    }


async def run_extract_background(process_id: str, user=None) -> None:
    token = set_current_user(user)
    try:
        state_dict = await blob_client.get_state(process_id)
        state_dict.setdefault("process_id", process_id)
        state = ProcessState(**state_dict)
        await run_extract_pipeline(state, blob_client)
    finally:
        reset_current_user(token)
        running_extract_jobs.discard(process_id)


async def get_state_with_stale_marker(process_id: str) -> dict[str, Any]:
    state_dict = await blob_client.get_state(process_id)
    state_dict.setdefault("process_id", process_id)
    state = ProcessState(**state_dict)
    changed = False
    if extract_job_is_stale(state, live_job_running=process_id in running_extract_jobs):
        mark_extract_job_stale(state)
        changed = True

    if state.dados_carro:
        before_dav_state = state.model_dump()
        refresh_dav_field_metadata(
            state,
            raw_insights=(state.flags or {}).get("raw_page_insights") or [],
        )
        apply_dav_applicability(state)
        changed = changed or state.model_dump() != before_dav_state

    if changed:
        if hasattr(blob_client, "save_state"):
            await blob_client.save_state(process_id, state.model_dump())
        return state.model_dump()
    return state_dict


def summarize_documents(state: dict[str, Any]) -> list[dict[str, Any]]:
    docs = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    documents: list[dict[str, Any]] = []
    for doc_id, info in docs.items():
        if "_page_" in str(doc_id) or not isinstance(info, dict):
            continue
        pages = []
        for index, page_blob in enumerate(info.get("pages") or [], start=1):
            if not page_blob:
                continue
            pages.append({
                "page_number": index,
                "blob_path": str(page_blob),
                "filename": str(page_blob).split("/")[-1],
            })
        documents.append({
            "doc_id": str(doc_id),
            "filename": str(info.get("filename") or doc_id),
            "category": info.get("category") or "OUTRO",
            "status": info.get("status") or "pending",
            "confidence": info.get("confidence"),
            "pages": pages,
        })
    return documents



@app.get("/health", response_model=SimpleResponse)
async def health_check():
    return SimpleResponse(success=True, message="OK")


@app.get("/processes")
async def list_processes():
    """
    Lista processos existentes na Blob a partir de processes/*/state.json.
    """
    blobs = await blob_client.list_blobs(user_processes_prefix(), include_metadata=True)
    state_blobs = []
    for blob in blobs:
        name = blob.get("name")
        if not isinstance(name, str) or not name.startswith("processes/") or not name.endswith("/state.json"):
            continue

        parts = name.split("/")
        if get_current_user():
            if len(parts) != 4 or parts[1] != get_current_user().user_key or not parts[2]:
                continue
            process_id = parts[2]
        else:
            if len(parts) != 3 or not parts[1]:
                continue
            process_id = parts[1]

        if not process_id:
            continue

        state_blobs.append((process_id, blob.get("last_modified")))

    async def load_summary(process_id: str, last_modified: Any) -> dict[str, Any]:
        state = await get_state_with_stale_marker(process_id)
        return summarize_process_state(state, last_modified)

    summaries = await asyncio.gather(
        *(load_summary(process_id, last_modified) for process_id, last_modified in state_blobs)
    )
    summaries.sort(key=lambda item: item.get("last_modified") or "", reverse=True)
    return {"processes": summaries}


@app.get("/processes/{process_id}")
async def get_process_state(process_id: str):
    """
    Devolve o state.json (ou estado inicial se ainda não existir).
    """
    return await get_state_with_stale_marker(process_id)


@app.get("/processes/{process_id}/documents")
async def list_process_documents(process_id: str):
    state = await get_state_with_stale_marker(process_id)
    return {"process_id": process_id, "documents": summarize_documents(state)}


@app.get("/processes/{process_id}/documents/file")
async def get_process_document_file(process_id: str, blob_path: str = Query(...)):
    allowed_prefix = scope_blob_path(f"processes/{process_id}/docs/")
    scoped_blob_path = scope_blob_path(blob_path)
    if not scoped_blob_path.startswith(allowed_prefix) or ".." in scoped_blob_path:
        raise HTTPException(status_code=400, detail="Invalid document path")

    data = await blob_client.get_blob_bytes(scoped_blob_path)
    filename = scoped_blob_path.split("/")[-1] or "document"
    media_type = "image/jpeg"
    lower = filename.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".webp"):
        media_type = "image/webp"
    elif lower.endswith(".pdf"):
        media_type = "application/pdf"

    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )



@app.post("/processes/{process_id}/events")
async def handle_event(
    process_id: str,
    background_tasks: BackgroundTasks,
    event_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    # 1) ler estado atual do Blob
    state_dict = await blob_client.get_state(process_id)

    # 2) validar que tem process_id
    state_dict.setdefault("process_id", process_id)

    state_obj = ProcessState(**state_dict)

    # 3) parse do evento
    try:
        event = json.loads(event_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="event_json inválido")

    # 4) upload de ficheiro se existir
    if file is not None:
        add_progress(
            state_obj,
            "upload",
            "running",
            f"Uploading {file.filename}",
            {"filename": file.filename},
        )
        await blob_client.save_state(process_id, state_obj.model_dump())

        blob_path = scope_blob_path(f"processes/{process_id}/docs/{file.filename}")
        try:
            await blob_client.upload_file(blob_path, file)
            event.setdefault("data", {})
            event["data"]["blob_path"] = blob_path
            event["data"]["filename"] = file.filename
            add_progress(
                state_obj,
                "upload",
                "done",
                f"Uploaded {file.filename}",
                {"filename": file.filename, "blob_path": blob_path},
            )
            await blob_client.save_state(process_id, state_obj.model_dump())
        except Exception:
            add_progress(
                state_obj,
                "upload",
                "error",
                f"Upload failed for {file.filename}",
                {"filename": file.filename},
            )
            await blob_client.save_state(process_id, state_obj.model_dump())
            raise

    # 5) start_extract corre em background para nao bloquear o browser.
    if event.get("type") == "start_extract":
        state_obj.flags = state_obj.flags or {}
        state_obj.flags["last_event"] = event

        if process_id in running_extract_jobs:
            add_progress(
                state_obj,
                "extract",
                "warning",
                "Extract is already running",
                state_obj.flags.get("extract_job") if isinstance(state_obj.flags.get("extract_job"), dict) else None,
            )
        else:
            if extract_job_is_running(state_obj):
                job = state_obj.flags.get("extract_job")
                if isinstance(job, dict):
                    job["status"] = "queued"
                add_progress(
                    state_obj,
                    "extract",
                    "warning",
                    "Restarting stale extract job",
                    job if isinstance(job, dict) else None,
                )

            if prepare_extract_job(state_obj):
                running_extract_jobs.add(process_id)
                background_tasks.add_task(run_extract_background, process_id, get_current_user())

        await blob_client.save_state(process_id, state_obj.model_dump())
        return {
            "success": True,
            "fase_atual": state_obj.fase_atual,
            "sub_fase": state_obj.sub_fase,
            "state": state_obj.model_dump(),
        }

    # 6) eventos globais (advance_phase) continuam aqui se quiseres
    if event.get("type") == "advance_phase":
        data = event.get("data", {})
        state_obj.fase_atual = data.get("nova_fase", state_obj.fase_atual)
        state_obj.sub_fase = data.get("sub_fase", state_obj.sub_fase)
        state_obj.historico.append(f"Fase alterada manualmente para {state_obj.fase_atual}")
        new_state = state_obj
    else:
        # 7) meter evento no state.flags para os nodes lerem
        state_obj.flags = state_obj.flags or {}
        state_obj.flags["last_event"] = event

        # 8) correr o grafo (um passo)
        graph_out = await graph.ainvoke(state_obj)

        # ✅ Normaliza: se vier dict, converte; se vier ProcessState, usa.
        if isinstance(graph_out, ProcessState):
            new_state = graph_out
        elif isinstance(graph_out, dict):
            new_state = ProcessState(**graph_out)
        else:
            raise HTTPException(status_code=500, detail=f"Graph devolveu tipo inesperado: {type(graph_out)}")


    # 9) guardar no Blob
    await blob_client.save_state(process_id, new_state.model_dump())

    return {
        "success": True,
        "fase_atual": new_state.fase_atual,
        "sub_fase": new_state.sub_fase,
        "state": new_state.model_dump(),
    }





if __name__ == "__main__":
    import uvicorn


    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
