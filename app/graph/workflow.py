from typing import Literal
from langgraph.graph import StateGraph, END
from models.state import ProcessState
from handlers.handlers import (
    handle_intake_docs,
    handle_extract_validate,
    handle_dav_collect_fiscal,
    handle_dav_draft_generation,
)

# ----------------- NÓS -----------------
def node_intake_docs(state: ProcessState) -> ProcessState:
    event = state.flags.get("last_event") or {}
    state_dict = state.model_dump()
    state_dict = handle_intake_docs(state_dict, event)
    return ProcessState(**state_dict)

def node_extract_validate(state: ProcessState) -> ProcessState:
    event = state.flags.get("last_event") or {}
    state_dict = state.model_dump()
    state_dict = handle_extract_validate(state_dict, event)
    return ProcessState(**state_dict)

def node_dav_flow(state: ProcessState) -> ProcessState:
    event = state.flags.get("last_event") or {}
    state_dict = state.model_dump()
    state_dict = handle_dav_collect_fiscal(state_dict, event)
    return ProcessState(**state_dict)

def node_dav_draft_ready(state: ProcessState) -> ProcessState:
    event = state.flags.get("last_event") or {}
    state_dict = state.model_dump()
    state_dict = handle_dav_draft_generation(state_dict, event)
    return ProcessState(**state_dict)

# ----------------- NÓ ROUTER INICIAL -----------------
def router_node(state: ProcessState) -> ProcessState:
    """Nó inicial que só roteia para o nó correto, SEM lógica de negócio."""
    fase = state.fase_atual
    if fase == "INTAKE_DOCS":
        return state  # mantém state igual, routing será feito na edge
    if fase == "EXTRACT_VALIDATE":
        return state
    if fase == "DAV_FLOW":
        if state.sub_fase == "DAV_DRAFT_READY":
            return state
        return state
    if fase == "DAV_DRAFT_READY":
        return state
    return state

# ----------------- FUNÇÕES DE TRANSIÇÃO -----------------
def entry_router(state: ProcessState) -> Literal[
    "INTAKE_DOCS", "EXTRACT_VALIDATE", "DAV_FLOW", "DAV_DRAFT_READY"
]:
    fase = state.fase_atual
    if fase == "INTAKE_DOCS":
        return "INTAKE_DOCS"
    if fase == "EXTRACT_VALIDATE":
        return "EXTRACT_VALIDATE"
    if fase == "DAV_FLOW":
        # 👇 MUDANÇA: getattr(state, 'sub_fase') em vez de state.sub_fase
        if getattr(state, 'sub_fase', None) == "DAV_DRAFT_READY":
            return "DAV_DRAFT_READY"
        return "DAV_FLOW"
    if fase == "DAV_DRAFT_READY":
        return "DAV_DRAFT_READY"
    return "INTAKE_DOCS"



def next_after_intake(state: ProcessState):
    # 👇 MUDANÇA: state.docs em vez de state.documentos
    tem_fatura = bool(state.docs.get("fatura"))
    tem_dua = bool(state.docs.get("dua"))
    if tem_fatura and tem_dua:
        state.fase_atual = "EXTRACT_VALIDATE"
        return "EXTRACT_VALIDATE"
    return END

def next_after_extract_validate(state: ProcessState):
    if state.fase_atual == "DAV_FLOW":
        return "DAV_FLOW"
    return END

def next_after_dav_flow(state: ProcessState):
    event = state.flags.get("last_event") or {}
    if event.get("type") == "generate_dav_draft":
        state.sub_fase = "DAV_DRAFT_READY"
        return "DAV_DRAFT_READY"
    return END

def next_after_dav_draft_ready(state: ProcessState):
    state.fase_atual = "DAV_DRAFT_READY"
    return END

# ----------------- BUILD_GRAPH -----------------
def build_graph():
    graph = StateGraph(ProcessState)

    # ADICIONA O NÓ ROUTER
    graph.add_node("router", router_node)
    graph.add_node("INTAKE_DOCS", node_intake_docs)
    graph.add_node("EXTRACT_VALIDATE", node_extract_validate)
    graph.add_node("DAV_FLOW", node_dav_flow)
    graph.add_node("DAV_DRAFT_READY", node_dav_draft_ready)

    # ENTRY POINT: começa sempre no router
    graph.set_entry_point("router")

    # ROUTER -> primeiro nó de negócio
    graph.add_conditional_edges(
        "router",
        entry_router,
        {
            "INTAKE_DOCS": "INTAKE_DOCS",
            "EXTRACT_VALIDATE": "EXTRACT_VALIDATE",
            "DAV_FLOW": "DAV_FLOW",
            "DAV_DRAFT_READY": "DAV_DRAFT_READY",
        },
    )

    # Conditional edges dos nós de negócio
    graph.add_conditional_edges(
        "INTAKE_DOCS",
        next_after_intake,
        {"EXTRACT_VALIDATE": "EXTRACT_VALIDATE", END: END},
    )
    graph.add_conditional_edges(
        "EXTRACT_VALIDATE",
        next_after_extract_validate,
        {"DAV_FLOW": "DAV_FLOW", END: END},
    )
    graph.add_conditional_edges(
        "DAV_FLOW",
        next_after_dav_flow,
        {"DAV_DRAFT_READY": "DAV_DRAFT_READY", END: END},
    )
    graph.add_conditional_edges(
        "DAV_DRAFT_READY",
        next_after_dav_draft_ready,
        {END: END},
    )

    return graph.compile()
