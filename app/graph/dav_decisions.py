from __future__ import annotations

from typing import Any

from app.graph.dav_flow_utils import set_dav_field
from app.graph.dav_metadata import record_user_change
from app.models.state import ProcessState


CONTROLLER_CODES = ["DC16", "DC21", "14", "85"]


def build_dav_decisions(state: ProcessState, max_decisions: int = 4) -> list[dict[str, Any]]:
    """Return only human/applicability decisions; conflicts are handled by metadata."""
    if not state.dados_carro:
        return []

    decisions: list[dict[str, Any]] = []
    code_index = _code_index(state.dados_carro)
    meta = (state.flags or {}).get("dav_field_meta") or {}

    for code in CONTROLLER_CODES:
        decision = _controller_decision(state, code_index, meta, code)
        if decision:
            decisions.append(decision)
            if len(decisions) >= max_decisions:
                return decisions

    return decisions


def apply_dav_decision_answer(state: ProcessState, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply a human decision using the normal DAV field update path."""
    updates = payload.get("field_updates")
    if not isinstance(updates, list) or not updates:
        field = payload.get("field")
        if not field:
            return []
        updates = [{"field": field, "value": payload.get("value")}]

    applied: list[dict[str, Any]] = []
    for update in updates:
        field = update.get("field")
        if not field:
            continue
        result = set_dav_field(
            state,
            field=str(field),
            value=update.get("value"),
            clear=bool(update.get("clear", False)),
        )
        record_user_change(state, result)
        applied.append(result)

    return applied


def _controller_decision(
    state: ProcessState,
    code_index: dict[str, str],
    meta: dict[str, dict[str, Any]],
    code: str,
) -> dict[str, Any] | None:
    field_key = code_index.get(code)
    if not field_key:
        return None
    entry = meta.get(field_key) or {}
    value = state.dados_carro.get(field_key)
    if not _needs_controller_answer(value, entry):
        return None

    if code == "DC16":
        return {
            "id": "applicability:DC16",
            "kind": "applicability",
            "field": field_key,
            "label": "Intermediarios na transacao",
            "message": "Existiram intermediarios na transacao?",
            "reason": "Esta resposta pode bloquear os campos DC17 a DC20.",
            "impact": "Se responderes Nao, deixo de pedir os dados do intermediario.",
            "options": [
                _option("Nao", "Nao", "Sem intermediarios; bloqueia dados do intermediario."),
                _option("Sim", "Sim", "Mantem os campos do intermediario em revisao."),
            ],
        }

    if code == "DC21":
        return {
            "id": "applicability:DC21",
            "kind": "applicability",
            "field": field_key,
            "label": "Transporte ate Portugal",
            "message": "Como o veiculo veio para Portugal?",
            "reason": "Esta resposta decide se os dados da transportadora sao necessarios.",
            "impact": "Proprios meios bloqueia DC22 a DC24; transportadora mantem esses campos.",
            "options": [
                _option("Proprios meios", "Proprios meios", "Nao pede empresa transportadora."),
                _option("Transportadora", "Transportadora", "Pede dados da empresa transportadora."),
            ],
        }

    if code == "14":
        return {
            "id": "applicability:14",
            "kind": "applicability",
            "field": field_key,
            "label": "Declarante",
            "message": "Esta a declarar em nome proprio?",
            "reason": "Esta resposta decide se ha representante.",
            "impact": "Em nome proprio bloqueia o numero de identificacao do representante.",
            "options": [
                {
                    "label": "Proprio",
                    "value": "Proprio",
                    "description": "O proprietario/adquirente e o declarante.",
                    "field_updates": [
                        {"field": field_key, "value": "Proprio"},
                        {"field": "15", "value": None, "clear": True},
                    ],
                },
                _option("Representante", "Representante", "Mantem dados de representante em revisao."),
            ],
        }

    if code == "85":
        return {
            "id": "applicability:85",
            "kind": "applicability",
            "field": field_key,
            "label": "Garantia",
            "message": "Existe garantia do veiculo?",
            "reason": "Esta resposta decide se o fundamento legal e necessario.",
            "impact": "Sem garantia, o campo 86 deixa de ser pedido.",
            "options": [
                _option("Nao", "Nao", "Bloqueia fundamento legal de garantia."),
                _option("Sim", "Sim", "Mantem fundamento legal em revisao."),
            ],
        }

    return None


def _needs_controller_answer(value: Any, meta: dict[str, Any]) -> bool:
    status = meta.get("status")
    return _is_missing(value) or status in {"missing", "needs_review", "conflict"}


def _option(label: str, value: Any, description: str) -> dict[str, Any]:
    return {"label": label, "value": value, "description": description}


def _code_index(dados_carro: dict[str, Any]) -> dict[str, str]:
    return {key.split(":", 1)[0].strip(): key for key in dados_carro}


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
