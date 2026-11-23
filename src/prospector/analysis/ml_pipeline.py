"""Aprendizado supervisionado local, reproduzível e explicável."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from prospector.config import AppPaths


@dataclass(frozen=True)
class TrainingResult:
    model_version: str
    artifact_path: str
    sample_count: int
    positive_count: int
    negative_count: int
    validation_method: str
    metrics: dict[str, float | str]
    selected_algorithm: str


def candidate_features(candidate: dict[str, Any]) -> dict[str, Any]:
    """Extrai somente atributos observáveis, sem inferir dados sensíveis."""
    followers = candidate.get("follower_count") or 0
    bio = (candidate.get("bio_text") or "").casefold()
    return {
        "followers_log_bucket": min(6, len(str(max(followers, 1)))),
        "has_followers": int(candidate.get("follower_count") is not None),
        "has_commercial_signal": int(bool(candidate.get("commercial_signals_json"))),
        "bio_publicidade": int(any(term in bio for term in ("publicidade", "parceria", "publi", "comercial"))),
        "has_niche_tags": int(bool(candidate.get("niche_tags_json"))),
        "source_type": candidate.get("source_type") or "desconhecida",
        "discovery_relation": candidate.get("discovery_relation") or "desconhecida",
        "verification_state": candidate.get("verification_state") or "pendente",
        "data_completeness": sum(value is not None and value != "" for value in (candidate.get("bio_text"), candidate.get("follower_count"), candidate.get("profile_url"))),
    }


def train(candidates: list[dict[str, Any]], paths: AppPaths) -> tuple[TrainingResult, Pipeline]:
    """Treina modelos locais depois de validar quantidade e diversidade de rótulos."""
    labels = [1 if candidate["review_status"] == "aprovado" else 0 for candidate in candidates]
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("O modelo precisa de ao menos uma aprovação e uma rejeição.")
    if len(labels) < 8 or min(positives, negatives) < 3:
        raise ValueError("São necessários pelo menos 8 rótulos e 3 exemplos de cada classe para treinar.")
    features = [candidate_features(candidate) for candidate in candidates]
    logistic = Pipeline([("vectorizer", DictVectorizer(sparse=True)), ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42))])
    tree = Pipeline([("vectorizer", DictVectorizer(sparse=True)), ("classifier", DecisionTreeClassifier(max_depth=5, min_samples_leaf=2, class_weight="balanced", random_state=42))])
    folds = min(5, positives, negatives)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    logistic_f1 = float(cross_val_score(logistic, features, labels, cv=splitter, scoring="f1").mean())
    tree_f1 = float(cross_val_score(tree, features, labels, cv=splitter, scoring="f1").mean())
    selected = logistic if logistic_f1 >= tree_f1 else tree
    selected_name = "regressão logística" if selected is logistic else "árvore de decisão"
    selected.fit(features, labels)
    prediction = selected.predict(features)
    probability = selected.predict_proba(features)[:, 1]
    precision, recall, f1, _ = precision_recall_fscore_support(labels, prediction, average="binary", zero_division=0)
    metrics: dict[str, float | str] = {
        "f1_validação_regressão_logística": round(logistic_f1, 4),
        "f1_validação_árvore": round(tree_f1, 4),
        "precision_treino": round(float(precision), 4),
        "recall_treino": round(float(recall), 4),
        "f1_treino": round(float(f1), 4),
        "pr_auc_treino": round(float(average_precision_score(labels, probability)), 4),
        "aviso": "As métricas de treino são apenas diagnósticas. Use a F1 de validação para comparar modelos.",
    }
    version_payload = repr([(candidate["id"], candidate["review_status"], candidate.get("updated_at")) for candidate in candidates]).encode()
    version = "modelo-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(version_payload).hexdigest()[:8]
    destination = paths.models / f"{version}.joblib"
    joblib.dump({"pipeline": selected, "version": version, "algorithm": selected_name}, destination)
    result = TrainingResult(version, str(destination), len(labels), positives, negatives, f"validação cruzada estratificada ({folds} dobras)", metrics, selected_name)
    return result, selected


def score_candidates(model: Pipeline, candidates: list[dict[str, Any]]) -> list[tuple[int, float, str]]:
    """Gera prioridade para revisão; não altera decisão humana ou opt-out."""
    if not candidates:
        return []
    probabilities = model.predict_proba([candidate_features(candidate) for candidate in candidates])[:, 1]
    results: list[tuple[int, float, str]] = []
    for candidate, value in zip(candidates, probabilities, strict=True):
        features = candidate_features(candidate)
        reasons = []
        if features["has_commercial_signal"]:
            reasons.append("sinais comerciais registrados")
        if features["has_followers"]:
            reasons.append("contagem de seguidores disponível")
        if features["has_niche_tags"]:
            reasons.append("etiquetas de nicho registradas")
        explanation = "Sinais disponíveis: " + (", ".join(reasons) if reasons else "dados ainda incompletos")
        results.append((int(candidate["id"]), round(float(value), 4), explanation))
    return results


def load_active_model(artifact_path: str) -> Pipeline:
    """Carrega somente artefato salvo pela aplicação na pasta de modelos."""
    content = joblib.load(Path(artifact_path))
    return content["pipeline"]
