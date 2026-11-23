from __future__ import annotations

import pytest

from prospector.database.repository import ContactBlockedError, DuplicateCandidateError
from prospector.services.outreach_service import render_message


def create_candidate(repo, username="criadora.teste", followers=15000):
    return repo.create_candidate({"username": username, "display_name": "Criadora", "bio_text": "Faço publi e parcerias", "follower_count": followers, "commercial_signals": ["faço publi"], "source_type": "manual"})


def test_candidate_persists_and_duplicate_is_blocked(repo):
    candidate = create_candidate(repo)
    assert repo.get_candidate(candidate["id"])["username_normalized"] == "criadora.teste"
    with pytest.raises(DuplicateCandidateError):
        create_candidate(repo)


def test_review_history_and_opt_out_blocks_contact(repo):
    candidate = create_candidate(repo)
    repo.record_review(candidate["id"], "não contatar", "opt_out", "Pediu para não receber contato")
    assert repo.get_candidate(candidate["id"])["do_not_contact"] == 1
    assert repo.review_events(candidate["id"])[0]["reviewer_action"] == "não contatar"
    template = repo.list_templates()[0]
    with pytest.raises(ContactBlockedError):
        repo.prepare_outreach(candidate["id"], template["id"], "Olá")


def test_message_is_prepared_before_manual_contact(repo):
    candidate = create_candidate(repo)
    template = repo.list_templates()[0]
    message = render_message(template["body"], candidate, "Ana")
    draft = repo.prepare_outreach(candidate["id"], template["id"], message)
    assert draft["status"] == "rascunho"
    assert draft["sent_at"] is None
    repo.record_manual_contact(draft["id"])
    assert repo.get_outreach(draft["id"])["status"] == "enviado manualmente"


def test_evidence_and_seed_relation(repo):
    seed = create_candidate(repo, "semente")
    child = create_candidate(repo, "derivada")
    evidence = repo.add_evidence(child["id"], {"evidence_type": "Story", "source_type": "texto colado", "raw_text": "link visível", "verification_state": "pendente"})
    repo.create_seed_relation(seed["id"], child["id"], "sugestão observada")
    assert evidence["candidate_id"] == child["id"]
    assert repo.seed_stats()[0]["derived_count"] == 1


def test_soft_delete_requires_confirmation_and_can_be_restored(repo):
    candidate = create_candidate(repo, "arquivar")
    with pytest.raises(ValueError):
        repo.soft_delete_candidate(candidate["id"], confirmed=False)
    repo.soft_delete_candidate(candidate["id"], confirmed=True)
    assert repo.count_candidates() == 0
    repo.restore_candidate(candidate["id"])
    assert repo.count_candidates() == 1


def test_batch_review_and_human_link_correction(repo):
    candidate = create_candidate(repo, "lote")
    link = repo.add_link_analysis(candidate["id"], {"original_url": "https://example.com", "destination_category": "desconhecido", "check_status": "concluído"})
    assert repo.move_to_review([candidate["id"]]) == 1
    assert repo.get_candidate(candidate["id"])["review_status"] == "pendente"
    repo.correct_link_category(link["id"], "comércio", "site institucional")
    assert repo.list_link_analyses(candidate["id"])[0]["destination_category"] == "comércio"
