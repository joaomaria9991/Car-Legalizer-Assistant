#!/usr/bin/env python3
"""TESTA APENAS EXTRAÇÃO FINAL → dados_carro"""

import asyncio
import json
import requests
from app.models.state import ProcessState
from app.graph.workflow import build_graph

async def main():
    process_id = "demo-process-001"
    
    print(f"🚗 TESTE EXTRAÇÃO DADOS CARRO - {process_id}")
    print("=" * 40)
    
    # 1. Lê estado atual (precisa ter raw_page_insights da Fase 1)
    resp = requests.get(f"http://localhost:8000/processes/{process_id}")
    state = ProcessState.model_validate(resp.json())
    
    print(f"📊 Antes: fase={state.fase_atual} | dados_carro={bool(state.dados_carro)}")
    
    # 2. Só injeta o evento e roda
    state.flags["last_event"] = {"type": "start_extract"}
    state.fase_atual = "EXTRACT_VALIDATE"
    
    graph = build_graph()
    result = await graph.ainvoke(state.model_dump())
    state_final = ProcessState.model_validate(result)
    
    # 3. Resultado
    print(f"\n✅ DADOS CARRO EXTRAÍDOS!")
    print(f"📍 fase_atual: {state_final.fase_atual}")
    print("\n📊 dados_carro:")
    print(json.dumps(state_final.dados_carro, indent=2, ensure_ascii=False))
    
    # Salva
    with open(f"dados_carro_{process_id}.json", "w", encoding="utf-8") as f:
        json.dump(state_final.model_dump(), f, indent=2)
    print(f"\n💾 Salvo: dados_carro_{process_id}.json")

if __name__ == "__main__":
    asyncio.run(main())
