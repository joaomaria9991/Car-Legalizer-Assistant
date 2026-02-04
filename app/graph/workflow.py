from typing import Literal
from langgraph.graph import StateGraph, END
from app.models.state import ProcessState
import json

import pdf2image
import io
import base64
from PIL import Image

from app.handlers.handlers import (
    handle_intake_docs,
    handle_extract_validate,
    handle_dav_collect_fiscal,
    handle_dav_draft_generation,
)
from app.llms import llm  # teu AzureOpenAI
from app.prompts.dav_prompts import EXTRACT_DADOS_CARRO, GENERATE_DAV
from app.storage.blob_client import BlobClient
from app.prompts.classification_prompts import CLASSIFY_DOC_PROMPT, HARMONIZE_DADOS_CARRO
from app.graph.graph_utils import (
    extract_all_pages_parallel, harmonize_all_data,find_doc_by_category)

# ----------------- NÓS -----------------
async def node_intake_docs(state: ProcessState) -> dict:
    """🤖 CLASSIFICAÇÃO HÍBRIDA - PDF INTEIRO (mantém contexto)."""
    
    print(f"🔍 INÍCIO - docs antes: {len(state.docs)}")
    
    event = state.flags.get("last_event", {})
    
    if event.get("type") == "classify_docs":
        print("🚀 CLASSIFICAÇÃO HÍBRIDA EXECUTANDO...")
        
        blob_client = BlobClient()
        blob_prefix = f"processes/{state.process_id}/docs/"
        all_blobs = await blob_client.list_blobs(blob_prefix)
        
        # 1️⃣ AGRUPA PÁGINAS POR PDF ORIGINAL
        pdf_groups = {}
        for blob in all_blobs:
            filename = blob['name'].split('/')[-1]
            if '_page_' in filename:
                # "CERTIFICADO_page_1.jpg" → "CERTIFICADO"
                base_name = filename.split('_page_')[0]
                if base_name not in pdf_groups:
                    pdf_groups[base_name] = []
                pdf_groups[base_name].append(blob)
            else:
                # Imagens soltas ficam sozinhas
                pdf_groups[filename] = [blob]
        
        print(f"📚 {len(pdf_groups)} documentos únicos encontrados")
        
        # 2️⃣ CLASSIFICA CADA PDF INTEIRO
        for pdf_name, pages in pdf_groups.items():
            print(f"\n📄 Processando: {pdf_name} ({len(pages)} páginas)")
            
            # Usa 1ª página (mais representativa do documento)
            first_page = pages[0]
            image_base64 = await blob_client.get_blob_as_base64(first_page["name"])
            
            messages = [
                {"role": "user", "content": [
                    {
                        "type": "text", 
                        "text": CLASSIFY_DOC_PROMPT
                    },
                    {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]}
            ]
            
            response = llm.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            doc_type = result["category"]
            
            # ✅ SALVA PDF COMO UNIDADE (lista de páginas)
            state.docs[pdf_name] = {
                "category": doc_type,
                "pages": [page["name"] for page in pages],
                "filename": pdf_name,
                "confidence": result.get("confidence", 0.5),
                "status": "classified"
            }
            print(f"✅ {pdf_name} → {doc_type} ({len(pages)} páginas)")
        
        state.historico.append(f"🤖 Classificou {len(state.docs)} documentos")
        
        # 💾 SALVA NA BLOB
        print("💾 SALVANDO STATE NA BLOB...")
        await blob_client.save_state(state.process_id, state.model_dump())
        print(f"✅ STATE SALVO: {len(state.docs)} docs")
    
    print(f"🔚 RETORNO: {len(state.docs)} docs")
    return state.model_dump()




async def node_extract_validate(state: ProcessState) -> dict:
    """🧠 EXTRACT_VALIDATE: Fase 1 (paralelo) + Fase 2 (harmonização)."""
    
    event = state.flags.get("last_event", {})
    if event.get("type") != "start_extract":
        return state.model_dump()
    
    # FASE 1: ainda não temos raw_page_insights?
    if "raw_page_insights" not in state.flags or not state.flags["raw_page_insights"]:
        print("🚀 FASE 1: processar TODAS as páginas (PARALELO)")
        
        raw_insights = await extract_all_pages_parallel(state)
        state.flags["raw_page_insights"] = raw_insights
        state.historico.append(f"✅ Fase 1: {len(raw_insights)} páginas processadas em paralelo")
        
    
    # FASE 2: já temos → harmonizar
    print("🚀 FASE 2: harmonizar tudo → dados_carro")
    
    raw_insights = state.flags["raw_page_insights"]
    dados_carro = await harmonize_all_data(raw_insights)
    
    print("✅ dados_carro harmonizado:")
    print(json.dumps(dados_carro, indent=2, ensure_ascii=False))
    
    state.dados_carro = dados_carro
    state.fase_atual = "DAV_FLOW"
    state.historico.append("✅ Fase 2: dados_carro harmonizado de todas as páginas")
    
    return state.model_dump()



async def node_dav_flow(state: ProcessState) -> dict:
    """🤖 Gera DAV automático."""
    event = state.flags.get("last_event", {})
    
    if event.get("type") == "generate_dav_draft" and state.dados_carro:
        prompt = GENERATE_DAV.format(
            dados_carro=state.dados_carro,
            dados_fiscal=state.dados_fiscal
        )
        
        response = llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        
        state.dav_draft = response.choices[0].message.content
        state.sub_fase = "DAV_READY"
    
    return state.model_dump()

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
    """
    Usa docs lógicos (1..9) e categorias híbridas.
    Exemplo: avança quando tiver Fatura + Documento Transporte.
    """
    has_invoice = find_doc_by_category(state, "FATURA_PROFORMA") or \
                  find_doc_by_category(state, "FATURA_COMPRA")
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
