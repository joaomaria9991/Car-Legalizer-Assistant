from typing import Dict, Any
from langgraph.graph import StateGraph
from app.models.state import ProcessState

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
