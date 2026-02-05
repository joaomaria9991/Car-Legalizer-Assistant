#!/usr/bin/env python3
"""
TESTA O NÓ DAV_FLOW (conversacional) via API FastAPI.

Fluxo:
1) GET state
2) força fase_atual=DAV_FLOW (via advance_phase)
3) chama /events para o nó perguntar missing (evento neutro)
4) lê ui_out.fields
5) envia resposta do utilizador (dav_user_message)
6) repete até dav_ready
"""

import json
import time
import requests

from app.models import state


API = "http://localhost:8000"
PROCESS_ID = "demo-process-001"
MAX_TURNS = 15


def get_state(pid: str) -> dict:
    r = requests.get(f"{API}/processes/{pid}", timeout=30)
    r.raise_for_status()
    return r.json()


def post_event(pid: str, event: dict) -> dict:
    # O teu endpoint espera Form field event_json
    data = {"event_json": json.dumps(event, ensure_ascii=False)}
    r = requests.post(f"{API}/processes/{pid}/events", data=data, timeout=120)
    r.raise_for_status()
    return r.json()


def show_bot(state: dict):
    ui_out = (state.get("flags") or {}).get("ui_out") or {}
    t = ui_out.get("type")

    print(f"🧠 ui_out.type = {t}")

    # ✅ mensagem do bot (dinâmica)
    msg = ui_out.get("message") or ui_out.get("assistant_message") or ""
    if msg:
        print(f"🤖 {msg}")

    # campos (pode vir list[str] ou list[dict] dependendo da tua implementação)
    fields = ui_out.get("fields") or []
    if fields:
        print("\n🧾 Campos pedidos:")
        if isinstance(fields[0], dict):
            for f in fields:
                print(f"  - {f.get('field')} :: {f.get('label')}")
                if f.get("explain"):
                    print(f"      • {f['explain']}")
                if f.get("where"):
                    print(f"      • Onde: {f['where']}")
                ex = f.get("examples") or []
                if ex:
                    print(f"      • Ex: {', '.join(map(str, ex))}")
        else:
            for f in fields:
                print(f"  - {f}")

    applied = ui_out.get("applied") or []
    if applied:
        print("\n✅ Alterações aplicadas:")
        for a in applied:
            if isinstance(a, dict) and a.get("ok"):
                print(f"  - {a.get('field_resolved')}: {a.get('old')} -> {a.get('new')}")
            else:
                print(f"  - {a}")



def main():
    print(f"🚗 TESTE DAV_FLOW CHAT (API) - {PROCESS_ID}")
    print("=" * 60)

    # 1) Lê state
    state = get_state(PROCESS_ID)
    print(f"📍 estado inicial: fase={state.get('fase_atual')} | sub_fase={state.get('sub_fase')}")

    # 2) Força DAV_FLOW via advance_phase (usa o teu handler já existente)
    print("\n➡️  Forçar fase DAV_FLOW via advance_phase...")
    res = post_event(PROCESS_ID, {
        "type": "advance_phase",
        "data": {"nova_fase": "DAV_FLOW", "sub_fase": "DAV_CHAT"}
    })
    state = res["state"]
    print(f"✅ fase agora: {state.get('fase_atual')} | sub={state.get('sub_fase')}")

    # 3) Turn loop
    for turn in range(1, MAX_TURNS + 1):
        print(f"\n--- TURN {turn} ---")

        # 3a) Disparar “pergunta” do nó:
        # se o nó pergunta quando event.type != dav_user_message,
        # podemos mandar um evento neutro para forçar execução.
        res = post_event(PROCESS_ID, {"type": "noop"})
        state = res["state"]
        show_bot(state)
        ui_out = (state.get("flags") or {}).get("ui_out") or {}
        ui_type = ui_out.get("type")


        # 3b) Se DAV pronta, termina
        if ui_type == "dav_ready":
            print("\n✅ DAV_READY: conversa terminou.")
            break

        # 3c) Se recebeu pergunta com fields, responde
        if ui_type == "dav_question":
            fields = ui_out.get("fields") or []
            if not fields:
                print("⚠️ dav_question sem fields — a sair")
                break

            user_msg = input("\n🧑 Responde (texto livre, ex: '61=AB-12-CD; 67=2026-02-05'): ").strip()
            if not user_msg:
                user_msg = "não sei"

            res = post_event(PROCESS_ID, {
                "type": "dav_user_message",
                "data": {"message": user_msg}
            })
            state = res["state"]

            # aqui podes até NÃO chamar show_bot se não quiseres imprimir nada após a resposta
            # show_bot(state)

            time.sleep(2)
            continue
                    # Modo interactivo: tu escreves a resposta
            user_msg = input("\n🧑 Responde (texto livre, ex: '61=AB-12-CD; 67=2026-02-05'): ").strip()
            if not user_msg:
                user_msg = "não sei"

            # envia resposta
            res = post_event(PROCESS_ID, {
                "type": "dav_user_message",
                "data": {"message": user_msg}
            })
            state = res["state"]
            ui_out = (state.get("flags") or {}).get("ui_out") or {}

            show_bot(state)

            # pequeno sleep para legibilidade
            time.sleep(0.2)
            continue

        # 3d) Outros tipos (info/error)
        if ui_type == "error":
            print(f"❌ ERRO: {ui_out.get('message')}")
            break

        if ui_type == "info":
            # nó não perguntou nada → pode estar à espera de evento certo
            print(f"ℹ️ {ui_out.get('message')}")
            # tenta continuar
            time.sleep(0.2)
            continue

        print("⚠️ ui_out inesperado, a sair.")
        print(json.dumps(ui_out, indent=2, ensure_ascii=False))
        break

    # estado final (resumo)
    final_state = get_state(PROCESS_ID)
    print("\n" + "=" * 60)
    print("📦 Resumo final:")
    print(f"fase={final_state.get('fase_atual')} | sub_fase={final_state.get('sub_fase')}")
    ui_out = (final_state.get("flags") or {}).get("ui_out")
    if ui_out:
        print("ui_out:", json.dumps(ui_out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
