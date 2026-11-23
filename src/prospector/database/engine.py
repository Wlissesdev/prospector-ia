"""Esquema SQLite versionado e conexão transacional."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from prospector.config import DEFAULT_SETTINGS, AppPaths

SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Abre conexões curtas com integridade referencial e migração controlada."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure_exists()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Fecha conexões de leitura para não reter arquivos WAL no Windows."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Cria a versão inicial sem apagar ou alterar dados existentes."""
        with self.transaction() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            current = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
            if current > SCHEMA_VERSION:
                raise RuntimeError("O banco foi criado por uma versão mais nova do Prospector IA.")
            if current < 1:
                self._migration_1(connection)
                connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (1, utc_now()))
            if current < 2:
                self._migration_2(connection)
                connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (2, utc_now()))
            for key, value in DEFAULT_SETTINGS.items():
                connection.execute("INSERT OR IGNORE INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)", (key, json.dumps(value, ensure_ascii=False), utc_now()))
            self._ensure_default_templates(connection)

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE candidates (
                id INTEGER PRIMARY KEY,
                platform TEXT NOT NULL DEFAULT 'instagram',
                username_normalized TEXT NOT NULL,
                profile_url TEXT,
                display_name TEXT,
                bio_text TEXT,
                follower_count INTEGER,
                following_count INTEGER,
                post_count INTEGER,
                account_type TEXT NOT NULL DEFAULT 'desconhecido',
                profile_category TEXT,
                commercial_signals_json TEXT NOT NULL DEFAULT '[]',
                niche_tags_json TEXT NOT NULL DEFAULT '[]',
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_reference TEXT,
                discovery_relation TEXT NOT NULL DEFAULT 'desconhecida',
                first_seen_at TEXT NOT NULL,
                last_checked_at TEXT,
                data_freshness TEXT NOT NULL DEFAULT 'desconhecida',
                verification_state TEXT NOT NULL DEFAULT 'pendente',
                review_status TEXT NOT NULL DEFAULT 'novo',
                ml_score REAL,
                ml_model_version TEXT,
                ml_explanation TEXT,
                contact_status TEXT NOT NULL DEFAULT 'não contatado',
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, username_normalized)
            );
            CREATE INDEX idx_candidates_review ON candidates(review_status, deleted_at);
            CREATE INDEX idx_candidates_contact ON candidates(contact_status, do_not_contact);
            CREATE TABLE evidence (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                evidence_type TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_uri TEXT,
                captured_at TEXT NOT NULL,
                observed_at TEXT,
                raw_text TEXT,
                extracted_text TEXT,
                normalized_text TEXT,
                evidence_file_path TEXT,
                content_hash TEXT,
                verification_state TEXT NOT NULL DEFAULT 'pendente',
                confidence REAL,
                reviewer_decision TEXT,
                reviewer_notes TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_evidence_candidate ON evidence(candidate_id, created_at DESC);
            CREATE TABLE link_analyses (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                evidence_id INTEGER REFERENCES evidence(id),
                original_url TEXT NOT NULL,
                final_url TEXT,
                redirect_chain_json TEXT NOT NULL DEFAULT '[]',
                final_domain TEXT,
                http_status INTEGER,
                page_title TEXT,
                visible_text TEXT,
                destination_category TEXT NOT NULL DEFAULT 'desconhecido',
                classification_method TEXT,
                confidence REAL,
                checked_at TEXT NOT NULL,
                check_status TEXT NOT NULL,
                error_code TEXT,
                explanation TEXT,
                review_status TEXT NOT NULL DEFAULT 'pendente'
            );
            CREATE TABLE seed_relations (
                id INTEGER PRIMARY KEY,
                seed_candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                discovered_candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                relation_type TEXT NOT NULL,
                source_evidence_id INTEGER REFERENCES evidence(id),
                observed_at TEXT NOT NULL,
                user_confirmed INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                UNIQUE(seed_candidate_id, discovered_candidate_id, relation_type)
            );
            CREATE TABLE review_events (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                reviewer_action TEXT NOT NULL,
                reason_code TEXT,
                reason_text TEXT,
                features_snapshot_json TEXT NOT NULL,
                model_version_at_decision TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE message_templates (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL,
                variables_json TEXT NOT NULL DEFAULT '[]',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE outreach (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                channel TEXT NOT NULL DEFAULT 'instagram',
                template_id INTEGER REFERENCES message_templates(id),
                message_draft TEXT NOT NULL,
                message_sent_text TEXT,
                prepared_at TEXT NOT NULL,
                sent_at TEXT,
                send_method TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'rascunho',
                response_summary TEXT,
                follow_up_due_at TEXT,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE model_runs (
                id INTEGER PRIMARY KEY,
                model_version TEXT NOT NULL UNIQUE,
                training_dataset_version TEXT NOT NULL,
                trained_at TEXT NOT NULL,
                training_sample_count INTEGER NOT NULL,
                positive_sample_count INTEGER NOT NULL,
                negative_sample_count INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                validation_method TEXT NOT NULL,
                notes TEXT,
                artifact_path TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE import_runs (
                id INTEGER PRIMARY KEY,
                original_filename TEXT NOT NULL,
                source_path TEXT,
                imported_at TEXT NOT NULL,
                valid_rows INTEGER NOT NULL,
                invalid_rows INTEGER NOT NULL,
                duplicate_rows INTEGER NOT NULL,
                errors_json TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _ensure_default_templates(connection: sqlite3.Connection) -> None:
        templates = [
            ("Possível publi", "Oii, tudo bem? Meu nome é {nome_remetente} e queria conversar sobre uma possível publi contigo."),
            ("Parcerias comerciais", "Oi, tudo bem? Sou {nome_remetente}. Gostaria de saber se você trabalha com parcerias comerciais."),
            ("Contato de publicidade", "Oii! Tudo bem? Vi teu perfil e queria conversar sobre uma possível parceria. Com quem posso falar sobre publicidade?"),
        ]
        now = utc_now()
        for name, body in templates:
            connection.execute(
                "INSERT OR IGNORE INTO message_templates(name, body, variables_json, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (name, body, json.dumps(["nome_remetente"], ensure_ascii=False), now, now),
            )

    @staticmethod
    def _migration_2(connection: sqlite3.Connection) -> None:
        """Adiciona a fila de descoberta oficial sem alterar registros existentes."""
        connection.executescript(
            """
            CREATE TABLE discovery_runs (
                id INTEGER PRIMARY KEY,
                source_type TEXT NOT NULL,
                query_text TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                imported_candidate_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE discovery_items (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES discovery_runs(id),
                media_id TEXT NOT NULL,
                author_username TEXT,
                media_type TEXT,
                media_product_type TEXT,
                permalink TEXT,
                caption TEXT,
                posted_at TEXT,
                raw_json TEXT NOT NULL,
                candidate_id INTEGER REFERENCES candidates(id),
                review_state TEXT NOT NULL DEFAULT 'pendente',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, media_id)
            );
            CREATE INDEX idx_discovery_items_run ON discovery_items(run_id, review_state);
            """
        )

    def integrity_check(self) -> str:
        with self.read_connection() as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])

    def latest_backup(self) -> Path | None:
        backups = sorted(self.paths.backups.glob("prospector-*.sqlite3"), reverse=True)
        return backups[0] if backups else None
