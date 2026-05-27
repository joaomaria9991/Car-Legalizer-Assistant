from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
from typing import Any

from app.models.state import ProcessState
from app.graph.dav_autofill import (
    candidate_display_value,
    candidate_key,
    extract_dav_candidates,
)


DAV_FIELD_META_FLAG = "dav_field_meta"
NOT_APPLICABLE_STATUS = "not_applicable"
NOT_APPLICABLE_SOURCE = "dav_applicability"

HIGH_RISK_KINDS = {"vin", "plate", "buyer_tax_id", "seller_tax_id"}
SOFT_REVIEW_KINDS = {
    "price",
    "kilometers",
    "first_registration_date",
    "entry_date",
    "invoice_date",
    "buyer_name",
    "seller_name",
    "buyer_address",
    "seller_address",
    "payment_method",
}

KIND_TO_CODES = {
    "vin": ["42"],
    "plate": ["61"],
    "buyer_tax_id": ["06a", "17a", "DC08"],
    "seller_tax_id": ["DC04"],
    "price": ["58", "77", "DC13"],
    "kilometers": ["57", "76"],
    "first_registration_date": ["60", "62"],
    "entry_date": ["66", "DC25"],
    "invoice_date": ["75", "DC11"],
    "buyer_name": ["18", "DC05"],
    "seller_name": ["DC01"],
    "buyer_address": ["DC06"],
    "seller_address": ["DC02"],
    "payment_method": ["84", "DC15"],
}


def refresh_dav_field_metadata(
    state: ProcessState,
    raw_insights: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Ensure every DAV field has metadata and mark conflicts from raw candidates.

    Existing user/induced metadata is preserved unless the current field value is
    empty. Missing and extracted metadata can be regenerated safely.
    """
    state.flags = state.flags or {}
    meta = _ensure_meta_dict(state)
    dados_carro = state.dados_carro or {}

    for stale_key in list(meta.keys()):
        if stale_key not in dados_carro:
            meta.pop(stale_key, None)

    for field_key, value in dados_carro.items():
        current = meta.get(field_key) or {}
        if _is_missing(value):
            meta[field_key] = {
                **current,
                "origin": "missing",
                "status": "missing",
                "reason": "Field is empty",
                "value": None,
                "alternatives": current.get("alternatives") or [],
            }
            continue

        if current.get("origin") in {"user", "induced"} and current.get("status") == "filled":
            current["value"] = value
            current.setdefault("alternatives", [])
            meta[field_key] = current
            continue

        if current.get("origin") == "user":
            current["value"] = value
            current["status"] = "filled"
            current.setdefault("alternatives", [])
            meta[field_key] = current
            continue

        meta[field_key] = {
            **current,
            "origin": current.get("origin") if current.get("origin") in {"induced", "user"} else "extracted",
            "status": "filled",
            "reason": current.get("reason") or "Value from harmonized extraction",
            "source": current.get("source") or "harmonized_extraction",
            "confidence": current.get("confidence"),
            "value": value,
            "alternatives": current.get("alternatives") or [],
        }

    mark_candidate_conflicts(state, raw_insights or [])
    apply_dav_applicability(state)
    return meta


def record_induced_changes(state: ProcessState, changes: list[dict[str, Any]]) -> None:
    if not changes:
        return

    meta = _ensure_meta_dict(state)
    for change in changes:
        field = change.get("field")
        if not field:
            continue
        meta[field] = {
            "origin": "induced",
            "status": "filled",
            "reason": change.get("reason") or "Inferred from DAV equivalence",
            "source": change.get("source"),
            "value": change.get("value"),
            "alternatives": (meta.get(field) or {}).get("alternatives") or [],
        }


def record_user_change(state: ProcessState, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    field = result.get("field_resolved")
    if not field:
        return

    new_value = result.get("new")
    meta = _ensure_meta_dict(state)
    meta[field] = {
        "origin": "user",
        "status": "missing" if _is_missing(new_value) else "filled",
        "reason": "User supplied this field in DAV chat",
        "source": "dav_user_message",
        "value": new_value,
        "alternatives": [],
    }
    apply_dav_applicability(state)


def is_not_applicable(meta_entry: dict[str, Any] | None) -> bool:
    return bool(meta_entry) and meta_entry.get("status") == NOT_APPLICABLE_STATUS


def apply_dav_applicability(state: ProcessState) -> list[dict[str, Any]]:
    """
    Mark DAV fields that are disabled by explicit answers elsewhere in the form.

    This is intentionally conservative and reversible. Existing not-applicable
    metadata created by this helper is cleared first, then the current rules are
    applied again from the current dados_carro values.
    """
    if not state.dados_carro:
        return []

    meta = _ensure_meta_dict(state)
    code_index = _code_index(state.dados_carro)
    changes: list[dict[str, Any]] = []

    for field_key, entry in list(meta.items()):
        if (
            isinstance(entry, dict)
            and entry.get("status") == NOT_APPLICABLE_STATUS
            and entry.get("source") == NOT_APPLICABLE_SOURCE
        ):
            value = state.dados_carro.get(field_key)
            meta[field_key] = _default_meta_for_value(value)

    def value(code: str) -> Any:
        key = code_index.get(code)
        return state.dados_carro.get(key) if key else None

    def mark(codes: list[str], controller: str, reason: str) -> None:
        for code in codes:
            field_key = code_index.get(code)
            if not field_key:
                continue
            meta[field_key] = {
                "origin": NOT_APPLICABLE_STATUS,
                "status": NOT_APPLICABLE_STATUS,
                "reason": reason,
                "source": NOT_APPLICABLE_SOURCE,
                "source_doc": controller,
                "value": state.dados_carro.get(field_key),
                "alternatives": [],
            }
            changes.append({"field": field_key, "controller": controller, "reason": reason})

    if _is_explicit_no(value("DC16")):
        mark(
            ["DC17", "DC18", "DC19", "DC20"],
            "DC16",
            "DC16 = Não, por isso dados do intermediário não são necessários.",
        )

    if _is_own_transport(value("DC21")):
        mark(
            ["DC22", "DC23", "DC24"],
            "DC21",
            "DC21 indica meios próprios, por isso dados da transportadora não são necessários.",
        )

    if _is_missing(value("63")) and not _is_missing(value("61")):
        mark(
            ["64", "65"],
            "61/63",
            "Existe matrícula definitiva e não há matrícula provisória, por isso datas da matrícula provisória não são necessárias.",
        )

    if _is_self_representation(value("14")) and _is_blank_select(value("15")):
        mark(
            ["15a"],
            "14/15",
            "A representação é própria e não há representante, por isso o número do representante não é necessário.",
        )

    if _is_particular(value("02")):
        mark(
            ["16"],
            "02",
            "O sujeito passivo é Particular, por isso NIF de sociedade HD não é necessário.",
        )

    if _is_combustion_fuel(value("39")):
        mark(
            ["52"],
            "39",
            "O combustível indicado não é elétrico/híbrido plug-in, por isso autonomia da bateria não é necessária.",
        )

    if _is_eu_country(value("56")) or _is_eu_country(value("70")):
        if _is_missing(value("68")):
            mark(["68"], "56/70", "O veículo tem procedência/entrada UE e não há declaração de importação aplicável.")
        if _is_missing(value("69")):
            mark(["69"], "56/70", "O veículo tem procedência/entrada UE e não há tipo de declaração de importação aplicável.")

    if _is_explicit_no(value("85")):
        mark(
            ["86"],
            "85",
            "85 indica que não há garantia, por isso fundamento legal não é necessário.",
        )

    return changes


def review_field_keys(state: ProcessState) -> list[str]:
    meta = (state.flags or {}).get(DAV_FIELD_META_FLAG) or {}
    dados_carro = state.dados_carro or {}

    needs_review = [
        field for field, info in meta.items()
        if field in dados_carro and info.get("status") == "needs_review" and not is_not_applicable(info)
    ]
    missing = [
        field for field, value in dados_carro.items()
        if not is_not_applicable(meta.get(field))
        and (_is_missing(value) or (meta.get(field) or {}).get("status") == "missing")
    ]

    return _dedupe([*needs_review, *missing])


def mark_candidate_conflicts(
    state: ProcessState,
    raw_insights: list[dict[str, Any]],
) -> None:
    if not raw_insights or not state.dados_carro:
        return

    meta = _ensure_meta_dict(state)
    candidates = extract_dav_candidates(raw_insights)
    code_index = _code_index(state.dados_carro)

    for kind, codes in KIND_TO_CODES.items():
        alternatives = _candidate_alternatives(kind, candidates.get(kind) or [])
        if len(alternatives) <= 1:
            continue

        for code in codes:
            field_key = code_index.get(code)
            if not field_key or _is_missing(state.dados_carro.get(field_key)):
                continue

            existing = meta.get(field_key) or {}
            if existing.get("origin") == "user":
                continue

            selected_key = candidate_key(kind, state.dados_carro.get(field_key))
            enriched = [
                {**alt, "selected": selected_key is not None and alt["key"] == selected_key}
                for alt in alternatives
            ]
            winner = _auto_resolve_candidate(alternatives, selected_key)
            if winner:
                winner_value = winner.get("value")
                state.dados_carro[field_key] = winner_value
                enriched = [
                    {
                        **alt,
                        "selected": alt["key"] == winner["key"],
                        "auto_selected": alt["key"] == winner["key"],
                    }
                    for alt in alternatives
                ]
                meta[field_key] = {
                    **existing,
                    "origin": existing.get("origin") if existing.get("origin") in {"induced", "user"} else "extracted",
                    "status": "filled",
                    "reason": _auto_resolved_reason(kind),
                    "source": "raw_insights_auto_resolved",
                    "value": winner_value,
                    "alternatives": enriched,
                }
                continue

            status = "conflict" if kind in HIGH_RISK_KINDS else "needs_review"
            origin = "conflict" if status == "conflict" else None
            reason = _conflict_reason(kind, status)

            meta[field_key] = {
                **existing,
                "origin": origin or existing.get("origin") or "extracted",
                "status": status,
                "reason": reason,
                "source": "raw_insights",
                "value": state.dados_carro.get(field_key),
                "alternatives": enriched,
            }


def _ensure_meta_dict(state: ProcessState) -> dict[str, dict[str, Any]]:
    state.flags = state.flags or {}
    raw = state.flags.setdefault(DAV_FIELD_META_FLAG, {})
    if not isinstance(raw, dict):
        raw = {}
        state.flags[DAV_FIELD_META_FLAG] = raw
    return raw


def _default_meta_for_value(value: Any) -> dict[str, Any]:
    if _is_missing(value):
        return {
            "origin": "missing",
            "status": "missing",
            "reason": "Field is empty",
            "value": None,
            "alternatives": [],
        }
    return {
        "origin": "extracted",
        "status": "filled",
        "reason": "Value from harmonized extraction",
        "source": "harmonized_extraction",
        "value": value,
        "alternatives": [],
    }


def _candidate_alternatives(kind: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in values:
        key = candidate_key(kind, item.get("value"))
        if not key:
            continue
        entry = grouped.setdefault(
            key,
            {
                "key": key,
                "value": candidate_display_value(kind, item.get("value")),
                "score": 0,
                "sources": [],
                "categories": [],
            },
        )
        entry["score"] += int(item.get("weight") or 1)
        _append_unique(entry["sources"], item.get("source"))
        _append_unique(entry["categories"], item.get("category"))

    return sorted(grouped.values(), key=lambda entry: (-entry["score"], str(entry["value"])))


def _auto_resolve_candidate(alternatives: list[dict[str, Any]], selected_key: str | None) -> dict[str, Any] | None:
    if not alternatives:
        return None

    selected = next((alt for alt in alternatives if selected_key is not None and alt["key"] == selected_key), None)
    if selected:
        return selected

    top = alternatives[0]
    if len(alternatives) == 1:
        return top
    second = alternatives[1]
    if int(top.get("score") or 0) > int(second.get("score") or 0):
        return top
    return None


def _auto_resolved_reason(kind: str) -> str:
    labels = {
        "vin": "VIN",
        "plate": "plate",
        "buyer_tax_id": "buyer/declarant tax id",
        "seller_tax_id": "seller tax id",
        "price": "price",
        "kilometers": "kilometers",
        "first_registration_date": "first registration date",
        "entry_date": "entry date",
        "invoice_date": "invoice date",
        "buyer_name": "buyer/declarant name",
        "seller_name": "seller name",
        "buyer_address": "buyer address",
        "seller_address": "seller address",
        "payment_method": "payment method",
    }
    return f"Auto-resolved {labels.get(kind, 'field')} from document candidates; alternatives kept for audit."


def _conflict_reason(kind: str, status: str) -> str:
    labels = {
        "vin": "Multiple VIN candidates found across source documents",
        "plate": "Multiple plate candidates found across source documents",
        "buyer_tax_id": "Multiple buyer/declarant tax id candidates found",
        "seller_tax_id": "Multiple seller tax id candidates found",
        "price": "Multiple price candidates found",
        "kilometers": "Multiple kilometer candidates found",
        "first_registration_date": "Multiple first registration date candidates found",
        "entry_date": "Multiple entry date candidates found",
        "invoice_date": "Multiple invoice date candidates found",
        "buyer_name": "Multiple buyer/declarant name candidates found",
        "seller_name": "Multiple seller name candidates found",
        "buyer_address": "Multiple buyer address candidates found",
        "seller_address": "Multiple seller address candidates found",
        "payment_method": "Multiple payment method candidates found",
    }
    suffix = "Requires confirmation" if status == "conflict" else "Please review when convenient"
    return f"{labels.get(kind, 'Multiple candidates found')}. {suffix}."


def _code_index(dados_carro: dict[str, Any]) -> dict[str, str]:
    return {key.split(":", 1)[0].strip(): key for key in dados_carro}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def _is_explicit_no(value: Any) -> bool:
    text = _norm(value)
    return text in {"nao", "n", "no", "false", "0"} or text.startswith("nao ") or " - nao" in text


def _is_blank_select(value: Any) -> bool:
    text = _norm(value)
    return _is_missing(value) or text in {"---", "--", "-", "nao aplicavel", "n/a"}


def _is_self_representation(value: Any) -> bool:
    text = _norm(value)
    return any(token in text for token in ("proprio", "dono", "consignatario", "owner", "self"))


def _is_particular(value: Any) -> bool:
    text = _norm(value)
    return "particular" in text or "singular" in text


def _is_own_transport(value: Any) -> bool:
    text = _norm(value)
    return any(token in text for token in ("proprios meios", "proprios", "own means", "pelos proprios"))


def _is_combustion_fuel(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return False
    electric_tokens = ("eletric", "electric", "hibrid", "hybrid", "plug", "phev", "bev")
    if any(token in text for token in electric_tokens):
        return False
    combustion_tokens = ("gasoleo", "diesel", "gasolina", "petrol", "gpl", "gnc", "fuel")
    return any(token in text for token in combustion_tokens)


def _is_eu_country(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return False
    eu_names = {
        "alemanha", "germany", "de", "belgica", "belgium", "be", "franca", "france", "fr",
        "espanha", "spain", "es", "italia", "italy", "it", "paises baixos", "netherlands", "nl",
        "luxemburgo", "luxembourg", "lu", "austria", "at", "dinamarca", "denmark", "dk",
        "suecia", "sweden", "se", "finlandia", "finland", "fi", "irlanda", "ireland", "ie",
        "polonia", "poland", "pl", "chequia", "czech", "cz", "eslovaquia", "slovakia", "sk",
        "eslovenia", "slovenia", "si", "hungria", "hungary", "hu", "croacia", "croatia", "hr",
        "romenia", "romania", "ro", "bulgaria", "bg", "grecia", "greece", "gr",
        "portugal", "pt", "estonia", "ee", "letonia", "latvia", "lv", "lituania", "lithuania", "lt",
        "malta", "mt", "chipre", "cyprus", "cy",
    }
    return text in eu_names or any(f" {name} " in f" {text} " for name in eu_names if len(name) > 2)


def _append_unique(target: list[Any], value: Any) -> None:
    if value and value not in target:
        target.append(value)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
