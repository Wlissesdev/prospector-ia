from __future__ import annotations

import pytest

from prospector.services.import_service import import_csv, preview_csv
from prospector.utils.urls import analyze_url, normalize_http_url


def test_csv_preview_and_import(repo, paths):
    content = b"usuario,seguidores,bio\nperfil_a,12000,Fa\xc3\xa7o publi\nperfil_b,9000,\n"
    preview = preview_csv(content, "leads.csv")
    assert preview.mapped_columns["usuario"] == "username"
    result = import_csv(content, "leads.csv", preview.mapped_columns, repo, paths)
    assert result.valid_rows == 2
    assert repo.count_candidates() == 2


def test_csv_formula_in_identity_is_rejected(repo, paths):
    content = b"usuario\n=1+1\n"
    result = import_csv(content, "leads.csv", {"usuario": "username"}, repo, paths)
    assert result.invalid_rows == 1
    assert "fórmula" in result.errors[0]["mensagem"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "http://localhost:8501", "http://127.0.0.1:80", "http://10.0.0.1"])
def test_unsafe_urls_are_rejected(url):
    if url.startswith("http"):
        result = analyze_url(url)
        assert result.check_status == "bloqueado"
    else:
        with pytest.raises(ValueError):
            normalize_http_url(url)


def test_export_safety(repo):
    candidate = repo.create_candidate({"username": "safe_export", "notes": "=cmd()"})
    assert candidate["notes"] == "=cmd()"
