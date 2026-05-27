# utils/extract_utils.py
"""
Utils para extracao/harmonizacao com paralelismo controlado.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.llms import llm
from app.models.state import ProcessState
from app.prompts.classification_prompts import DOC_PROMPTS
from app.prompts.extraction_prompts import (
    DEFAULT_DAV_TEMPLATE,
    HARMONIZE_DADOS_CARRO_SYSTEM,
    HARMONIZE_DADOS_CARRO_USER_TEMPLATE,
)
from app.storage.blob_client import BlobClient


logger = logging.getLogger(__name__)

# Concurrency control (tweak via env var without touching code).
_MAX_CONCURRENCY = int(os.getenv("EXTRACT_CONCURRENCY", "6"))
_SEM = asyncio.Semaphore(_MAX_CONCURRENCY)


async def _llm_create(**kwargs):
    """
    Calls llm.chat.completions.create without blocking the event loop when the
    configured client is synchronous.
    """
    create_fn = llm.chat.completions.create
    return await _maybe_await_or_thread(create_fn, **kwargs)


async def _maybe_await_or_thread(fn, /, *args, **kwargs):
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


def count_extract_pages(state: ProcessState) -> int:
    return len(list(iter_extract_pages(state)))


def iter_extract_pages(state: ProcessState) -> List[tuple[str, str, str]]:
    pages: List[tuple[str, str, str]] = []
    for doc_id, info in (state.docs or {}).items():
        if "_page_" in doc_id or not isinstance(info, dict):
            continue
        category = info.get("category", "OUTRO")
        for page_blob in info.get("pages", []):
            if page_blob:
                pages.append((str(page_blob), str(doc_id), str(category)))
    return pages


async def process_single_page(page_blob: str, doc_id: str, category: str) -> Dict[str, Any] | None:
    """Process one page with one structured vision call."""
    logger.info("Processing page doc_id=%s category=%s blob=%s", doc_id, category, page_blob)

    try:
        blob_client = _get_blob_client()
        img_base64 = await _maybe_await_or_thread(blob_client.get_blob_as_base64, page_blob)
        prompt_specific = DOC_PROMPTS.get(category, DOC_PROMPTS["OUTROS"])

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"""
Analisa esta imagem de documento automovel e responde apenas em JSON.

Formato obrigatorio:
{{
  "full_desc": "descricao curta mas completa do documento, textos principais e evidencias",
  "extracted": {{ "campo": "valor" }}
}}

Regras:
- Inclui em full_desc os textos, entidades, VIN, matriculas, precos, datas e dados de pessoas/empresas relevantes.
- Em extracted, extrai dados estruturados relevantes para DAV.
- Se a categoria for incerta, extrai tudo o que for util e deixa claro em full_desc.
- Mantem valores como aparecem no documento quando fizer sentido.

Categoria classificada: {category}

Guia especifico da categoria:
{prompt_specific}
""",
                },
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}},
            ],
        }]

        async with _SEM:
            response = await _llm_create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2200,
                response_format={"type": "json_object"},
            )

        raw_content = (response.choices[0].message.content or "{}").strip()
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            parsed = {"full_desc": raw_content, "extracted": {}}

        full_description = str(parsed.get("full_desc") or "")
        extracted = parsed.get("extracted")
        if not isinstance(extracted, dict):
            extracted = parsed

        return {
            "doc_id": doc_id,
            "category": category,
            "page_blob": page_blob,
            "gpt_raw": json.dumps(extracted, ensure_ascii=False),
            "full_desc": full_description,
        }

    except Exception:
        logger.exception("Failed to process page doc_id=%s blob=%s", doc_id, page_blob)
        return None


async def extract_all_pages_parallel(
    state: ProcessState,
    on_page_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    page_specs: Optional[List[tuple[str, str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Fase 1: processa todas as paginas em paralelo."""
    raw_insights: List[Dict[str, Any]] = []
    specs = page_specs if page_specs is not None else iter_extract_pages(state)

    logical_docs = {doc_id for _, doc_id, _ in specs}
    logger.info(
        "Extracting %s logical docs -> %s pages with LLM concurrency=%s",
        len(logical_docs),
        len(specs),
        _MAX_CONCURRENCY,
    )

    all_tasks = []
    for page_blob, doc_id, category in specs:
        all_tasks.append(asyncio.create_task(process_single_page(page_blob, doc_id, category)))

    for task in asyncio.as_completed(all_tasks):
        try:
            result = await task
        except Exception as exc:
            logger.warning("Parallel page task failed: %s", exc)
            continue

        if isinstance(result, dict) and result:
            raw_insights.append(result)
            if on_page_result:
                await on_page_result(result)

    logger.info("Processed %s pages", len(raw_insights))
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
    """
    template = dav_template or DEFAULT_DAV_TEMPLATE

    combined_context_parts: List[str] = []
    for insight in raw_insights:
        doc_id = insight.get("doc_id", "UNKNOWN")
        category = insight.get("category", "UNKNOWN")
        gpt_raw = insight.get("gpt_raw", "")
        full_desc = insight.get("full_desc", "")
        combined_context_parts.append(
            f"Doc {doc_id} ({category}):\nDESC:\n{full_desc}\nJSON:\n{gpt_raw}\n"
        )

    combined_context = "\n".join(combined_context_parts)
    final_prompt = HARMONIZE_DADOS_CARRO_USER_TEMPLATE.format(
        raw_context=combined_context,
        dav_template=json.dumps(template, ensure_ascii=False),
    )

    response = await _llm_create(
        model=model,
        messages=[
            {"role": "system", "content": HARMONIZE_DADOS_CARRO_SYSTEM},
            {"role": "user", "content": final_prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    try:
        harmonized = json.loads(content)
    except json.JSONDecodeError:
        harmonized = {}

    return {key: harmonized.get(key, None) for key in template.keys()}


def find_doc_by_category(state: ProcessState, category: str) -> Optional[Dict[str, Any]]:
    """
    Procura nos docs logicos um documento com a categoria pedida.
    """
    for doc_id, info in (state.docs or {}).items():
        if "_page_" in doc_id or not isinstance(info, dict):
            continue
        if info.get("category") == category:
            return {"id": doc_id, **info}
    return None
