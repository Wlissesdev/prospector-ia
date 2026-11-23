"""Pontuação explicável por regras, independente do modelo estatístico."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from prospector.utils.text import find_terms


@dataclass(frozen=True)
class RuleAssessment:
    score: float
    eligibility: str
    compatibility: str
    satisfied: list[str]
    pending: list[str]
    excluded: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_candidate(
    candidate: dict[str, Any], settings: dict[str, Any], link_analyses: list[dict[str, Any]] | None = None
) -> RuleAssessment:
    """Explica critérios objetivos sem apresentar inferências como fatos."""
    links = link_analyses or []
    satisfied: list[str] = []
    pending: list[str] = []
    excluded: list[str] = []
    score = 0.0
    minimum = int(settings.get("minimum_followers", 10_000))
    followers = candidate.get("follower_count")
    if followers is None:
        pending.append("Contagem de seguidores não informada")
    elif followers >= minimum:
        satisfied.append(f"Seguidores no mínimo configurado ({minimum:,})")
        score += 35
    else:
        excluded.append(f"Seguidores abaixo do mínimo configurado ({minimum:,})")

    commercial_terms = find_terms(candidate.get("bio_text"), list(settings.get("positive_terms", [])))
    stored_signals = candidate.get("commercial_signals_json", [])
    all_signals = sorted(set(commercial_terms + stored_signals))
    if all_signals:
        satisfied.append("Sinais comerciais: " + ", ".join(all_signals[:4]))
        score += min(25, 10 + len(all_signals) * 5)
    else:
        pending.append("Sem sinais comerciais confirmados na bio ou em evidência")

    betting_links = [item for item in links if item.get("destination_category") in {"apostas", "cassino", "afiliado"}]
    if betting_links:
        satisfied.append("Há análise de link com categoria comercial relevante")
        score += 20
    elif links:
        pending.append("Links analisados sem categoria comercial relevante confirmada")
    else:
        pending.append("Nenhum link analisado")

    niche_terms = find_terms(candidate.get("bio_text"), list(settings.get("family_terms", [])))
    if candidate.get("niche_tags_json") or niche_terms:
        satisfied.append("Há etiquetas ou termos de nicho observáveis")
        score += 10
    else:
        pending.append("Nicho ainda não classificado")

    if candidate.get("do_not_contact"):
        excluded.append("Perfil marcado como não contatar")
    if candidate.get("contact_status") in {"contatado manualmente", "respondeu", "interessado"}:
        excluded.append("Já existe histórico de contato")
    if candidate.get("data_freshness") == "antiga":
        pending.append("Dados marcados como desatualizados")

    score = max(0.0, min(100.0, score))
    if excluded:
        eligibility = "bloqueada"
    elif followers is None:
        eligibility = "dados pendentes"
    elif followers >= minimum:
        eligibility = "atende ao mínimo"
    else:
        eligibility = "abaixo do mínimo"
    compatibility = "alta" if score >= 65 else "média" if score >= 35 else "baixa"
    return RuleAssessment(score, eligibility, compatibility, satisfied, pending, excluded)


def evidence_is_stale(timestamp: str | None, max_age_days: int) -> bool:
    """Indica dados antigos sem descartá-los."""
    if not timestamp:
        return True
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(UTC) - value).days > max_age_days
