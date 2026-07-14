from __future__ import annotations

import hashlib
import html
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
INSTRUCTION_PATTERNS = (
    re.compile(r"ignore (?:(all|any|the|your) )?(previous|prior|above) instructions", re.I),
    re.compile(r"system\s*(message|prompt)", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"do not (tell|reveal|mention) (the )?(user|operator)", re.I),
    re.compile(r"(?:execute|run) (?:this|the following) (?:command|code)", re.I),
)


def clean_text(value: str, *, limit: int = 2000) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def content_hash(title: str, excerpt: str) -> str:
    normalized = clean_text(f"{title} {excerpt}", limit=10000).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def contains_suspicious_instructions(value: str) -> bool:
    return any(pattern.search(value) for pattern in INSTRUCTION_PATTERNS)


def text_similarity(left: str, right: str) -> float:
    left_clean = clean_text(left, limit=5000).casefold()
    right_clean = clean_text(right, limit=5000).casefold()
    if not left_clean or not right_clean:
        return 0.0
    left_tokens = set(re.findall(r"[\wæøåäö]{3,}", left_clean))
    right_tokens = set(re.findall(r"[\wæøåäö]{3,}", right_clean))
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_clean[:1500], right_clean[:1500]).ratio()
    if left_tokens and right_tokens:
        left_fuzzy = sum(max(SequenceMatcher(None, token, other).ratio() for other in right_tokens) for token in left_tokens) / len(left_tokens)
        right_fuzzy = sum(max(SequenceMatcher(None, token, other).ratio() for other in left_tokens) for token in right_tokens) / len(right_tokens)
        fuzzy = (left_fuzzy + right_fuzzy) / 2
    else:
        fuzzy = 0.0
    return round(jaccard * 0.45 + fuzzy * 0.35 + sequence * 0.20, 4)


def slugify(value: str, *, limit: int = 180) -> str:
    value = value.casefold().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:limit].rstrip("-") or "opportunity"


_COMPANY_SUFFIXES = re.compile(r"\b(as|asa|ans|da|sa|ab|aps|ltd|gmbh)\b\.?", re.IGNORECASE)


def job_fingerprint(employer: str | None, title: str | None) -> str | None:
    """Stable id for 'the same job on another board': normalized employer + title."""
    if not employer or not title:
        return None

    def norm(text: str) -> str:
        text = text.casefold()
        text = re.sub(r"\(.*?\)", " ", text)
        text = re.sub(r"\b\d{1,3}\s?%", " ", text)
        text = re.sub(r"[^\wæøå]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    company = re.sub(r"\s+", " ", _COMPANY_SUFFIXES.sub(" ", norm(employer))).strip()
    role = norm(title)
    if not company or not role:
        return None
    return hashlib.sha256(f"{company}|{role}".encode()).hexdigest()[:16]
