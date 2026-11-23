"""Preparação de mensagens sob controle humano."""

from __future__ import annotations

import re
from typing import Any

VARIABLE_PATTERN = re.compile(r"\{([a-z_]+)\}")
ALLOWED_VARIABLES = {"nome_publico", "nome_remetente", "usuario"}


def render_message(template: str, candidate: dict[str, Any], sender_name: str) -> str:
    """Renderiza somente variáveis explícitas e bloqueia valores ausentes."""
    variables = set(VARIABLE_PATTERN.findall(template))
    unsupported = variables - ALLOWED_VARIABLES
    if unsupported:
        raise ValueError("Modelo possui variáveis não permitidas: " + ", ".join(sorted(unsupported)))
    values = {
        "nome_publico": (candidate.get("display_name") or "").strip(),
        "nome_remetente": sender_name.strip(),
        "usuario": candidate.get("username_normalized", ""),
    }
    missing = [key for key in variables if not values.get(key)]
    if missing:
        raise ValueError("Preencha antes as variáveis: " + ", ".join(missing))
    return template.format(**values)
