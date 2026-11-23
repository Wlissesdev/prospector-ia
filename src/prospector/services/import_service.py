"""Pré-visualização e importação CSV com validação e relatório de erros."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from prospector.config import AppPaths
from prospector.database.repository import DuplicateCandidateError, Repository

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 20_000
ALLOWED_EXTENSIONS = {".csv"}
KNOWN_COLUMNS = {
    "username": "username",
    "nome_de_usuario": "username",
    "usuario": "username",
    "profile_url": "profile_url",
    "url": "profile_url",
    "link": "profile_url",
    "display_name": "display_name",
    "nome": "display_name",
    "bio": "bio_text",
    "bio_text": "bio_text",
    "followers": "follower_count",
    "seguidores": "follower_count",
    "follower_count": "follower_count",
    "tags": "niche_tags",
    "nicho": "niche_tags",
    "notes": "notes",
    "notas": "notes",
}


@dataclass(frozen=True)
class ImportPreview:
    columns: list[str]
    mapped_columns: dict[str, str]
    sample: list[dict[str, str]]
    row_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportResult:
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    errors: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def preview_csv(content: bytes, filename: str) -> ImportPreview:
    """Lê CSV sem gravar nada, com tamanho e formato limitados."""
    _validate_file(filename, content)
    text = _decode_csv(content)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("O CSV precisa ter cabeçalho.")
    columns = [column.strip() for column in reader.fieldnames if column and column.strip()]
    if not columns:
        raise ValueError("O CSV não contém colunas válidas.")
    mapped = {column: KNOWN_COLUMNS[_key(column)] for column in columns if _key(column) in KNOWN_COLUMNS}
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_IMPORT_ROWS:
            raise ValueError(f"O arquivo excede o limite de {MAX_IMPORT_ROWS:,} linhas.")
        if len(rows) < 10:
            rows.append({key: (value or "")[:500] for key, value in row.items() if key})
    warnings = []
    if "username" not in mapped.values() and "profile_url" not in mapped.values():
        warnings.append("Nenhuma coluna foi reconhecida como nome de usuário ou URL de perfil.")
    unknown = [column for column in columns if column not in mapped]
    if unknown:
        warnings.append("Mapeie manualmente as colunas não reconhecidas antes de importar: " + ", ".join(unknown))
    return ImportPreview(columns, mapped, rows, index if 'index' in locals() else 0, warnings)


def import_csv(
    content: bytes,
    filename: str,
    column_mapping: dict[str, str],
    repository: Repository,
    paths: AppPaths,
) -> ImportResult:
    """Importa linhas válidas preservando o arquivo de origem em pasta controlada."""
    _validate_file(filename, content)
    if "username" not in column_mapping.values() and "profile_url" not in column_mapping.values():
        raise ValueError("Mapeie uma coluna para Nome de usuário ou URL de perfil.")
    saved_path = _save_import_copy(content, filename, paths)
    reader = csv.DictReader(io.StringIO(_decode_csv(content)))
    valid = invalid = duplicates = 0
    errors: list[dict[str, Any]] = []
    with repository.database.transaction() as connection:
        for number, row in enumerate(reader, start=2):
            if number > MAX_IMPORT_ROWS + 1:
                break
            try:
                payload = _row_to_payload(row, column_mapping)
                repository.create_candidate_in_transaction(connection, payload)
                valid += 1
            except DuplicateCandidateError as exc:
                duplicates += 1
                errors.append({"linha": number, "tipo": "duplicado", "mensagem": str(exc)})
            except (ValueError, KeyError) as exc:
                invalid += 1
                errors.append({"linha": number, "tipo": "inválido", "mensagem": str(exc)})
    repository.record_import(filename, str(saved_path), valid, invalid, duplicates, errors)
    return ImportResult(valid, invalid, duplicates, errors)


def _validate_file(filename: str, content: bytes) -> None:
    suffix = Path(filename).suffix.casefold()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Envie um arquivo CSV.")
    if not content:
        raise ValueError("O arquivo está vazio.")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("O arquivo excede o limite de 10 MB.")


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não foi possível ler a codificação do CSV.")


def _key(value: str) -> str:
    return value.strip().casefold().replace(" ", "_")


def _row_to_payload(row: dict[str, str | None], mapping: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {"source_type": "CSV"}
    for source, target in mapping.items():
        value = (row.get(source) or "").strip()
        if value.startswith(("=", "+", "-", "@")) and target in {"username", "profile_url"}:
            raise ValueError("O campo de identificação não pode começar com fórmula de planilha.")
        if target == "niche_tags":
            payload[target] = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
        else:
            payload[target] = value
    if not payload.get("username") and payload.get("profile_url"):
        payload["username"] = _username_from_url(str(payload["profile_url"]))
    return payload


def _username_from_url(url: str) -> str:
    from urllib.parse import urlparse

    components = [part for part in urlparse(url).path.split("/") if part]
    if not components:
        raise ValueError("Não foi possível identificar o nome de usuário pela URL.")
    return components[0]


def _save_import_copy(content: bytes, filename: str, paths: AppPaths) -> Path:
    safe_name = Path(filename).name
    digest = hashlib.sha256(content).hexdigest()[:12]
    destination = paths.imports / f"{digest}-{safe_name}"
    destination.write_bytes(content)
    return destination
