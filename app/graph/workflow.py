# app/graph/dav_graph.py
from __future__ import annotations

from typing import Literal
import json
import asyncio
import os
import time
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END

from app.models.state import ProcessState
from app.storage.blob_client import BlobClient

from app.graph.graph_utils import (
    count_extract_pages,
    extract_all_pages_parallel,
    harmonize_all_data,
    find_doc_by_category,
    iter_extract_pages,
)

from app.graph.dav_flow_utils import (
    pick_questions,
    llm_route_intent,
)
from app.graph.dav_autofill import apply_dav_autofill
from app.graph.dav_decisions import apply_dav_decision_answer, build_dav_decisions
from app.graph.dav_metadata import (
    record_induced_changes,
    refresh_dav_field_metadata,
    review_field_keys,
)
from app.graph.progress import add_progress, finish_progress, start_progress

from app.graph.graph_helpers import (
    # state helpers
    get_event,
    ensure_flags,
    set_ui,
    clear_flag,
    # prompts / llm helpers
    llm_json,
    MODEL_TEXT,
    DAV_EXPLAIN_FIELDS_SYSTEM_PROMPT,
    # intake helpers
    group_blobs_by_doc,
    classify_first_page,
    # dav helpers
    dav_run_tool_calling_turn,
)


# =========================
# NODES
# =========================

EXTRACT_JOB_FLAG = "extract_job"
EXTRACT_PROGRESS_SAVE_EVERY = int(os.getenv("EXTRACT_PROGRESS_SAVE_EVERY", "2"))
EXTRACT_PROGRESS_SAVE_INTERVAL = float(os.getenv("EXTRACT_PROGRESS_SAVE_INTERVAL", "1.5"))
EXTRACT_STALE_AFTER_SECONDS = int(os.getenv("EXTRACT_STALE_AFTER_SECONDS", "180"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_job_is_running(state: ProcessState) -> bool:
    job = (state.flags or {}).get(EXTRACT_JOB_FLAG) or {}
    return isinstance(job, dict) and job.get("status") == "running"


def latest_extract_progress_ts(state: ProcessState) -> str | None:
    entries = (state.flags or {}).get("agent_progress") or []
    for entry in reversed(entries):
        if isinstance(entry, dict) and entry.get("stage") == "extract":
            ts = entry.get("ts")
            return str(ts) if ts else None
    return None


def extract_job_is_stale(state: ProcessState, live_job_running: bool = False) -> bool:
    if live_job_running or not extract_job_is_running(state):
        return False

    job = (state.flags or {}).get(EXTRACT_JOB_FLAG) or {}
    ts = latest_extract_progress_ts(state) or job.get("started_at")
    if not ts:
        return True

    try:
        last_progress = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last_progress).total_seconds() >= EXTRACT_STALE_AFTER_SECONDS


def mark_extract_job_stale(state: ProcessState) -> None:
    ensure_flags(state)
    job = state.flags.get(EXTRACT_JOB_FLAG)
    if not isinstance(job, dict):
        return
    job["status"] = "stale"
    job["stale"] = True
    job["last_progress_at"] = latest_extract_progress_ts(state)
    job["error"] = "Extraction appears stalled and can be resumed."
    add_progress(
        state,
        "extract",
        "warning",
        "Extraction appears stalled and can be resumed",
        {"pages_done": job.get("pages_done"), "pages_total": job.get("pages_total")},
    )


def prepare_extract_job(state: ProcessState) -> bool:
    ensure_flags(state)
    if extract_job_is_running(state):
        add_progress(
            state,
            "extract",
            "warning",
            "Extract is already running",
            state.flags.get(EXTRACT_JOB_FLAG) if isinstance(state.flags.get(EXTRACT_JOB_FLAG), dict) else None,
        )
        return False

    pages_total = count_extract_pages(state)
    state.fase_atual = "EXTRACT_VALIDATE"
    state.sub_fase = "EXTRACT_RUNNING"
    state.flags[EXTRACT_JOB_FLAG] = {
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": None,
        "error": None,
        "stale": False,
        "last_progress_at": _utc_now(),
        "pages_total": pages_total,
        "pages_done": len(state.flags.get("raw_page_insights") or []),
    }
    start_progress(
        state,
        "extract",
        "Extract job started",
        {"pages_total": pages_total, "pages_done": state.flags[EXTRACT_JOB_FLAG]["pages_done"]},
    )
    return True


async def run_extract_pipeline(state: ProcessState, blob_client: BlobClient) -> ProcessState:
    ensure_flags(state)
    job = state.flags.setdefault(EXTRACT_JOB_FLAG, {})
    if not isinstance(job, dict):
        job = {}
        state.flags[EXTRACT_JOB_FLAG] = job

    job.update({
        "status": "running",
        "started_at": job.get("started_at") or _utc_now(),
        "finished_at": None,
        "error": None,
        "stale": False,
        "pages_total": count_extract_pages(state),
        "pages_done": len(state.flags.get("raw_page_insights") or []),
    })
    state.fase_atual = "EXTRACT_VALIDATE"
    state.sub_fase = "EXTRACT_RUNNING"

    try:
        expected_pages = iter_extract_pages(state)
        raw_insights = state.flags.get("raw_page_insights")
        if not isinstance(raw_insights, list):
            raw_insights = []
            state.flags["raw_page_insights"] = raw_insights

        seen_page_blobs = {
            insight.get("page_blob")
            for insight in raw_insights
            if isinstance(insight, dict) and insight.get("page_blob")
        }
        missing_page_specs = [
            spec for spec in expected_pages
            if spec[0] not in seen_page_blobs
        ]
        job["pages_total"] = len(expected_pages)
        job["pages_done"] = len(raw_insights)

        if missing_page_specs:
            start_progress(
                state,
                "extract",
                "Extracting structured data from document pages",
                {
                    "pages_total": job["pages_total"],
                    "pages_done": len(raw_insights),
                    "pages_missing": len(missing_page_specs),
                },
            )
            await blob_client.save_state(state.process_id, state.model_dump())

            last_save = {"pages_done": len(raw_insights), "ts": time.monotonic()}

            async def on_page_result(insight: dict) -> None:
                state.flags.setdefault("raw_page_insights", []).append(insight)
                pages_done = len(state.flags.get("raw_page_insights") or [])
                job["pages_done"] = pages_done
                job["last_progress_at"] = _utc_now()
                add_progress(
                    state,
                    "extract",
                    "done",
                    f"Extracted {insight.get('page_blob') or insight.get('doc_id') or 'page'}",
                    {
                        "doc_id": insight.get("doc_id"),
                        "category": insight.get("category"),
                        "page_blob": insight.get("page_blob"),
                        "pages_done": pages_done,
                        "pages_total": job.get("pages_total", 0),
                    },
                )

                enough_pages = pages_done - last_save["pages_done"] >= EXTRACT_PROGRESS_SAVE_EVERY
                enough_time = time.monotonic() - last_save["ts"] >= EXTRACT_PROGRESS_SAVE_INTERVAL
                if enough_pages or enough_time or pages_done == job.get("pages_total"):
                    await blob_client.save_state(state.process_id, state.model_dump())
                    last_save["pages_done"] = pages_done
                    last_save["ts"] = time.monotonic()

            new_insights = await extract_all_pages_parallel(
                state,
                on_page_result=on_page_result,
                page_specs=missing_page_specs,
            )
            raw_insights = state.flags.get("raw_page_insights") or []
            job["pages_done"] = len(raw_insights)
            if len(new_insights) < len(missing_page_specs):
                job.update({
                    "status": "warning",
                    "finished_at": _utc_now(),
                    "error": f"Extracted {len(new_insights)} of {len(missing_page_specs)} missing page(s)",
                    "pages_done": len(raw_insights),
                })
                add_progress(
                    state,
                    "extract",
                    "warning",
                    job["error"],
                    {"pages_done": len(raw_insights), "pages_total": job.get("pages_total", 0)},
                )
                await blob_client.save_state(state.process_id, state.model_dump())
                return state
            finish_progress(
                state,
                "extract",
                f"Finished extraction for {len(raw_insights)} page(s)",
                {"pages": len(raw_insights)},
                status="done" if raw_insights else "warning",
            )
            state.historico.append(f"Fase 1: {len(raw_insights)} paginas processadas em paralelo")
            await blob_client.save_state(state.process_id, state.model_dump())
        else:
            job["pages_done"] = len(raw_insights)
            job["last_progress_at"] = latest_extract_progress_ts(state) or _utc_now()
            add_progress(
                state,
                "extract",
                "done",
                f"Using cached extraction for {len(raw_insights)} page(s)",
                {"pages": len(raw_insights)},
            )
            await blob_client.save_state(state.process_id, state.model_dump())

        start_progress(
            state,
            "harmonize",
            "Harmonizing extracted page data into DAV fields",
            {"pages": len(raw_insights or [])},
        )
        await blob_client.save_state(state.process_id, state.model_dump())
        dados_carro = await harmonize_all_data(raw_insights or [])
        state.dados_carro = dados_carro
        refresh_dav_field_metadata(state, raw_insights=raw_insights or [])
        finish_progress(
            state,
            "harmonize",
            "Harmonized extracted data into the DAV mirror",
            {"fields": len(dados_carro or {})},
        )
        await blob_client.save_state(state.process_id, state.model_dump())

        _apply_dav_autofill_to_state(state)
        state.fase_atual = "DAV_FLOW"
        state.sub_fase = "DAV_CHAT"
        set_ui(state, {
            "type": "info",
            "message": "Extraction finished. Open Review or ask for missing fields to continue DAV validation.",
        })
        finish_progress(state, "complete", "DAV review is ready")
        state.historico.append("Fase 2: dados_carro harmonizado de todas as paginas")
        job.update({
            "status": "done",
            "finished_at": _utc_now(),
            "error": None,
            "stale": False,
            "last_progress_at": _utc_now(),
            "pages_done": len(raw_insights or []),
        })
        await blob_client.save_state(state.process_id, state.model_dump())
        return state
    except Exception as exc:
        job.update({
            "status": "error",
            "finished_at": _utc_now(),
            "error": str(exc),
            "pages_done": len(state.flags.get("raw_page_insights") or []),
        })
        add_progress(
            state,
            "error",
            "error",
            f"Extraction pipeline failed: {exc}",
        )
        await blob_client.save_state(state.process_id, state.model_dump())
        raise

def _apply_dav_autofill_to_state(state: ProcessState) -> list[dict]:
    refresh_dav_field_metadata(
        state,
        raw_insights=(state.flags or {}).get("raw_page_insights") or [],
    )
    changes = apply_dav_autofill(
        state.dados_carro or {},
        raw_insights=(state.flags or {}).get("raw_page_insights") or [],
    )
    if changes:
        ensure_flags(state)
        record_induced_changes(state, changes)
        finish_progress(
            state,
            "autofill",
            f"Autofilled {len(changes)} DAV field(s)",
            {
                "count": len(changes),
                "fields": [change.get("field") for change in changes if change.get("field")],
            },
        )
        refresh_dav_field_metadata(
            state,
            raw_insights=(state.flags or {}).get("raw_page_insights") or [],
        )
        state.historico.append(f"✅ Auto-preencheu {len(changes)} campos DAV por equivalências/extração")
    return changes

async def node_intake_docs(state: ProcessState) -> dict:
    event = get_event(state)
    if event.get("type") != "classify_docs":
        return state.model_dump()

    blob_client = BlobClient()
    blob_prefix = f"processes/{state.process_id}/docs/"
    all_blobs = await blob_client.list_blobs(blob_prefix)

    pdf_groups = group_blobs_by_doc(all_blobs)
    start_progress(
        state,
        "classify",
        f"Classifying {len(pdf_groups)} document group(s)",
        {"documents": len(pdf_groups)},
    )
    await blob_client.save_state(state.process_id, state.model_dump())

    if not pdf_groups:
        finish_progress(
            state,
            "classify",
            "No uploaded documents found to classify",
            {"documents": 0},
            status="warning",
        )
        await blob_client.save_state(state.process_id, state.model_dump())
        return state.model_dump()

    # 🔧 controla concorrência (ajusta: 4/6/8)
    sem = asyncio.Semaphore(6)

    async def classify_one(doc_name: str, pages: list[dict]) -> tuple[str, dict]:
        # escolhe 1ª página que seja imagem
        first_page_blob = None
        for p in pages:
            n = p["name"].lower()
            if n.endswith(".jpg") or n.endswith(".jpeg") or n.endswith(".png") or n.endswith(".webp"):
                first_page_blob = p["name"]
                break

        if not first_page_blob:
            # devolve como OUTRO e segue (ou levanta erro — escolha tua)
            return doc_name, {
                "category": "OUTRO",
                "pages": [p["name"] for p in pages],
                "filename": doc_name,
                "confidence": 0.0,
                "status": "no_image_pages",
            }

        async with sem:
            result = await classify_first_page(blob_client=blob_client, page_blob_name=first_page_blob)

        doc_type = result.get("category", "OUTRO")
        return doc_name, {
            "category": doc_type,
            "pages": [p["name"] for p in pages],
            "filename": doc_name,
            "confidence": result.get("confidence", 0.5),
            "status": "classified",
        }

    # dispara tudo em paralelo (controlado pelo semaphore)
    tasks = [asyncio.create_task(classify_one(doc_name, pages)) for doc_name, pages in pdf_groups.items()]
    results = []
    for task in asyncio.as_completed(tasks):
        doc_name, doc_info = await task
        results.append((doc_name, doc_info))
        state.docs[doc_name] = doc_info
        add_progress(
            state,
            "classify",
            "warning" if doc_info.get("status") == "no_image_pages" else "done",
            f"Classified {doc_name} as {doc_info.get('category', 'OUTRO')}",
            {
                "filename": doc_name,
                "category": doc_info.get("category"),
                "confidence": doc_info.get("confidence"),
                "status": doc_info.get("status"),
            },
        )
        await blob_client.save_state(state.process_id, state.model_dump())

    # escreve no state no fim (evita confusões)
    for doc_name, doc_info in results:
        state.docs[doc_name] = doc_info

    state.historico.append(f"🤖 Classificou {len(pdf_groups)} documentos (paralelo)")
    state.fase_atual = "EXTRACT_VALIDATE"
    finish_progress(
        state,
        "classify",
        f"Finished classifying {len(results)} document group(s)",
        {"documents": len(results)},
    )
    await blob_client.save_state(state.process_id, state.model_dump())
    return state.model_dump()


async def node_extract_validate(state: ProcessState) -> dict:
    event = get_event(state)
    if event.get("type") != "start_extract":
        return state.model_dump()

    if not prepare_extract_job(state):
        return state.model_dump()

    await run_extract_pipeline(state, BlobClient())
    return state.model_dump()


async def _dav_ask_missing_fields(state: ProcessState) -> dict:
    _apply_dav_autofill_to_state(state)
    refresh_dav_field_metadata(
        state,
        raw_insights=(state.flags or {}).get("raw_page_insights") or [],
    )
    decisions = build_dav_decisions(state)
    if decisions:
        clear_flag(state, "dav_pending_fields")
        ensure_flags(state)
        state.flags["dav_pending_decisions"] = decisions
        set_ui(state, {
            "type": "dav_decision",
            "message": "Vamos resolver primeiro as decisões que desbloqueiam mais campos.",
            "decisions": decisions,
        })
        finish_progress(
            state,
            "dav_chat",
            f"Prepared {len(decisions)} DAV decision card(s)",
            {"decisions": len(decisions), "fields": [decision.get("field") for decision in decisions]},
            status="warning",
        )
        return state.model_dump()

    clear_flag(state, "dav_pending_decisions")
    missing = review_field_keys(state)
    if not missing:
        clear_flag(state, "dav_pending_fields")
        finish_progress(
            state,
            "dav_chat",
            "DAV review has no missing or risky fields",
            {"review_fields": 0},
        )
        set_ui(state, {"type": "dav_ready", "message": "✅ DAV completa. Queres gerar o draft?"})
        return state.model_dump()

    ask_fields = pick_questions(
        missing,
        max_q=10,
        field_meta=(state.flags or {}).get("dav_field_meta") or {},
    )
    ensure_flags(state)
    state.flags["dav_pending_fields"] = ask_fields

    subset = {k: (state.dados_carro or {}).get(k) for k in ask_fields}

    llm_out = llm_json(
        model=MODEL_TEXT,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": DAV_EXPLAIN_FIELDS_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"PENDING_FIELDS:\n{json.dumps(ask_fields, ensure_ascii=False)}\n\n"
                f"ESTADO_SUBSET:\n{json.dumps(subset, ensure_ascii=False)}"
            )},
        ],
    )

    set_ui(state, {
        "type": "dav_question",
        "message": llm_out.get("message") or "Preciso de confirmar/preencher estes campos:",
        "fields": llm_out.get("fields") or ask_fields,
    })
    finish_progress(
        state,
        "dav_chat",
        f"Prepared {len(ask_fields)} DAV review question(s)",
        {"review_fields": len(ask_fields), "fields": ask_fields},
        status="warning",
    )
    return state.model_dump()


async def node_dav_flow(state: ProcessState) -> dict:
    ensure_flags(state)
    event = get_event(state)
    blob_client = BlobClient()

    state.fase_atual = "DAV_FLOW"
    state.sub_fase = getattr(state, "sub_fase", None) or "DAV_CHAT"

    # 1) Não é resposta do user -> pergunta missing
    if event.get("type") == "dav_decision_answer":
        start_progress(state, "dav_chat", "Applying DAV decision answer")
        applied = apply_dav_decision_answer(state, event.get("data") or {})
        _apply_dav_autofill_to_state(state)
        refresh_dav_field_metadata(
            state,
            raw_insights=(state.flags or {}).get("raw_page_insights") or [],
        )
        result = await _dav_ask_missing_fields(state)
        ui_out = state.flags.get("ui_out") or {}
        ui_out["assistant_message"] = "Decisão aplicada. Recalculei os campos em falta e bloqueados."
        ui_out["applied"] = applied
        state.flags["ui_out"] = ui_out
        finish_progress(
            state,
            "dav_chat",
            f"Applied {len(applied)} DAV decision update(s)",
            {"applied": len(applied)},
            status="done",
        )
        await blob_client.save_state(state.process_id, state.model_dump())
        return state.model_dump()

    if event.get("type") != "dav_user_message":
        if event.get("type") == "noop":
            start_progress(state, "dav_chat", "Checking DAV fields that need review")
            await blob_client.save_state(state.process_id, state.model_dump())
        result = await _dav_ask_missing_fields(state)
        await blob_client.save_state(state.process_id, state.model_dump())
        return result

    # 2) É resposta do user -> route intent
    user_msg = ((event.get("data") or {}).get("message") or "").strip()
    start_progress(state, "dav_chat", "Processing user DAV answer")
    await blob_client.save_state(state.process_id, state.model_dump())

    route = await llm_route_intent(user_msg)
    intent = (route.get("intent") or "answer_fields").strip()

    if intent == "upload_more_docs":
        state.fase_atual = "INTAKE_DOCS"
        state.sub_fase = "AGUARDAR_UPLOAD"
        clear_flag(state, "raw_page_insights")
        clear_flag(state, "dav_pending_fields")
        finish_progress(state, "dav_chat", "User asked to upload more documents")
        set_ui(state, {"type": "request_upload", "message": "📎 Ok — faz upload do novo documento. Depois eu volto a classificar e extrair mantendo o progresso."})
        state.historico.append("📎 LLM intent=upload_more_docs → reset para INTAKE_DOCS")
        return state.model_dump()

    if intent == "export_state":
        finish_progress(state, "dav_chat", "User asked to save the current process state")
        await blob_client.save_state(state.process_id, state.model_dump())
        set_ui(state, {"type": "info", "message": "✅ Estado guardado no Blob."})
        state.historico.append("💾 LLM intent=export_state → save_state")
        return state.model_dump()

    if intent == "generate_dav_draft":
        state.flags["last_event"] = {"type": "generate_dav_draft"}
        finish_progress(state, "dav_chat", "User asked to generate the DAV draft")
        set_ui(state, {"type": "info", "message": "🧾 A gerar draft da DAV..."})
        state.historico.append("🧾 LLM intent=generate_dav_draft")
        return state.model_dump()

    # 3) Default: answer_fields
    pending = state.flags.get("dav_pending_fields") or []
    if not pending:
        state.flags["last_event"] = {"type": "noop"}
        result = await _dav_ask_missing_fields(state)
        await blob_client.save_state(state.process_id, state.model_dump())
        return result

    final_text, applied = await dav_run_tool_calling_turn(
        state=state,
        pending_fields=pending,
        user_msg=user_msg,
    )
    _apply_dav_autofill_to_state(state)
    refresh_dav_field_metadata(
        state,
        raw_insights=(state.flags or {}).get("raw_page_insights") or [],
    )

    clear_flag(state, "dav_pending_fields")

    missing = review_field_keys(state)
    if not missing:
        finish_progress(
            state,
            "dav_chat",
            "Applied user answer and completed DAV review",
            {"applied": len(applied)},
        )
        set_ui(state, {"type": "dav_ready", "message": "✅ Top! DAV completa.", "assistant_message": final_text, "applied": applied})
        return state.model_dump()

    ask_fields = pick_questions(
        missing,
        max_q=120,
        field_meta=(state.flags or {}).get("dav_field_meta") or {},
    )  # mantido
    state.flags["dav_pending_fields"] = ask_fields
    finish_progress(
        state,
        "dav_chat",
        f"Applied user answer; {len(ask_fields)} field(s) still need review",
        {"applied": len(applied), "review_fields": len(ask_fields), "fields": ask_fields},
        status="warning",
    )
    set_ui(state, {"type": "dav_question", "message": "Perfeito. Faltam estes:", "fields": ask_fields, "assistant_message": final_text, "applied": applied})
    state.historico.append("💬 dav_user_message processado (tool-calling manual)")
    return state.model_dump()


def node_dav_draft_ready(state: ProcessState) -> ProcessState:
    return ProcessState(state.model_dump())  # placeholder para possível lógica futura


# =========================
# ROUTER + EDGES + BUILD_GRAPH
# =========================

def router_node(state: ProcessState) -> ProcessState:
    return state


def entry_router(state: ProcessState) -> Literal[
    "INTAKE_DOCS", "EXTRACT_VALIDATE", "DAV_FLOW", "DAV_DRAFT_READY"
]:
    event = (state.flags or {}).get("last_event") or {}

    if event.get("type") == "start_extract":
        state.fase_atual = "EXTRACT_VALIDATE"
        return "EXTRACT_VALIDATE"

    if event.get("type") in {"noop", "dav_user_message", "dav_decision_answer"} and state.dados_carro:
        state.fase_atual = "DAV_FLOW"
        state.sub_fase = "DAV_CHAT"
        return "DAV_FLOW"

    if event.get("type") == "ui":
        intent = (event.get("payload") or {}).get("intent")
        if intent in ("upload_more_docs", "reset_to_intake"):
            state.fase_atual = "INTAKE_DOCS"
            state.sub_fase = "AGUARDAR_UPLOAD"
            if state.flags:
                state.flags.pop("raw_page_insights", None)
            state.dados_carro = state.dados_carro or {}
            state.dav_draft = None if hasattr(state, "dav_draft") else None
            return "INTAKE_DOCS"

    fase = state.fase_atual
    if fase == "INTAKE_DOCS":
        return "INTAKE_DOCS"
    if fase == "EXTRACT_VALIDATE":
        return "EXTRACT_VALIDATE"
    if fase == "DAV_FLOW":
        if getattr(state, "sub_fase", None) == "DAV_DRAFT_READY":
            return "DAV_DRAFT_READY"
        return "DAV_FLOW"
    if fase == "DAV_DRAFT_READY":
        return "DAV_DRAFT_READY"

    return "INTAKE_DOCS"


def next_after_intake(state: ProcessState):
    has_invoice = find_doc_by_category(state, "FATURA_PROFORMA") or find_doc_by_category(state, "FATURA_COMPRA")
    has_cmr = find_doc_by_category(state, "DOCUMENTO_TRANSPORTE_CMR")
    if has_invoice and has_cmr:
        state.fase_atual = "EXTRACT_VALIDATE"
        return "EXTRACT_VALIDATE"
    return END


def next_after_extract_validate(state: ProcessState):
    # Extraction/harmonization can be slow. Finish the request here so the
    # frontend can show completion immediately; DAV chat runs on explicit noop
    # or dav_user_message events.
    return END


def next_after_dav_flow(state: ProcessState):
    if state.fase_atual == "INTAKE_DOCS":
        return "INTAKE_DOCS"

    event = (state.flags or {}).get("last_event") or {}
    if event.get("type") == "generate_dav_draft":
        state.sub_fase = "DAV_DRAFT_READY"
        return "DAV_DRAFT_READY"

    return END


def next_after_dav_draft_ready(state: ProcessState):
    state.fase_atual = "DAV_DRAFT_READY"
    return END


def build_graph():
    g = StateGraph(ProcessState)

    g.add_node("router", router_node)
    g.add_node("INTAKE_DOCS", node_intake_docs)
    g.add_node("EXTRACT_VALIDATE", node_extract_validate)
    g.add_node("DAV_FLOW", node_dav_flow)
    g.add_node("DAV_DRAFT_READY", node_dav_draft_ready)

    g.set_entry_point("router")

    g.add_conditional_edges(
        "router",
        entry_router,
        {
            "INTAKE_DOCS": "INTAKE_DOCS",
            "EXTRACT_VALIDATE": "EXTRACT_VALIDATE",
            "DAV_FLOW": "DAV_FLOW",
            "DAV_DRAFT_READY": "DAV_DRAFT_READY",
        },
    )

    g.add_conditional_edges(
        "INTAKE_DOCS",
        next_after_intake,
        {"EXTRACT_VALIDATE": "EXTRACT_VALIDATE", END: END},
    )

    g.add_conditional_edges(
        "EXTRACT_VALIDATE",
        next_after_extract_validate,
        {"DAV_FLOW": "DAV_FLOW", END: END},
    )

    g.add_conditional_edges(
        "DAV_FLOW",
        next_after_dav_flow,
        {"INTAKE_DOCS": "INTAKE_DOCS", "DAV_DRAFT_READY": "DAV_DRAFT_READY", END: END},
    )

    g.add_conditional_edges(
        "DAV_DRAFT_READY",
        next_after_dav_draft_ready,
        {END: END},
    )

    return g.compile()
