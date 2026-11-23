from __future__ import annotations

import time
from pathlib import Path

from prospector.services.import_service import import_csv


def test_imports_one_thousand_synthetic_candidates(repo, paths):
    rows = ["usuario,seguidores,bio"] + [f"sintetico_{index},{10000 + index},dados sintéticos" for index in range(1000)]
    started = time.perf_counter()
    result = import_csv("\n".join(rows).encode(), "sinteticos.csv", {"usuario": "username", "seguidores": "follower_count", "bio": "bio_text"}, repo, paths)
    elapsed = time.perf_counter() - started
    assert result.valid_rows == 1000
    assert repo.count_candidates() == 1000
    assert elapsed < 20


def test_ui_declares_all_primary_pages():
    app_source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    for page in ("Visão geral", "Candidatos", "Descoberta oficial", "Perfis-semente", "Evidências e Links", "Fila de revisão", "Mensagens", "Aprendizado", "Relatórios", "Importação/exportação", "Configurações", "Diagnóstico"):
        assert page in app_source
