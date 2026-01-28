#!/usr/bin/env python3
"""
Teste completo do grafo - VERSÃO FINAL CORRIGIDA
"""

import asyncio
import json
from pathlib import Path
from typing import List
from models.state import ProcessState
from graph.workflow import build_graph

async def create_test_files():
    test_dir = Path("test_files")
    test_dir.mkdir(exist_ok=True)
    
    for filename in ["fatura.pdf", "dua.pdf"]:
        filepath = test_dir / filename
        if not filepath.exists():
            filepath.write_bytes(b"%PDF-1.4\nTest document\n")
            print(f"✅ Criado {filepath}")

async def test_full_workflow():
    print("🚀 TESTE COMPLETO DO GRAFO\n" + "="*50)
    
    graph = build_graph()
    process_id = "test-complete-123"
    
    state = ProcessState(
        process_id=process_id,
        fase_atual="INTAKE_DOCS",
        docs={},  # ✅ correto
        historico=[],
        flags={}
    )
    
    print(f"📍 INÍCIO: {state.fase_atual}")
    
    # 1. UPLOAD FATURA
    print("\n1️⃣ UPLOAD FATURA")
    state.flags["last_event"] = {
        "type": "upload_doc",
        "data": {"doc_type": "fatura", "filename": "fatura.pdf"}
    }
    result_dict = await graph.ainvoke(state.model_dump())  # ✅ devolve dict
    state = ProcessState.model_validate(result_dict)       # ✅ volta a ProcessState
    print(f"   → {state.fase_atual} | Docs: {list(state.docs.keys())}")
    
    # 2. UPLOAD DUA
    print("\n2️⃣ UPLOAD DUA")
    state.flags["last_event"] = {
        "type": "upload_doc",
        "data": {"doc_type": "dua", "filename": "dua.pdf"}
    }
    result_dict = await graph.ainvoke(state.model_dump())
    state = ProcessState.model_validate(result_dict)
    print(f"   → {state.fase_atual} | Docs: {list(state.docs.keys())}")
    
    # 3. START_EXTRACT
    print("\n3️⃣ START_EXTRACT")
    state.flags["last_event"] = {"type": "start_extract"}
    result_dict = await graph.ainvoke(state.model_dump())
    state = ProcessState.model_validate(result_dict)
    print(f"   → {state.fase_atual}")
    
    # 4. ANSWER_FISCAL_QUESTIONS
    print("\n4️⃣ ANSWER_FISCAL")
    state.flags["last_event"] = {
        "type": "answer_fiscal_questions",
        "data": {
            "matricula": "AB-12-CD",
            "nif_proprietario": "123456789",
            "valor_compra": 25000
        }
    }
    result_dict = await graph.ainvoke(state.model_dump())
    state = ProcessState.model_validate(result_dict)
    print(f"   → {state.fase_atual}")
    
    # 5. GENERATE_DAV_DRAFT
    print("\n5️⃣ GENERATE_DAV_DRAFT")
    state.flags["last_event"] = {"type": "generate_dav_draft"}
    result_dict = await graph.ainvoke(state.model_dump())
    state = ProcessState.model_validate(result_dict)
    print(f"   → {state.fase_atual} | sub_fase: {getattr(state, 'sub_fase', 'N/A')}")
    
    print("\n🎉 FLUXO COMPLETO OK!")
    return state

async def main():
    await create_test_files()
    await test_full_workflow()
    print("\n✅ TESTE CONCLUÍDO!")

if __name__ == "__main__":
    asyncio.run(main())
