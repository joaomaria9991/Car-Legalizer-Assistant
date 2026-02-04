# utils/extract_utils.py
"""
Utils para node_extract_validate com paralelismo GPT-4o
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from app.models.state import ProcessState
from app.llms import llm
from app.prompts.dav_prompts import EXTRACT_DADOS_CARRO 
from app.prompts.classification_prompts import HARMONIZE_DADOS_CARRO
from app.storage.blob_client import BlobClient


async def process_single_page(page_blob: str, doc_id: str, category: str) -> Dict[str, Any]:
    """Processa 1 página GPT-4o em paralelo (JSON mode)."""
    print(f"🖼️  PROCESSANDO PÁGINA: {page_blob}")
    
    try:
        blob_client = BlobClient()
        print(f"   📥 Lendo blob...")
        img_base64 = await blob_client.get_blob_as_base64(page_blob)
        print(f"   ✅ Imagem carregada ({len(img_base64)} chars)")
        
        messages = [{
            "role": "user", 
            "content": [
                {"type": "text", "text": EXTRACT_DADOS_CARRO}, 
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
            ]
        }]
        
        print(f"   🤖 Chamando GPT-4o...")
        response = llm.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        raw_content = response.choices[0].message.content.strip()
        print(f"   ✅ GPT respondeu ({len(raw_content)} chars): {raw_content[:100]}...")
        
        result = {
            "doc_id": doc_id,
            "category": category,
            "page_blob": page_blob,
            "gpt_raw": raw_content
        }
        print(f"   🎯 Resultado salvo: {doc_id}/{category}")
        return result
        
    except Exception as e:
        print(f"   ❌ ERRO process_single_page {page_blob}: {e}")
        return None


async def extract_all_pages_parallel(state: ProcessState) -> List[Dict[str, Any]]:
    """Fase 1: processa TODAS as páginas em PARALELO."""
    blob_client = BlobClient()
    raw_insights = []
    
    # Só docs lógicos (1,2,3...)
    logical_docs = {
        doc_id: info for doc_id, info in state.docs.items() 
        if "_page_" not in doc_id
    }
    
    print(f"📚 {len(logical_docs)} docs lógicos → {sum(len(d.get('pages', [])) for d in logical_docs.values())} páginas")
    
    # Tarefas paralelas por doc
    all_tasks = []
    for doc_id, info in logical_docs.items():
        pages = info.get("pages", [])
        for page_blob in pages:
            task = process_single_page(page_blob, doc_id, info["category"])
            all_tasks.append(task)
    
    # Executa TUDO em paralelo
    results = await asyncio.gather(*all_tasks, return_exceptions=True)
    
    # Filtra sucessos
    for result in results:
        if isinstance(result, dict) and result:  # sucesso
            raw_insights.append(result)
        elif isinstance(result, Exception):  # erro
            print(f"❌ Erro paralelo: {result}")
    
    print(f"✅ {len(raw_insights)} páginas processadas")
    return raw_insights


async def harmonize_all_data(raw_insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fase 2: harmoniza TODOS os insights num único dados_carro."""
    # Monta contexto completo
    pages_text = []
    for insight in raw_insights:
        pages_text.append(
            f"Doc {insight['doc_id']} ({insight['category']}), página {insight['page_blob']}:\n"
            f"{insight['gpt_raw']}"
        )
    
    combined_context = "\n\n---\n\n".join(pages_text)
    final_prompt = HARMONIZE_DADOS_CARRO.format(raw_context=combined_context)
    
    messages = [{"role": "user", "content": [{"type": "text", "text": final_prompt}]}]
    
    response = llm.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=1200,
        response_format={"type": "json_object"}
    )
    
    raw_json = response.choices[0].message.content.strip()
    return json.loads(raw_json)


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