"""Normalização de texto e proteção de CSV."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    """Normaliza texto para busca sem perder o valor original armazenado."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", without_accents)).strip()


def normalize_username(value: str) -> str:
    """Normaliza nome de usuário sem alterar caracteres potencialmente válidos."""
    normalized = value.strip().lstrip("@").casefold()
    if not normalized:
        raise ValueError("Informe um nome de usuário.")
    if len(normalized) > 100 or not re.fullmatch(r"[\w.]+", normalized, flags=re.ASCII):
        raise ValueError("Nome de usuário inválido. Use letras, números, ponto ou sublinhado.")
    return normalized


def csv_safe(value: object) -> object:
    """Evita que exportações CSV sejam interpretadas como fórmulas por planilhas."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def find_terms(text: str | None, terms: list[str]) -> list[str]:
    """Encontra termos configurados, ignorando caixa, acentos e pontuação."""
    normalized = normalize_text(text)
    return [term for term in terms if normalize_text(term) and normalize_text(term) in normalized]
