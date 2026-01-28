from typing import Dict, Any
from langgraph.graph import StateGraph
from models.state import ProcessState

async def intake_docs_node(state: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Nó inicial: recolhe docs básicos"""
    if event["type"] == "upload_doc":
        doc_type = event["data"]["doc_type"]
        state["docs"][doc_type] = {
            "blob_path": event["data"]["blob_path"],
            "parsed": False
        }
        state["historico"].append(f"Doc {doc_type} recebido")
    
    # Lógica simples: se tem fatura + DUA, avança
    if "fatura" in state["docs"] and "dua" in state["docs"]:
        state["fase_atual"] = "EXTRACT_VALIDATE"
        state["sub_fase"] = "EXTRAINDO"
    
    return state

# Grafo inicial (mini)
def create_graph():
    workflow = StateGraph(dict)
    workflow.add_node("intake_docs", intake_docs_node)
    return workflow.compile()


# app/graph/nodes.py
from models.state import ProcessState
from handlers.handlers import (
    handle_intake_docs,
    handle_extract_validate,
    handle_dav_collect_fiscal,
    handle_dav_draft_generation,
)

def node_intake_docs(state: ProcessState) -> ProcessState:
    # usa o handler atual que trabalha com dict
    new_dict = handle_intake_docs(state.model_dump(), state.flags.get("last_event", {}))
    return ProcessState(**new_dict)

def node_extract_validate(state: ProcessState) -> ProcessState:
    new_dict = handle_extract_validate(state.model_dump(), state.flags.get("last_event", {}))
    return ProcessState(**new_dict)

def node_dav_flow(state: ProcessState) -> ProcessState:
    new_dict = handle_dav_collect_fiscal(state.model_dump(), state.flags.get("last_event", {}))
    return ProcessState(**new_dict)

def node_dav_draft_ready(state: ProcessState) -> ProcessState:
    new_dict = handle_dav_draft_generation(state.model_dump(), state.flags.get("last_event", {}))
    return ProcessState(**new_dict)
