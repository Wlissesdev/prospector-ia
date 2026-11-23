"""Fluxo de descoberta pela API oficial para uma fila local revisável."""

from __future__ import annotations

from typing import Any

from prospector.database.repository import DuplicateCandidateError, Repository
from prospector.integrations.official_instagram import InstagramGraphClient


def run_hashtag_discovery(
    hashtag: str,
    max_results: int,
    only_reels: bool,
    repository: Repository,
    client: InstagramGraphClient,
) -> dict[str, int]:
    """Registra mídia oficial e importa autores apenas quando o dado vier na resposta."""
    run_id = repository.start_discovery_run("Instagram Graph API", hashtag, "hashtag: mídia pública")
    imported_count = 0
    try:
        media_items = client.collect_hashtag_media(
            hashtag, max_results=max_results, only_reels=only_reels
        )
        for media in media_items:
            item_id = repository.add_discovery_item(run_id, media)
            username = media.get("username")
            if username:
                candidate_id, created = _import_author(repository, str(username), media, hashtag)
                repository.attach_discovery_item(item_id, candidate_id)
                imported_count += int(created)
        repository.finish_discovery_run(run_id, len(media_items), imported_count)
        return {"run_id": run_id, "media_count": len(media_items), "imported_candidates": imported_count}
    except Exception as exc:
        repository.finish_discovery_run(run_id, 0, imported_count, str(exc))
        raise


def associate_item_with_username(item: dict[str, Any], username: str, hashtag: str, repository: Repository) -> int:
    """Permite ao revisor associar manualmente o autor visto em uma mídia pública."""
    candidate_id, _ = _import_author(repository, username, item, hashtag)
    repository.attach_discovery_item(int(item["id"]), candidate_id)
    return candidate_id


def _import_author(repository: Repository, username: str, media: dict[str, Any], hashtag: str) -> tuple[int, bool]:
    existing = repository.find_candidate(username)
    if existing:
        candidate_id = int(existing["id"])
        created = False
    else:
        try:
            candidate = repository.create_candidate(
                {
                    "username": username,
                    "source_type": "integração autorizada",
                    "source_reference": f"hashtag #{hashtag.lstrip('#')}",
                    "discovery_relation": "pesquisa permitida",
                    "verification_state": "parcialmente verificado",
                }
            )
            candidate_id = int(candidate["id"])
            created = True
        except DuplicateCandidateError:
            existing = repository.find_candidate(username)
            if existing is None:
                raise
            candidate_id = int(existing["id"])
            created = False
    repository.add_evidence(
        candidate_id,
        {
            "evidence_type": "publicação",
            "source_type": "integração autorizada",
            "source_uri": media.get("permalink"),
            "raw_text": media.get("caption"),
            "observed_at": media.get("timestamp"),
            "verification_state": "confirmado",
            "reviewer_notes": f"Mídia retornada pela busca oficial da hashtag #{hashtag.lstrip('#')}.",
        },
    )
    return candidate_id, created
