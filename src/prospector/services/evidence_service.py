"""Armazenamento seguro de evidências fornecidas pelo usuário."""

from __future__ import annotations

import hashlib
from pathlib import Path

from prospector.config import AppPaths
from prospector.database.repository import Repository

MAX_EVIDENCE_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def save_uploaded_evidence(candidate_id: int, filename: str, content: bytes, repository: Repository, paths: AppPaths) -> dict:
    """Salva uma imagem fornecida pelo usuário sem executar ou interpretar arquivos."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Envie PNG, JPG, JPEG ou WEBP.")
    if not content or len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError("A captura deve ter entre 1 byte e 12 MB.")
    digest = hashlib.sha256(content).hexdigest()
    directory = paths.evidence / str(candidate_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest[:16]}{suffix}"
    if not destination.exists():
        destination.write_bytes(content)
    return repository.add_evidence(candidate_id, {
        "evidence_type": "captura de tela",
        "source_type": "captura fornecida pelo usuário",
        "evidence_file_path": str(destination),
        "content_hash": digest,
        "verification_state": "pendente",
        "reviewer_notes": "A imagem foi fornecida pelo usuário. OCR não é executado por padrão.",
    })
