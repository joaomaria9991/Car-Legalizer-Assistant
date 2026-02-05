# utils/extract_utils.py
"""
Utils para node_extract_validate com paralelismo GPT-4o
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from app.models.state import ProcessState
import inspect
import os

from app.storage.blob_client import BlobClient
from app.llms import llm
from app.prompts.dav_prompts import EXTRACT_DADOS_CARRO
from app.prompts.classification_prompts import  DOC_PROMPTS
from app.prompts.extraction_prompts import  HARMONIZE_DADOS_CARRO_SYSTEM, HARMONIZE_DADOS_CARRO_USER_TEMPLATE, DEFAULT_DAV_TEMPLATE
from app.prompts.classification_prompts import CLASSIFY_DOC_PROMPT, DOC_PROMPTS



# -----------------------------------------------------------------------------
# Concurrency control (tweak via env var without touching code)
# -----------------------------------------------------------------------------
_MAX_CONCURRENCY = int(os.getenv("EXTRACT_CONCURRENCY", "6"))
_SEM = asyncio.Semaphore(_MAX_CONCURRENCY)


async def _llm_create(**kwargs):
    """
    Calls llm.chat.completions.create in a non-blocking way (sync or async client).
    Assumes `llm` exists in your module scope (as in your current code).
    """
    create_fn = llm.chat.completions.create
    return await _maybe_await_or_thread(create_fn, **kwargs)




async def _maybe_await_or_thread(fn, /, *args, **kwargs):
    """
    - If fn is an async function -> await it
    - Else run it in a thread -> avoids blocking the event loop
    - Also handles cases where fn is sync but returns an awaitable
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)

    result = await asyncio.to_thread(fn, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


_BLOB_CLIENT_SINGLETON = None

def _get_blob_client():
    global _BLOB_CLIENT_SINGLETON
    if _BLOB_CLIENT_SINGLETON is None:
        _BLOB_CLIENT_SINGLETON = BlobClient()
    return _BLOB_CLIENT_SINGLETON

async def process_single_page(page_blob: str, doc_id: str, category: str) -> Dict[str, Any]:
    """Processa 1 página - PRIMEIRO lê TUDO, DEPOIS mapeia."""
    print(f"🖼️  {doc_id}/{category}: {page_blob}")

    try:
        blob_client = _get_blob_client()

        # get_blob_as_base64 pode ser async ou sync (depende da tua implementação)
        img_base64 = await _maybe_await_or_thread(blob_client.get_blob_as_base64, page_blob)

        # 🎯 PASSO 1: Lê TUDO da imagem (livre)
        messages_step1 = [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"""
                DESCREVE TUDO que vês nesta imagem de documento automóvel.
                - Textos principais (cabeçalhos, entidades)
                - Números importantes (VIN 17 dígitos, matrículas, preços €, datas)
                - Campos estruturados (marca, modelo, proprietário, etc)
                - Qualquer info relevante para DAV Alfândega

                FOCO: documentos multilíngue (alemão/português/inglês/etc...)
                """},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                            ]
                        }]

        # Limita concorrência (evita rate-limit storms e timeouts)
        async with _SEM:
            desc_response = await _llm_create(
                model="gpt-4o",
                messages=messages_step1,
                max_tokens=2000
            )

        full_description = desc_response.choices[0].message.content

        # 🎯 PASSO 2: Mapeia para JSON DAV (usando categoria como guia)
        prompt_specific = DOC_PROMPTS.get(category, DOC_PROMPTS["OUTROS"])

        messages_step2 = [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"""
            Com base nesta DESCRIÇÃO COMPLETA da imagem:

            {full_description}

            Esta é {category}. Extrai para JSON DAV:

            {prompt_specific}

            MAS inclui QUALQUER outro dado relevante que viste!
            """},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
            ]
        }]

        async with _SEM:
            response = await _llm_create(
                model="gpt-4o",
                messages=messages_step2,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

        raw_content = response.choices[0].message.content.strip()

        return {
            "doc_id": doc_id,
            "category": category,
            "page_blob": page_blob,
            "gpt_raw": raw_content,
            "full_desc": full_description  # ← DEBUG!
        }

    except Exception as e:
        return None




async def extract_all_pages_parallel(state: "ProcessState") -> List[Dict[str, Any]]:
    """Fase 1: processa TODAS as páginas em PARALELO."""
    raw_insights: List[Dict[str, Any]] = []

    # Só docs lógicos (1,2,3...)
    logical_docs = {
        doc_id: info for doc_id, info in state.docs.items()
        if "_page_" not in doc_id
    }

    total_pages = sum(len(d.get("pages", [])) for d in logical_docs.values())
    print(f"📚 {len(logical_docs)} docs lógicos → {total_pages} páginas")
    print(f"⚙️  Concorrência LLM limitada a: {_MAX_CONCURRENCY}")

    # Tarefas paralelas por página
    all_tasks = []
    for doc_id, info in logical_docs.items():
        pages = info.get("pages", [])
        category = info.get("category", "OUTRO")  # safety
        for page_blob in pages:
            all_tasks.append(asyncio.create_task(
                process_single_page(page_blob, doc_id, category)
            ))

    # Executa TUDO em paralelo (mas com rate limiting via semaphore)
    # return_exceptions=True evita rebentar tudo à primeira falha.
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, dict) and result:
            raw_insights.append(result)
        elif isinstance(result, Exception):
            print(f"❌ Erro paralelo (task): {result}")

    print(f"✅ {len(raw_insights)} páginas processadas")
    return raw_insights


async def harmonize_all_data(
    raw_insights: List[Dict[str, Any]],
    dav_template: Dict[str, Any] | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> Dict[str, Any]:
    """
    Phase 2: Harmonize extracted per-page insights into one flat DAV JSON object.

    Args:
        llm: OpenAI client (or compatible) that exposes llm.chat.completions.create(...)
        raw_insights: list of dicts, each containing doc_id, category, gpt_raw (json string)
        dav_template: dict with ALL output keys; if None, uses DEFAULT_DAV_TEMPLATE
        model: model name
        temperature: low for consistency
        max_tokens: output limit

    Returns:
        dict: harmonized DAV object with keys "CODE:Field Name" and values or null
    """
    template = dav_template or DEFAULT_DAV_TEMPLATE

    # 1) Build combined context
    combined_context_parts: List[str] = []
    for insight in raw_insights:
        doc_id = insight.get("doc_id", "UNKNOWN")
        category = insight.get("category", "UNKNOWN")
        gpt_raw = insight.get("gpt_raw", "")

        combined_context_parts.append(f"📄 Doc {doc_id} ({category}):\n{gpt_raw}\n")

    combined_context = "\n".join(combined_context_parts)

    # 2) Build user prompt
    final_prompt = HARMONIZE_DADOS_CARRO_USER_TEMPLATE.format(
        raw_context=combined_context,
        dav_template=json.dumps(template, ensure_ascii=False)
    )

    # 3) Call LLM with strict JSON response
    messages = [
        {"role": "system", "content": HARMONIZE_DADOS_CARRO_SYSTEM},
        {"role": "user", "content": final_prompt},
    ]

    response = llm.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"

    # 4) Parse and enforce template keys (never drop keys)
    try:
        harmonized = json.loads(content)
    except json.JSONDecodeError:
        # If the model somehow returns invalid JSON, fail closed to template
        harmonized = {}

    # Ensure all keys exist and no extra keys are required (we keep extras only if you want)
    # Here: keep ONLY template keys to keep the output deterministic.
    cleaned: Dict[str, Any] = {}
    for k in template.keys():
        cleaned[k] = harmonized.get(k, None)

    return cleaned



def find_doc_by_category(state: ProcessState, category: str) -> Optional[Dict[str, Any]]:
    """
    Procura nos docs 'lógicos' (chaves '1','2',...) um documento com a category pedida.
    Ignora as entradas por página (1_page_1.jpg, etc).
    
    Args:
        state: ProcessState atual
        category: categoria exata para procurar (ex: "FATURA_PROFORMA")
    
    Returns:
        Dict completo do doc ou None se não encontrou
    """
    for doc_id, info in state.docs.items():
        # só considera docs lógicos (sem '_page_')
        if '_page_' in doc_id:
            continue
        if info.get("category") == category:
            return {"id": doc_id, **info}
    return None