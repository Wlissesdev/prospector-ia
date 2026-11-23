"""Operações de persistência com regras de integridade do CRM."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from prospector.database.engine import Database, utc_now
from prospector.utils.text import normalize_text, normalize_username
from prospector.utils.urls import normalize_http_url


class DuplicateCandidateError(ValueError):
    """Indica que já existe candidato para a mesma plataforma e nome de usuário."""


class ContactBlockedError(ValueError):
    """Impede preparar ou registrar uma nova abordagem após opt-out."""


JSON_COLUMNS = {
    "commercial_signals_json",
    "niche_tags_json",
    "features_snapshot_json",
    "variables_json",
    "redirect_chain_json",
    "metrics_json",
    "errors_json",
}


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    output = dict(row)
    for key in JSON_COLUMNS:
        if key in output and output[key] is not None:
            output[key] = json.loads(output[key])
    return output


def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows if row is not None]  # type: ignore[misc]


class Repository:
    """Repositório SQLite; dados pessoais não saem do banco local."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_settings(self) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            rows = connection.execute("SELECT key, value_json FROM settings ORDER BY key").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def set_setting(self, key: str, value: Any) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), utc_now()),
            )

    def create_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as connection:
            candidate_id = self.create_candidate_in_transaction(connection, payload)
        return self.get_candidate(candidate_id)

    def create_candidate_in_transaction(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> int:
        """Insere um candidato na transação fornecida para importações em lote."""
        username = normalize_username(str(payload.get("username") or payload.get("username_normalized") or ""))
        platform = str(payload.get("platform") or "instagram").casefold().strip()
        profile_url = payload.get("profile_url")
        if profile_url:
            profile_url = normalize_http_url(str(profile_url))
        else:
            profile_url = f"https://www.instagram.com/{username}/" if platform == "instagram" else None
        follower_count = _optional_nonnegative_int(payload.get("follower_count"), "seguidores")
        following_count = _optional_nonnegative_int(payload.get("following_count"), "seguindo")
        post_count = _optional_nonnegative_int(payload.get("post_count"), "publicações")
        now = utc_now()
        values = {
            "platform": platform,
            "username_normalized": username,
            "profile_url": profile_url,
            "display_name": _clean_optional(payload.get("display_name")),
            "bio_text": _clean_optional(payload.get("bio_text")),
            "follower_count": follower_count,
            "following_count": following_count,
            "post_count": post_count,
            "account_type": _clean_optional(payload.get("account_type")) or "desconhecido",
            "profile_category": _clean_optional(payload.get("profile_category")),
            "commercial_signals_json": json.dumps(payload.get("commercial_signals") or [], ensure_ascii=False),
            "niche_tags_json": json.dumps(payload.get("niche_tags") or [], ensure_ascii=False),
            "source_type": _clean_optional(payload.get("source_type")) or "manual",
            "source_reference": _clean_optional(payload.get("source_reference")),
            "discovery_relation": _clean_optional(payload.get("discovery_relation")) or "desconhecida",
            "first_seen_at": now,
            "last_checked_at": _clean_optional(payload.get("last_checked_at")),
            "data_freshness": _clean_optional(payload.get("data_freshness")) or "desconhecida",
            "verification_state": _clean_optional(payload.get("verification_state")) or "pendente",
            "review_status": "novo",
            "contact_status": "não contatado",
            "do_not_contact": 0,
            "notes": _clean_optional(payload.get("notes")),
            "created_at": now,
            "updated_at": now,
        }
        columns = ", ".join(values)
        parameters = ", ".join("?" for _ in values)
        try:
            cursor = connection.execute(
                f"INSERT INTO candidates ({columns}) VALUES ({parameters})", tuple(values.values())
            )
            candidate_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateCandidateError(f"O perfil @{username} já existe na base.") from exc
        return candidate_id

    def get_candidate(self, candidate_id: int) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            result = _row(connection.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone())
        if result is None:
            raise LookupError("Candidato não encontrado.")
        return result

    def find_candidate(self, username: str, platform: str = "instagram") -> dict[str, Any] | None:
        normalized = normalize_username(username)
        with self.database.read_connection() as connection:
            return _row(
                connection.execute(
                    "SELECT * FROM candidates WHERE platform=? AND username_normalized=? AND deleted_at IS NULL",
                    (platform, normalized),
                ).fetchone()
            )

    def list_candidates(
        self,
        *,
        search: str = "",
        review_status: str | None = None,
        contact_status: str | None = None,
        min_followers: int | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        parameters: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if search.strip():
            clauses.append("(username_normalized LIKE ? OR display_name LIKE ? OR bio_text LIKE ?)")
            term = f"%{search.strip()}%"
            parameters.extend([term, term, term])
        if review_status and review_status != "Todos":
            clauses.append("review_status = ?")
            parameters.append(review_status)
        if contact_status and contact_status != "Todos":
            clauses.append("contact_status = ?")
            parameters.append(contact_status)
        if min_followers is not None:
            clauses.append("follower_count >= ?")
            parameters.append(min_followers)
        parameters.extend([limit, offset])
        query = "SELECT * FROM candidates WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        with self.database.read_connection() as connection:
            return _rows(connection.execute(query, parameters).fetchall())

    def count_candidates(self, **filters: Any) -> int:
        clauses = ["deleted_at IS NULL"]
        parameters: list[Any] = []
        for key, value in filters.items():
            if value is not None:
                clauses.append(f"{key} = ?")
                parameters.append(value)
        with self.database.read_connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM candidates WHERE " + " AND ".join(clauses), parameters).fetchone()[0])

    def update_candidate(self, candidate_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "display_name", "bio_text", "follower_count", "following_count", "post_count",
            "account_type", "profile_category", "source_type", "source_reference",
            "discovery_relation", "last_checked_at", "data_freshness", "verification_state",
            "notes", "profile_url", "commercial_signals", "niche_tags",
        }
        changes: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if key in {"follower_count", "following_count", "post_count"}:
                changes[key] = _optional_nonnegative_int(value, key)
            elif key == "profile_url":
                changes[key] = normalize_http_url(value) if value else None
            elif key in {"commercial_signals", "niche_tags"}:
                changes[f"{key}_json"] = json.dumps(value or [], ensure_ascii=False)
            else:
                changes[key] = _clean_optional(value)
        if not changes:
            return self.get_candidate(candidate_id)
        changes["updated_at"] = utc_now()
        query = ", ".join(f"{key} = ?" for key in changes)
        with self.database.transaction() as connection:
            cursor = connection.execute(f"UPDATE candidates SET {query} WHERE id = ?", (*changes.values(), candidate_id))
            if not cursor.rowcount:
                raise LookupError("Candidato não encontrado.")
        return self.get_candidate(candidate_id)

    def soft_delete_candidate(self, candidate_id: int, confirmed: bool) -> None:
        """Oculta um candidato sem apagar evidências, contatos ou histórico."""
        if not confirmed:
            raise ValueError("Confirme a exclusão para arquivar o candidato.")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE candidates SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (utc_now(), utc_now(), candidate_id),
            )
            if not cursor.rowcount:
                raise LookupError("Candidato não encontrado ou já arquivado.")

    def restore_candidate(self, candidate_id: int) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE candidates SET deleted_at=NULL, updated_at=? WHERE id=? AND deleted_at IS NOT NULL",
                (utc_now(), candidate_id),
            )
            if not cursor.rowcount:
                raise LookupError("Candidato não encontrado ou não está arquivado.")

    def add_evidence(self, candidate_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_candidate(candidate_id)
        raw_text = _clean_optional(payload.get("raw_text"))
        extracted = _clean_optional(payload.get("extracted_text"))
        values = {
            "candidate_id": candidate_id,
            "evidence_type": str(payload.get("evidence_type") or "nota manual"),
            "source_type": str(payload.get("source_type") or "entrada manual"),
            "source_uri": _clean_optional(payload.get("source_uri")),
            "captured_at": str(payload.get("captured_at") or utc_now()),
            "observed_at": _clean_optional(payload.get("observed_at")),
            "raw_text": raw_text,
            "extracted_text": extracted,
            "normalized_text": normalize_text(extracted or raw_text),
            "evidence_file_path": _clean_optional(payload.get("evidence_file_path")),
            "content_hash": _clean_optional(payload.get("content_hash")),
            "verification_state": str(payload.get("verification_state") or "pendente"),
            "confidence": payload.get("confidence"),
            "reviewer_decision": _clean_optional(payload.get("reviewer_decision")),
            "reviewer_notes": _clean_optional(payload.get("reviewer_notes")),
            "expires_at": _clean_optional(payload.get("expires_at")),
            "created_at": utc_now(),
        }
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"INSERT INTO evidence ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values())
            )
            evidence_id = int(cursor.lastrowid)
        return self.get_evidence(evidence_id)

    def get_evidence(self, evidence_id: int) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            value = _row(connection.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone())
        if value is None:
            raise LookupError("Evidência não encontrada.")
        return value

    def list_evidence(self, candidate_id: int) -> list[dict[str, Any]]:
        with self.database.read_connection() as connection:
            return _rows(connection.execute("SELECT * FROM evidence WHERE candidate_id = ? ORDER BY captured_at DESC", (candidate_id,)).fetchall())

    def add_link_analysis(self, candidate_id: int, payload: dict[str, Any], evidence_id: int | None = None) -> dict[str, Any]:
        values = {
            "candidate_id": candidate_id,
            "evidence_id": evidence_id,
            "original_url": payload["original_url"],
            "final_url": payload.get("final_url"),
            "redirect_chain_json": json.dumps(payload.get("redirect_chain") or [], ensure_ascii=False),
            "final_domain": payload.get("final_domain"),
            "http_status": payload.get("http_status"),
            "page_title": payload.get("page_title"),
            "visible_text": payload.get("visible_text"),
            "destination_category": payload.get("destination_category") or "desconhecido",
            "classification_method": payload.get("classification_method"),
            "confidence": payload.get("confidence"),
            "checked_at": utc_now(),
            "check_status": payload.get("check_status") or "erro",
            "error_code": payload.get("error_code"),
            "explanation": payload.get("explanation"),
            "review_status": "pendente",
        }
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"INSERT INTO link_analyses ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values())
            )
            link_id = int(cursor.lastrowid)
        with self.database.read_connection() as connection:
            result = _row(connection.execute("SELECT * FROM link_analyses WHERE id = ?", (link_id,)).fetchone())
        assert result is not None
        return result

    def correct_link_category(self, link_id: int, category: str, notes: str = "") -> None:
        """Registra a correção humana sem ocultar o resultado técnico anterior."""
        allowed = {"apostas", "cassino", "afiliado", "comércio", "rede social", "encurtador", "desconhecido", "suspeito"}
        if category not in allowed:
            raise ValueError("Categoria de link inválida.")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE link_analyses SET destination_category=?, classification_method='revisão humana', review_status='corrigido', explanation=COALESCE(explanation, '') || ? WHERE id=?",
                (category, f"\nCorreção humana: {notes.strip()}" if notes.strip() else "\nCorrigido por revisão humana.", link_id),
            )
            if not cursor.rowcount:
                raise LookupError("Análise de link não encontrada.")

    def list_link_analyses(self, candidate_id: int) -> list[dict[str, Any]]:
        with self.database.read_connection() as connection:
            return _rows(connection.execute("SELECT * FROM link_analyses WHERE candidate_id = ? ORDER BY checked_at DESC", (candidate_id,)).fetchall())

    def create_seed_relation(self, seed_id: int, candidate_id: int, relation_type: str, notes: str = "") -> None:
        if seed_id == candidate_id:
            raise ValueError("Um candidato não pode ser semente de si mesmo.")
        self.get_candidate(seed_id)
        self.get_candidate(candidate_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO seed_relations(seed_candidate_id, discovered_candidate_id, relation_type, observed_at, notes) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(seed_candidate_id, discovered_candidate_id, relation_type) DO UPDATE SET observed_at=excluded.observed_at, notes=excluded.notes",
                (seed_id, candidate_id, relation_type, utc_now(), _clean_optional(notes)),
            )

    def seed_stats(self) -> list[dict[str, Any]]:
        query = """
            SELECT seed.id, seed.username_normalized, seed.display_name, COUNT(rel.id) AS derived_count,
                   SUM(CASE WHEN child.review_status = 'aprovado' THEN 1 ELSE 0 END) AS approved_count,
                   ROUND(100.0 * SUM(CASE WHEN child.review_status = 'aprovado' THEN 1 ELSE 0 END) / NULLIF(COUNT(rel.id), 0), 1) AS approval_rate
            FROM candidates seed
            LEFT JOIN seed_relations rel ON rel.seed_candidate_id = seed.id
            LEFT JOIN candidates child ON child.id = rel.discovered_candidate_id
            WHERE seed.deleted_at IS NULL
            GROUP BY seed.id
            HAVING COUNT(rel.id) > 0
            ORDER BY approval_rate DESC, derived_count DESC
        """
        with self.database.read_connection() as connection:
            return _rows(connection.execute(query).fetchall())

    def record_review(self, candidate_id: int, action: str, reason_code: str = "", reason_text: str = "") -> None:
        actions = {"aprovar": "aprovado", "rejeitar": "rejeitado", "adiar": "revisar novamente", "dados insuficientes": "pendente", "não contatar": "rejeitado"}
        if action not in actions:
            raise ValueError("Ação de revisão inválida.")
        candidate = self.get_candidate(candidate_id)
        snapshot = {
            "followers": candidate["follower_count"],
            "bio": candidate["bio_text"],
            "signals": candidate["commercial_signals_json"],
            "score": candidate["ml_score"],
        }
        do_not_contact = 1 if action == "não contatar" else candidate["do_not_contact"]
        contact_status = "não contatar" if do_not_contact else candidate["contact_status"]
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE candidates SET review_status=?, do_not_contact=?, contact_status=?, updated_at=? WHERE id=?",
                (actions[action], do_not_contact, contact_status, utc_now(), candidate_id),
            )
            connection.execute(
                "INSERT INTO review_events(candidate_id, reviewer_action, reason_code, reason_text, features_snapshot_json, model_version_at_decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (candidate_id, action, _clean_optional(reason_code), _clean_optional(reason_text), json.dumps(snapshot, ensure_ascii=False), candidate["ml_model_version"], utc_now()),
            )

    def review_events(self, candidate_id: int) -> list[dict[str, Any]]:
        with self.database.read_connection() as connection:
            return _rows(connection.execute("SELECT * FROM review_events WHERE candidate_id=? ORDER BY created_at DESC", (candidate_id,)).fetchall())

    def list_templates(self) -> list[dict[str, Any]]:
        with self.database.read_connection() as connection:
            return _rows(connection.execute("SELECT * FROM message_templates WHERE is_active=1 ORDER BY name").fetchall())

    def deactivate_template(self, template_id: int) -> None:
        """Desativa um modelo sem destruir rascunhos que já o referenciam."""
        with self.database.transaction() as connection:
            cursor = connection.execute("UPDATE message_templates SET is_active=0, updated_at=? WHERE id=?", (utc_now(), template_id))
            if not cursor.rowcount:
                raise LookupError("Modelo de mensagem não encontrado.")

    def save_template(self, name: str, body: str) -> None:
        if not name.strip() or not body.strip():
            raise ValueError("Nome e texto do modelo são obrigatórios.")
        variables = sorted(set(re.findall(r"\{([a-z_]+)\}", body)))
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO message_templates(name, body, variables_json, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET body=excluded.body, variables_json=excluded.variables_json, is_active=1, updated_at=excluded.updated_at",
                (name.strip(), body.strip(), json.dumps(variables, ensure_ascii=False), now, now),
            )

    def prepare_outreach(self, candidate_id: int, template_id: int, rendered_message: str) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate["do_not_contact"]:
            raise ContactBlockedError("Este perfil está marcado como não contatar.")
        if not rendered_message.strip():
            raise ValueError("A mensagem preparada está vazia.")
        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO outreach(candidate_id, template_id, message_draft, prepared_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (candidate_id, template_id, rendered_message.strip(), now, now, now),
            )
            outreach_id = int(cursor.lastrowid)
            connection.execute("UPDATE candidates SET contact_status='preparado', updated_at=? WHERE id=?", (now, candidate_id))
        return self.get_outreach(outreach_id)

    def get_outreach(self, outreach_id: int) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            result = _row(connection.execute("SELECT * FROM outreach WHERE id=?", (outreach_id,)).fetchone())
        if result is None:
            raise LookupError("Rascunho de contato não encontrado.")
        return result

    def record_manual_contact(self, outreach_id: int, sent_text: str | None = None) -> None:
        outreach = self.get_outreach(outreach_id)
        candidate = self.get_candidate(outreach["candidate_id"])
        if candidate["do_not_contact"]:
            raise ContactBlockedError("O contato foi bloqueado por opt-out.")
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE outreach SET message_sent_text=?, sent_at=?, status='enviado manualmente', updated_at=? WHERE id=?",
                (_clean_optional(sent_text) or outreach["message_draft"], now, now, outreach_id),
            )
            connection.execute("UPDATE candidates SET contact_status='contatado manualmente', updated_at=? WHERE id=?", (now, candidate["id"]))

    def record_response(self, outreach_id: int, status: str, summary: str = "") -> None:
        if status not in {"respondeu", "interessado", "recusado", "opt-out"}:
            raise ValueError("Estado de resposta inválido.")
        outreach = self.get_outreach(outreach_id)
        do_not_contact = 1 if status in {"recusado", "opt-out"} else 0
        contact_status = "não contatar" if do_not_contact else status
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute("UPDATE outreach SET status=?, response_summary=?, do_not_contact=?, updated_at=? WHERE id=?", (status, _clean_optional(summary), do_not_contact, now, outreach_id))
            connection.execute("UPDATE candidates SET contact_status=?, do_not_contact=CASE WHEN ?=1 THEN 1 ELSE do_not_contact END, updated_at=? WHERE id=?", (contact_status, do_not_contact, now, outreach["candidate_id"]))

    def list_outreach(self, candidate_id: int | None = None) -> list[dict[str, Any]]:
        query, params = ("SELECT * FROM outreach ORDER BY prepared_at DESC", [])
        if candidate_id is not None:
            query, params = ("SELECT * FROM outreach WHERE candidate_id=? ORDER BY prepared_at DESC", [candidate_id])
        with self.database.read_connection() as connection:
            return _rows(connection.execute(query, params).fetchall())

    def dashboard_counts(self) -> dict[str, int]:
        query = """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN review_status='novo' THEN 1 ELSE 0 END) AS novos,
              SUM(CASE WHEN review_status IN ('novo','pendente','revisar novamente') THEN 1 ELSE 0 END) AS pendentes,
              SUM(CASE WHEN review_status='aprovado' THEN 1 ELSE 0 END) AS aprovados,
              SUM(CASE WHEN review_status='rejeitado' THEN 1 ELSE 0 END) AS rejeitados,
              SUM(CASE WHEN contact_status='preparado' THEN 1 ELSE 0 END) AS preparados,
              SUM(CASE WHEN contact_status IN ('contatado manualmente','respondeu','interessado','não interessado') THEN 1 ELSE 0 END) AS contatos,
              SUM(CASE WHEN contact_status IN ('respondeu','interessado','recusado') THEN 1 ELSE 0 END) AS respostas,
              SUM(CASE WHEN do_not_contact=1 THEN 1 ELSE 0 END) AS opt_outs
            FROM candidates WHERE deleted_at IS NULL
        """
        with self.database.read_connection() as connection:
            values = dict(connection.execute(query).fetchone())
        return {key: int(value or 0) for key, value in values.items()}

    def move_to_review(self, candidate_ids: list[int]) -> int:
        """Pré-seleciona registros para revisão, sem criar qualquer contato."""
        ids = sorted(set(int(candidate_id) for candidate_id in candidate_ids))
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE candidates SET review_status='pendente', updated_at=? WHERE id IN ({placeholders}) AND deleted_at IS NULL AND do_not_contact=0",
                (utc_now(), *ids),
            )
        return int(cursor.rowcount)

    def start_discovery_run(self, source_type: str, query_text: str, mode: str) -> int:
        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO discovery_runs(source_type, query_text, mode, status, started_at, created_at) VALUES (?, ?, ?, 'em andamento', ?, ?)",
                (source_type, query_text, mode, now, now),
            )
            return int(cursor.lastrowid)

    def finish_discovery_run(self, run_id: int, result_count: int, imported_count: int, error_message: str | None = None) -> None:
        status = "erro" if error_message else "concluído"
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE discovery_runs SET status=?, result_count=?, imported_candidate_count=?, completed_at=?, error_message=? WHERE id=?",
                (status, result_count, imported_count, utc_now(), _clean_optional(error_message), run_id),
            )
            if not cursor.rowcount:
                raise LookupError("Execução de descoberta não encontrada.")

    def add_discovery_item(self, run_id: int, item: dict[str, Any]) -> int:
        values = {
            "run_id": run_id,
            "media_id": str(item["id"]),
            "author_username": _clean_optional(item.get("username")),
            "media_type": _clean_optional(item.get("media_type")),
            "media_product_type": _clean_optional(item.get("media_product_type")),
            "permalink": _clean_optional(item.get("permalink")),
            "caption": _clean_optional(item.get("caption")),
            "posted_at": _clean_optional(item.get("timestamp")),
            "raw_json": json.dumps(item, ensure_ascii=False),
            "created_at": utc_now(),
        }
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"INSERT OR IGNORE INTO discovery_items ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            existing = connection.execute("SELECT id FROM discovery_items WHERE run_id=? AND media_id=?", (run_id, values["media_id"])).fetchone()
            assert existing is not None
            return int(existing[0])

    def list_discovery_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.database.read_connection() as connection:
            return _rows(connection.execute("SELECT * FROM discovery_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall())

    def list_discovery_items(self, run_id: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query, parameters = ("SELECT * FROM discovery_items ORDER BY id DESC LIMIT ?", [limit])
        if run_id is not None:
            query, parameters = ("SELECT * FROM discovery_items WHERE run_id=? ORDER BY id DESC LIMIT ?", [run_id, limit])
        with self.database.read_connection() as connection:
            return _rows(connection.execute(query, parameters).fetchall())

    def attach_discovery_item(self, item_id: int, candidate_id: int) -> None:
        self.get_candidate(candidate_id)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE discovery_items SET candidate_id=?, review_state='associado' WHERE id=?",
                (candidate_id, item_id),
            )
            if not cursor.rowcount:
                raise LookupError("Item de descoberta não encontrado.")

    def set_discovery_item_state(self, item_id: int, state: str) -> None:
        if state not in {"pendente", "associado", "descartado"}:
            raise ValueError("Estado de descoberta inválido.")
        with self.database.transaction() as connection:
            cursor = connection.execute("UPDATE discovery_items SET review_state=? WHERE id=?", (state, item_id))
            if not cursor.rowcount:
                raise LookupError("Item de descoberta não encontrado.")

    def candidates_for_training(self) -> list[dict[str, Any]]:
        query = """
          SELECT c.* FROM candidates c
          WHERE c.deleted_at IS NULL AND c.review_status IN ('aprovado','rejeitado')
          ORDER BY c.id
        """
        with self.database.read_connection() as connection:
            return _rows(connection.execute(query).fetchall())

    def update_model_scores(self, scores: list[tuple[int, float, str, str]]) -> None:
        now = utc_now()
        with self.database.transaction() as connection:
            connection.executemany("UPDATE candidates SET ml_score=?, ml_model_version=?, ml_explanation=?, updated_at=? WHERE id=?", [(score, version, explanation, now, candidate_id) for candidate_id, score, version, explanation in scores])

    def save_model_run(self, payload: dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute("UPDATE model_runs SET active=0")
            connection.execute(
                "INSERT INTO model_runs(model_version, training_dataset_version, trained_at, training_sample_count, positive_sample_count, negative_sample_count, metrics_json, validation_method, notes, artifact_path, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (payload["model_version"], payload["training_dataset_version"], payload["trained_at"], payload["training_sample_count"], payload["positive_sample_count"], payload["negative_sample_count"], json.dumps(payload["metrics"], ensure_ascii=False), payload["validation_method"], payload.get("notes"), payload["artifact_path"]),
            )

    def active_model_run(self) -> dict[str, Any] | None:
        with self.database.read_connection() as connection:
            return _row(connection.execute("SELECT * FROM model_runs WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone())

    def record_import(self, filename: str, source_path: str, valid: int, invalid: int, duplicates: int, errors: list[dict[str, Any]]) -> None:
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO import_runs(original_filename, source_path, imported_at, valid_rows, invalid_rows, duplicate_rows, errors_json) VALUES (?, ?, ?, ?, ?, ?, ?)", (filename, source_path, utc_now(), valid, invalid, duplicates, json.dumps(errors, ensure_ascii=False)))


def _clean_optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        result = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"O campo {label} deve ser um número inteiro.") from exc
    if result < 0:
        raise ValueError(f"O campo {label} não pode ser negativo.")
    return result

