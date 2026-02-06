from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage

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
from app.prompts.dav_prompts import  GENERATE_DAV
from app.storage.blob_client import BlobClient
from app.prompts.classification_prompts import CLASSIFY_DOC_PROMPT
from app.graph.graph_utils import (
    extract_all_pages_parallel, harmonize_all_data,find_doc_by_category)
from app.models.state import ProcessState
from app.graph.dav_flow_utils import set_dav_field, find_missing_fields, pick_questions, _resolve_key, SET_DAV_FIELD_TOOL, llm_route_intent



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
    state.flags = state.flags or {}
    event = state.flags.get("last_event") or {}

    state.fase_atual = "DAV_FLOW"
    state.sub_fase = getattr(state, "sub_fase", None) or "DAV_CHAT"

    # 1) Se NÃO é resposta do user: pergunta missing
    if event.get("type") != "dav_user_message":
        missing = find_missing_fields(state.dados_carro or {})
        if not missing:
            state.flags["ui_out"] = {"type": "dav_ready", "message": "✅ DAV completa. Queres gerar o draft?"}
            state.flags.pop("dav_pending_fields", None)
            return state.model_dump()

        ask_fields = pick_questions(missing, max_q=10)
        state.flags["dav_pending_fields"] = ask_fields

        # ✅ chama LLM para gerar explicações (NESTE turn)
        system_text = (
            "Responde APENAS com um objeto JSON. Sem markdown. Sem texto fora do JSON.\n"
            "És um assistente de preenchimento da DAV.\n"
            "Para CADA campo em falta, explica em 1–2 frases:\n"
            "• o que é o campo\n"
            "• onde o utilizador normalmente encontra (DUA/Certificado matrícula, CoC, Fatura, CMR, IMT, Inspeção, ou 'é uma escolha do utilizador')\n"
            "• dá um exemplo de formato de resposta\n"
            "Responde em JSON com este schema:\n"
            "{\n"
            '  "message": "texto curto introdutório",\n'
            '  "fields": [\n'
            '    {"field": "CODIGO", "label": "nome curto", "explain": "...", "where": "...", "examples": ["..."]}\n'
            "  ]\n"
            "}\n"
            "Só podes falar dos campos em PENDING_FIELDS.\n"
        )

        subset = {k: (state.dados_carro or {}).get(k) for k in ask_fields}

        resp = llm.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": f"PENDING_FIELDS:\n{json.dumps(ask_fields, ensure_ascii=False)}\n\nESTADO_SUBSET:\n{json.dumps(subset, ensure_ascii=False)}"}
            ],
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        llm_json = json.loads(resp.choices[0].message.content.strip())

        state.flags["ui_out"] = {
            "type": "dav_question",
            "message": llm_json.get("message") or "Preciso de confirmar/preencher estes campos:",
            "fields": llm_json.get("fields") or ask_fields,  # fallback
        }

        return state.model_dump()


    # 2) É resposta do user: primeiro route intent (agentic)
    user_msg = (event.get("data") or {}).get("message", "").strip()

    route = await llm_route_intent(user_msg)
    intent = (route.get("intent") or "answer_fields").strip()

    # 1) upload_more_docs → muda fase e sai
    if intent == "upload_more_docs":
        state.fase_atual = "INTAKE_DOCS"
        state.sub_fase = "AGUARDAR_UPLOAD"

        # mantém progresso, limpa caches derivadas
        state.flags = state.flags or {}
        state.flags.pop("raw_page_insights", None)
        state.flags.pop("dav_pending_fields", None)

        state.flags["ui_out"] = {
            "type": "request_upload",
            "message": "📎 Ok — faz upload do novo documento. Depois eu volto a classificar e extrair mantendo o progresso.",
            # "debug_intent": route,  # opcional
        }
        state.historico.append("📎 LLM intent=upload_more_docs → reset para INTAKE_DOCS")
        return state.model_dump()

    # 2) export_state
    if intent == "export_state":
        blob_client = BlobClient()
        await blob_client.save_state(state.process_id, state.model_dump())
        state.flags["ui_out"] = {"type": "info", "message": "✅ Estado guardado no Blob."}
        state.historico.append("💾 LLM intent=export_state → save_state")
        return state.model_dump()

    # 3) generate_dav_draft
    if intent == "generate_dav_draft":
        state.flags["last_event"] = {"type": "generate_dav_draft"}
        state.flags["ui_out"] = {"type": "info", "message": "🧾 A gerar draft da DAV..."}
        state.historico.append("🧾 LLM intent=generate_dav_draft")
        return state.model_dump()

    # 4) default: answer_fields → continua fluxo normal
    pending = state.flags.get("dav_pending_fields") or []

    if not pending:
        # sem pending → recalcula e pergunta
        state.flags["last_event"] = {"type": "noop"}
        return await node_dav_flow(state)
    system_text = (
        "És um assistente de preenchimento da DAV.\n"
        "Quando pedires campos em falta, para CADA campo explica em 1–2 frases:\n"
        "• o que é o campo\n"
        "• onde o utilizador normalmente encontra (DUA/Certificado matrícula, CoC, Fatura, CMR, IMT, Inspeção, ou 'é uma escolha do utilizador')\n"
        "• dá um exemplo de formato de resposta (ex: AA-12-BB, 2026-02-05, 'Conduzido', etc.)\n"
        "Mantém linguagem simples e prática.\n"
        "Só podes preencher os campos em PENDING_FIELDS.\n"
        "Quando tiveres um valor para um campo, chama a tool set_dav_field(field=..., value=...).\n"
        "Se o utilizador não deu valor, não inventes.\n"
    )

    # Nota: aqui passamos apenas subset para reduzir tokens
    subset = {k: (state.dados_carro or {}).get(k) for k in pending}

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": f"PENDING_FIELDS:\n{json.dumps(pending, ensure_ascii=False)}\n\nESTADO_SUBSET:\n{json.dumps(subset, ensure_ascii=False)}\n\nRESPOSTA_USER:\n{user_msg}"}
    ]

    # 2a) primeira chamada: o modelo decide tool calls
    resp = llm.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=[SET_DAV_FIELD_TOOL],
        tool_choice="auto",
        max_tokens=400,
    )

    msg = resp.choices[0].message

    # 2b) se não chamou tools, devolve texto e repete pergunta
    tool_calls = getattr(msg, "tool_calls", None) or []

    # adiciona a mensagem do assistant (com tool_calls) ao histórico de mensagens
    messages.append({
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in tool_calls] if tool_calls else None
    })

    applied = []

    # 2c) executa tool calls manualmente
    for tc in tool_calls:
        fn = tc.function.name
        args = json.loads(tc.function.arguments or "{}")

        if fn == "set_dav_field":
            # segurança: só permite campos pending
            field = args.get("field")
            if field:
                # resolve para key real e verifica se pertence aos pending (por prefix match)
                resolved = _resolve_key(state.dados_carro or {}, field)
                if (resolved not in pending):
                    # tentativa de mexer fora → ignora e reporta
                    result = {"ok": False, "error": f"Campo fora de PENDING_FIELDS: {resolved}"}
                else:
                    result = set_dav_field(
                        state,
                        field=field,
                        value=args.get("value"),
                        clear=bool(args.get("clear", False)),
                    )
            else:
                result = {"ok": False, "error": "field em falta"}

        else:
            result = {"ok": False, "error": f"Tool desconhecida: {fn}"}

        applied.append(result)

        # devolve resultado ao modelo como role=tool
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    # 2d) chamada final para o modelo “fechar” (opcional mas útil para UX)
    resp2 = llm.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=250,
    )
    final_text = resp2.choices[0].message.content

    # limpa pending atual e pergunta o próximo bloco
    state.flags.pop("dav_pending_fields", None)

    missing = find_missing_fields(state.dados_carro or {})
    if not missing:
        state.flags["ui_out"] = {
            "type": "dav_ready",
            "message": "✅ Top! DAV completa.",
            "assistant_message": final_text,
            "applied": applied,
        }
        return state.model_dump()

    ask_fields = pick_questions(missing, max_q=120)

    state.flags["dav_pending_fields"] = ask_fields
    state.flags["ui_out"] = {
        "type": "dav_question",
        "message": "Perfeito. Faltam estes:",
        "fields": ask_fields,
        "assistant_message": final_text,
        "applied": applied,
    }

    state.historico.append("💬 dav_user_message processado (tool-calling manual)")
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
    event = (state.flags or {}).get("last_event") or {}
    if event.get("type") == "ui":
        intent = (event.get("payload") or {}).get("intent")
        if intent in ("upload_more_docs", "reset_to_intake"):
            state.fase_atual = "INTAKE_DOCS"
            state.sub_fase = "AGUARDAR_UPLOAD"
            # limpa caches derivadas
            if state.flags:
                state.flags.pop("raw_page_insights", None)
            state.dados_carro = state.dados_carro or {}  # podes manter ou limpar
            state.dav_draft = None if hasattr(state, "dav_draft") else None
            return "INTAKE_DOCS"

    # fallback: routing atual
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

# ----------------- BUILD_GRAPH -----------------
def build_graph():
    g = StateGraph(ProcessState)

    # Nodes
    g.add_node("router", router_node)

    g.add_node("INTAKE_DOCS", node_intake_docs)
    g.add_node("EXTRACT_VALIDATE", node_extract_validate)
    g.add_node("DAV_FLOW", node_dav_flow)
    g.add_node("DAV_DRAFT_READY", node_dav_draft_ready)

    # Entry point
    g.set_entry_point("router")

    # Router -> next node
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

    # Business edges
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
