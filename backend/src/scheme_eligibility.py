from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypedDict

SCHEME_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "schemes.json"

SUPPORTED_SCHEMES = {"PMJDY", "PMSBY", "PMJJBY", "APY", "SSY"}
LOCAL_DATA_STATUS = "local_curated_dataset"


class SchemeEligibilityAnswers(TypedDict, total=False):
    age: int
    age_group: str
    occupation_category: str
    residency_status: str
    state_or_union_territory: str
    is_girl_child_scheme: bool
    is_girl_child: bool

SENSITIVE_FIELD_NAMES = {
    "aadhaar",
    "aadhaar_number",
    "account_balance",
    "account_number",
    "atm_pin",
    "bank_account",
    "bank_account_number",
    "card_number",
    "cvv",
    "ifsc",
    "loan_account_number",
    "otp",
    "pan",
    "pan_number",
    "password",
    "pin",
    "phone_number",
    "policy_number",
    "transaction_id",
    "upi_pin",
}

ALLOWED_ANSWER_KEYS = {
    "age",
    "age_group",
    "occupation_category",
    "residency_status",
    "state_or_union_territory",
    "is_girl_child_scheme",
    "is_girl_child",
}

AGE_GROUPS = {
    "under_10",
    "10_to_17",
    "18_to_40",
    "18_to_50",
    "18_to_70",
    "unknown",
}

RESIDENCY_STATUSES = {
    "india",
    "indian_resident",
    "resident_of_india",
    "india_resident",
    "in_india",
    "unknown",
}

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b\d{12}\b"),
    re.compile(r"\b\d{16,18}\b"),
    re.compile(r"\b\d{6}\b"),
    re.compile(r"\b\d{3,4}\b"),
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
)


def _normalize_scheme_id(scheme_id: str) -> str:
    candidate = scheme_id.strip().upper() if isinstance(scheme_id, str) else ""
    if candidate not in SUPPORTED_SCHEMES:
        raise ValueError("Unsupported scheme")
    return candidate


def _load_dataset() -> list[dict[str, Any]]:
    raw = SCHEME_DATA_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Dataset must be a list")
    return [record for record in parsed if isinstance(record, dict)]


def _normalize_text(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _validate_answers(answers: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(answers, dict):
        raise ValueError("answers must be a dictionary")

    invalid_keys = set()
    for key in answers:
        normalized_key = key.strip().lower() if isinstance(key, str) else ""
        if not normalized_key or normalized_key in SENSITIVE_FIELD_NAMES:
            invalid_keys.add(key)
            continue
        if normalized_key not in ALLOWED_ANSWER_KEYS:
            invalid_keys.add(key)
            continue

    if invalid_keys:
        raise ValueError("Unsupported or sensitive answer field")

    normalized_answers: dict[str, Any] = {}
    for key, value in answers.items():
        normalized_key = key.strip().lower()
        if normalized_key == "age":
            if isinstance(value, bool):
                raise ValueError("Invalid age")
            if isinstance(value, int):
                age = value
            elif isinstance(value, str) and value.strip().isdigit():
                age = int(value.strip())
            else:
                raise ValueError("Invalid age")
            if age < 0 or age > 120:
                raise ValueError("Invalid age")
            normalized_answers[normalized_key] = age
            continue

        if normalized_key == "age_group":
            age_group = _normalize_text(value)
            if age_group and age_group not in AGE_GROUPS:
                raise ValueError("Invalid age_group")
            normalized_answers[normalized_key] = age_group or None
            continue

        if normalized_key in {"is_girl_child_scheme", "is_girl_child"}:
            if isinstance(value, bool):
                normalized_answers[normalized_key] = value
            elif isinstance(value, int) and value in {0, 1}:
                normalized_answers[normalized_key] = bool(value)
            elif isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "y", "1"}:
                    normalized_answers[normalized_key] = True
                elif lowered in {"false", "no", "n", "0"}:
                    normalized_answers[normalized_key] = False
                else:
                    raise ValueError("Invalid girl-child scheme answer")
            else:
                raise ValueError("Invalid girl-child scheme answer")
            continue

        if normalized_key == "residency_status":
            residency_status = _normalize_text(value)
            if residency_status and residency_status not in RESIDENCY_STATUSES:
                raise ValueError("Invalid residency_status")
            normalized_answers[normalized_key] = residency_status or None
            continue

        if normalized_key in {"occupation_category", "state_or_union_territory"}:
            text = value.strip() if isinstance(value, str) else ""
            if not text:
                raise ValueError(f"Invalid {normalized_key}")
            normalized_answers[normalized_key] = text
            continue

    sensitive_hits: list[str] = []
    for key, value in normalized_answers.items():
        if isinstance(value, str):
            candidate = value.strip()
            if any(pattern.search(candidate) for pattern in SENSITIVE_VALUE_PATTERNS):
                sensitive_hits.append(key)

    if sensitive_hits:
        raise ValueError("Sensitive data detected")

    return normalized_answers


def _rule_matches(rule: dict[str, Any], answers: dict[str, Any]) -> tuple[bool | None, str]:
    field = rule.get("field")
    rule_type = rule.get("type")
    message = rule.get("message") or "General guidance matches the available rule."
    if not isinstance(field, str) or not isinstance(rule_type, str):
        return None, message

    value = answers.get(field)
    if value is None:
        return None, message

    if rule_type == "equals_any":
        allowed = rule.get("values")
        if not isinstance(allowed, list):
            return None, message
        if isinstance(value, str):
            result = value.strip().lower() in {str(item).strip().lower() for item in allowed}
        elif isinstance(value, bool):
            result = value in allowed
        else:
            result = value in allowed
        return result, message

    if rule_type == "minimum":
        minimum = rule.get("value")
        if not isinstance(minimum, int) or not isinstance(value, int):
            return None, message
        return value >= minimum, message

    if rule_type == "maximum":
        maximum = rule.get("value")
        if not isinstance(maximum, int) or not isinstance(value, int):
            return None, message
        return value <= maximum, message

    if rule_type == "range":
        minimum = rule.get("minimum")
        maximum = rule.get("maximum")
        if not all(isinstance(bound, int) for bound in (minimum, maximum)) or not isinstance(
            value, int
        ):
            return None, message
        return minimum <= value <= maximum, message

    if rule_type == "required_true":
        if not isinstance(value, bool):
            return None, message
        return value is True, message

    return None, message


def _next_steps(record: dict[str, Any], result: str) -> list[str]:
    if result == "appears_unlikely":
        return [
            "This is only general guidance; please confirm the final answer through the official source or participating bank.",
        ]

    steps = record.get("next_steps")
    if isinstance(steps, list) and steps:
        return [str(step) for step in steps if isinstance(step, str)]

    return [
        "Confirm current eligibility through the official source or participating bank.",
    ]


def check_scheme_eligibility(scheme_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    """Check general, non-binding eligibility guidance for a supported scheme.

    This helper works on non-sensitive answers voluntarily provided by the caller.
    It should be used only for general eligibility guidance, commonly required
    documents, and next steps for supported Indian government financial schemes.
    It must not be used for account status, approval confirmation, transaction
    status, loan decisions, personalized investment advice, or requests involving
    OTPs, PINs, passwords, card details, account numbers, Aadhaar, PAN, or other
    sensitive identifiers.

    The result is informational only and includes dated source information.
    """
    try:
        normalized_scheme_id = _normalize_scheme_id(scheme_id)
    except ValueError:
        return {
            "success": False,
            "scheme_id": scheme_id,
            "result": "scheme_not_found",
            "matched_rules": [],
            "missing_answers": [],
            "document_checklist": [],
            "next_steps": [
                "Please verify the exact scheme name through the official government portal.",
            ],
            "source_name": "myScheme",
            "source_url": "https://www.myscheme.gov.in/",
            "data_status": LOCAL_DATA_STATUS,
            "retrieved_at": None,
            "last_verified": None,
            "effective_from": None,
            "disclaimer": "This is general guidance, not official approval.",
            "spoken_response": (
                "मुझे इस नाम की verified scheme information नहीं मिली। कृपया scheme का exact name"
                " बताइए या official government portal पर verify करें।"
            ),
        }

    try:
        validated_answers = _validate_answers(answers)
    except ValueError:
        return {
            "success": False,
            "scheme_id": normalized_scheme_id,
            "result": "validation_error",
            "matched_rules": [],
            "missing_answers": [],
            "document_checklist": [],
            "next_steps": [
                "Please share only non-sensitive general information such as age, state, or residency status.",
            ],
            "source_name": "myScheme",
            "source_url": "https://www.myscheme.gov.in/",
            "data_status": LOCAL_DATA_STATUS,
            "retrieved_at": None,
            "last_verified": None,
            "effective_from": None,
            "disclaimer": "This is general guidance, not official approval.",
            "spoken_response": (
                "मैं केवल general, non-sensitive information से eligibility guidance दे सकती हूं।"
                " कृपया OTP, PIN, password, CVV, account number, Aadhaar या PAN details share न करें।"
            ),
        }

    try:
        dataset = _load_dataset()
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "success": False,
            "scheme_id": normalized_scheme_id,
            "result": "source_unavailable",
            "matched_rules": [],
            "missing_answers": [],
            "document_checklist": [],
            "next_steps": [
                "Official scheme data is temporarily unavailable; please verify through the official government portal or participating bank.",
            ],
            "source_name": "myScheme",
            "source_url": "https://www.myscheme.gov.in/",
            "data_status": LOCAL_DATA_STATUS,
            "retrieved_at": None,
            "last_verified": None,
            "effective_from": None,
            "disclaimer": "This is general guidance, not official approval.",
            "spoken_response": (
                "इस समय scheme data उपलब्ध नहीं है। मैं अनुमान लगाकर जवाब नहीं दूंगी। कृपया official"
                " government portal या bank branch से जानकारी verify करें।"
            ),
        }

    record = next(
        (
            item
            for item in dataset
            if _normalize_text(item.get("scheme_id")) == normalized_scheme_id.lower()
        ),
        None,
    )

    if record is None:
        return {
            "success": False,
            "scheme_id": normalized_scheme_id,
            "result": "scheme_not_found",
            "matched_rules": [],
            "missing_answers": [],
            "document_checklist": [],
            "next_steps": [
                "Please verify the exact scheme name through the official government portal.",
            ],
            "source_name": "myScheme",
            "source_url": "https://www.myscheme.gov.in/",
            "data_status": LOCAL_DATA_STATUS,
            "retrieved_at": None,
            "last_verified": None,
            "effective_from": None,
            "disclaimer": "This is general guidance, not official approval.",
            "spoken_response": (
                "मुझे इस नाम की verified scheme information नहीं मिली। कृपया scheme का exact name"
                " बताइए या official government portal पर verify करें।"
            ),
        }

    scheme_name = record.get("scheme_name") or normalized_scheme_id
    eligibility_rules = record.get("eligibility_rules", {})
    if isinstance(eligibility_rules, dict):
        required_fields = eligibility_rules.get("required_answer_keys", [])
        known_rules = eligibility_rules.get("known_rules", [])
    else:
        required_fields = []
        known_rules = []
    if not isinstance(required_fields, list):
        required_fields = []
    if not isinstance(known_rules, list):
        known_rules = []

    missing_answers = [
        field for field in required_fields if field not in validated_answers or validated_answers[field] in {None, ""}
    ]

    matched_rules: list[str] = []
    unmatched_rules: list[str] = []

    for rule in known_rules:
        if not isinstance(rule, dict):
            continue
        result, message = _rule_matches(rule, validated_answers)
        if result is True:
            matched_rules.append(message)
        elif result is False:
            unmatched_rules.append(message)

    if unmatched_rules:
        final_result = "appears_unlikely"
    elif missing_answers:
        final_result = "needs_more_information"
    else:
        final_result = "appears_possible"

    document_checklist = record.get("document_checklist")
    if not isinstance(document_checklist, list):
        document_checklist = []

    source_name = record.get("source_name") or "myScheme"
    source_url = record.get("source_url") or "https://www.myscheme.gov.in/"
    retrieved_at = record.get("retrieved_at")
    last_verified = record.get("last_verified")
    effective_from = record.get("effective_from")

    return {
        "success": True,
        "scheme_id": normalized_scheme_id.lower(),
        "scheme_name": scheme_name,
        "result": final_result,
        "matched_rules": matched_rules or [
            "The provided general information matches the available rules.",
        ],
        "missing_answers": missing_answers,
        "unmatched_rules": unmatched_rules,
        "document_checklist": document_checklist,
        "next_steps": _next_steps(record, final_result),
        "source_name": source_name,
        "source_url": source_url,
        "data_status": record.get("data_status") or LOCAL_DATA_STATUS,
        "retrieved_at": retrieved_at,
        "last_verified": last_verified,
        "effective_from": effective_from,
        "disclaimer": "This is general guidance, not official approval.",
        "spoken_response": {
            "appears_possible": (
                "आपके द्वारा दी गई सामान्य जानकारी के आधार पर, यह स्कीम आपके लिए संभव हो सकती है।"
                " यह official approval नहीं है। कृपया final eligibility official government portal या"
                " participating bank से verify करें।"
            ),
            "appears_unlikely": (
                "आपके द्वारा दी गई जानकारी के आधार पर, यह स्कीम शायद match नहीं करती। Final"
                " confirmation official source या concerned bank ही दे सकता है।"
            ),
            "needs_more_information": (
                "Eligibility समझने के लिए मुझे एक और सामान्य जानकारी चाहिए। आपकी state या Union"
                " Territory कौन-सी है?"
            ),
            "scheme_not_found": (
                "मुझे इस नाम की verified scheme information नहीं मिली। कृपया scheme का exact name"
                " बताइए या official government portal पर verify करें।"
            ),
            "source_unavailable": (
                "इस समय scheme data उपलब्ध नहीं है। मैं अनुमान लगाकर जवाब नहीं दूंगी। कृपया official"
                " government portal या bank branch से जानकारी verify करें।"
            ),
            "validation_error": (
                "मैं केवल general, non-sensitive information से eligibility guidance दे सकती हूं।"
                " कृपया OTP, PIN, password, CVV, account number, Aadhaar या PAN details share न करें।"
            ),
        }[final_result],
    }
