from __future__ import annotations

import pytest

from prospector.analysis.ml_pipeline import train
from prospector.analysis.rule_scoring import assess_candidate
from prospector.database.backup import create_backup, maybe_create_automatic_backup, restore_backup


def test_rules_are_explainable(repo):
    candidate = repo.create_candidate({"username": "regras", "bio_text": "Faço publi e parcerias", "follower_count": 20000, "commercial_signals": ["faço publi"], "niche_tags": ["família"]})
    assessment = assess_candidate(candidate, repo.get_settings())
    assert assessment.score > 0
    assert assessment.eligibility == "atende ao mínimo"
    assert assessment.satisfied


def test_backup_and_restore(database, repo):
    repo.create_candidate({"username": "antes", "follower_count": 10000})
    backup = create_backup(database)
    repo.create_candidate({"username": "depois", "follower_count": 10000})
    with pytest.raises(ValueError):
        restore_backup(database, backup, confirmed=False)
    restore_backup(database, backup, confirmed=True)
    assert repo.count_candidates() == 1


def test_automatic_backup_creates_once_per_day(database):
    assert maybe_create_automatic_backup(database) is not None
    assert maybe_create_automatic_backup(database) is None


def test_ml_rejects_single_class(repo, paths):
    candidate = repo.create_candidate({"username": "positivo", "follower_count": 10000})
    repo.record_review(candidate["id"], "aprovar")
    with pytest.raises(ValueError, match="aprovação e uma rejeição"):
        train(repo.candidates_for_training(), paths)


def test_ml_trains_with_synthetic_labels(repo, paths):
    for index in range(8):
        candidate = repo.create_candidate({"username": f"ml_{index}", "follower_count": 12000 + index * 100, "bio_text": "Faço publi" if index % 2 else "bio comum", "commercial_signals": ["faço publi"] if index % 2 else []})
        repo.record_review(candidate["id"], "aprovar" if index % 2 else "rejeitar")
    result, model = train(repo.candidates_for_training(), paths)
    assert result.sample_count == 8
    assert result.artifact_path.endswith(".joblib")
    assert model.predict_proba([{"followers_log_bucket": 4, "has_followers": 1, "has_commercial_signal": 1, "bio_publicidade": 1, "has_niche_tags": 0, "source_type": "manual", "discovery_relation": "desconhecida", "verification_state": "pendente", "data_completeness": 2}]).shape == (1, 2)
