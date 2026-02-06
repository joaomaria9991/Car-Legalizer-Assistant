# app/graph/dav_graph.py
from __future__ import annotations

from typing import Literal
import json

from langgraph.graph import StateGraph, END

from app.models.state import ProcessState
from app.storage.blob_client import BlobClient

from app.graph.graph_utils import (
    extract_all_pages_parallel,
    harmonize_all_data,
    find_doc_by_category,
)

from app.graph.dav_flow_utils import (
    find_missing_fields,
    pick_questions,
    llm_route_intent,
)

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

async def node_intake_docs(state: ProcessState) -> dict:
    event = get_event(state)
    if event.get("type") != "classify_docs":
        return state.model_dump()

    blob_client = BlobClient()
    blob_prefix = f"processes/{state.process_id}/docs/"
    all_blobs = await blob_client.list_blobs(blob_prefix)

    pdf_groups = group_blobs_by_doc(all_blobs)

    # Opcional: idempotência total
    # state.docs = {}

    for doc_name, pages in pdf_groups.items():
        first_page_blob = pages[0]["name"]
        result = await classify_first_page(blob_client=blob_client, page_blob_name=first_page_blob)

        doc_type = result.get("category", "OUTRO")
        state.docs[doc_name] = {
            "category": doc_type,
            "pages": [p["name"] for p in pages],
            "filename": doc_name,
            "confidence": result.get("confidence", 0.5),
            "status": "classified",
        }

    state.historico.append(f"🤖 Classificou {len(pdf_groups)} documentos")
    await blob_client.save_state(state.process_id, state.model_dump())
    return state.model_dump()


async def node_extract_validate(state: ProcessState) -> dict:
    event = get_event(state)
    if event.get("type") != "start_extract":
        return state.model_dump()

    ensure_flags(state)
    raw_insights = state.flags.get("raw_page_insights")

    if not raw_insights:
        raw_insights = await extract_all_pages_parallel(state)
        state.flags["raw_page_insights"] = raw_insights
        state.historico.append(f"✅ Fase 1: {len(raw_insights)} páginas processadas em paralelo")

    dados_carro = await harmonize_all_data(raw_insights)
    state.dados_carro = dados_carro
    state.fase_atual = "DAV_FLOW"
    state.historico.append("✅ Fase 2: dados_carro harmonizado de todas as páginas")
    return state.model_dump()


async def _dav_ask_missing_fields(state: ProcessState) -> dict:
    missing = find_missing_fields(state.dados_carro or {})
    if not missing:
        clear_flag(state, "dav_pending_fields")
        set_ui(state, {"type": "dav_ready", "message": "✅ DAV completa. Queres gerar o draft?"})
        return state.model_dump()

    ask_fields = pick_questions(missing, max_q=10)
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
    return state.model_dump()


async def node_dav_flow(state: ProcessState) -> dict:
    ensure_flags(state)
    event = get_event(state)

    state.fase_atual = "DAV_FLOW"
    state.sub_fase = getattr(state, "sub_fase", None) or "DAV_CHAT"

    # 1) Não é resposta do user -> pergunta missing
    if event.get("type") != "dav_user_message":
        return await _dav_ask_missing_fields(state)

    # 2) É resposta do user -> route intent
    user_msg = ((event.get("data") or {}).get("message") or "").strip()

    route = await llm_route_intent(user_msg)
    intent = (route.get("intent") or "answer_fields").strip()

    if intent == "upload_more_docs":
        state.fase_atual = "INTAKE_DOCS"
        state.sub_fase = "AGUARDAR_UPLOAD"
        clear_flag(state, "raw_page_insights")
        clear_flag(state, "dav_pending_fields")
        set_ui(state, {"type": "request_upload", "message": "📎 Ok — faz upload do novo documento. Depois eu volto a classificar e extrair mantendo o progresso."})
        state.historico.append("📎 LLM intent=upload_more_docs → reset para INTAKE_DOCS")
        return state.model_dump()

    if intent == "export_state":
        blob_client = BlobClient()
        await blob_client.save_state(state.process_id, state.model_dump())
        set_ui(state, {"type": "info", "message": "✅ Estado guardado no Blob."})
        state.historico.append("💾 LLM intent=export_state → save_state")
        return state.model_dump()

    if intent == "generate_dav_draft":
        state.flags["last_event"] = {"type": "generate_dav_draft"}
        set_ui(state, {"type": "info", "message": "🧾 A gerar draft da DAV..."})
        state.historico.append("🧾 LLM intent=generate_dav_draft")
        return state.model_dump()

    # 3) Default: answer_fields
    pending = state.flags.get("dav_pending_fields") or []
    if not pending:
        state.flags["last_event"] = {"type": "noop"}
        return await _dav_ask_missing_fields(state)

    final_text, applied = await dav_run_tool_calling_turn(
        state=state,
        pending_fields=pending,
        user_msg=user_msg,
    )

    clear_flag(state, "dav_pending_fields")

    missing = find_missing_fields(state.dados_carro or {})
    if not missing:
        set_ui(state, {"type": "dav_ready", "message": "✅ Top! DAV completa.", "assistant_message": final_text, "applied": applied})
        return state.model_dump()

    ask_fields = pick_questions(missing, max_q=120)  # mantido
    state.flags["dav_pending_fields"] = ask_fields
    set_ui(state, {"type": "dav_question", "message": "Perfeito. Faltam estes:", "fields": ask_fields, "assistant_message": final_text, "applied": applied})
    state.historico.append("💬 dav_user_message processado (tool-calling manual)")
    return state.model_dump()


def node_dav_draft_ready(state: ProcessState) -> ProcessState:
    event = get_event(state)
    state_dict = state.model_dump()
    state_dict = handle_dav_draft_generation(state_dict, event)
    return ProcessState(**state_dict)


# =========================
# ROUTER + EDGES + BUILD_GRAPH
# =========================

def router_node(state: ProcessState) -> ProcessState:
    return state


def entry_router(state: ProcessState) -> Literal[
    "INTAKE_DOCS", "EXTRACT_VALIDATE", "DAV_FLOW", "DAV_DRAFT_READY"
]:
    event = (state.flags or {}).get("last_event") or {}

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
    if state.fase_atual == "DAV_FLOW":
        return "DAV_FLOW"
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
