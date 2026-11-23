"""Backup e restauração explícita do SQLite local."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from prospector.database.engine import Database
from prospector.database.repository import Repository


def create_backup(database: Database) -> Path:
    """Cria uma cópia consistente usando a API nativa de backup do SQLite."""
    destination = database.paths.backups / f"prospector-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.sqlite3"
    source_connection = database.connect()
    import sqlite3

    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        check = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError("O backup não passou na verificação de integridade.")
    finally:
        destination_connection.close()
        source_connection.close()
    _retain_backups(database)
    return destination


def restore_backup(database: Database, source: Path, confirmed: bool) -> Path:
    """Restaura somente após confirmação explícita e preserva cópia do banco atual."""
    if not confirmed:
        raise ValueError("Confirme a restauração para substituir o banco atual.")
    source = source.resolve()
    backups_root = database.paths.backups.resolve()
    if backups_root not in source.parents or source.suffix != ".sqlite3":
        raise ValueError("Escolha um backup criado pelo Prospector IA.")
    safety_copy = create_backup(database)
    # Consolida e remove apenas os arquivos WAL controlados desta base. O
    # arquivo principal continua aberto somente pelas conexões curtas do método.
    _checkpoint_and_remove_wal(database)
    import sqlite3

    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(database.paths.database)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    _checkpoint_and_remove_wal(database)
    if database.integrity_check() != "ok":
        _checkpoint_and_remove_wal(database)
        source_connection = sqlite3.connect(safety_copy)
        destination_connection = sqlite3.connect(database.paths.database)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        _checkpoint_and_remove_wal(database)
        raise RuntimeError("A restauração falhou na verificação de integridade; o banco anterior foi preservado.")
    return safety_copy


def maybe_create_automatic_backup(database: Database, max_age_hours: int = 24) -> Path | None:
    """Cria um backup diário na abertura sem substituir cópias existentes."""
    latest = database.latest_backup()
    if latest is None:
        return create_backup(database)
    age_seconds = datetime.now(UTC).timestamp() - latest.stat().st_mtime
    if age_seconds >= max_age_hours * 3600:
        return create_backup(database)
    return None


def _retain_backups(database: Database) -> None:
    settings = Repository(database).get_settings()
    retention = max(1, int(settings.get("backup_retention", 10)))
    for backup in sorted(database.paths.backups.glob("prospector-*.sqlite3"), reverse=True)[retention:]:
        backup.unlink()


def _checkpoint_and_remove_wal(database: Database) -> None:
    with database.read_connection() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for target in (Path(str(database.paths.database) + "-wal"), Path(str(database.paths.database) + "-shm")):
        if target.exists():
            target.unlink()

