"""Configuração de caminhos e valores padrão da aplicação."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    """Caminhos controlados exclusivamente pela aplicação."""

    root: Path
    database: Path
    backups: Path
    evidence: Path
    exports: Path
    imports: Path
    logs: Path
    models: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        configured = os.environ.get("PROSPECTOR_DATA_DIR")
        root = Path(configured).expanduser() if configured else _default_data_root()
        return cls(
            root=root,
            database=root / "prospector.sqlite3",
            backups=root / "backups",
            evidence=root / "evidence",
            exports=root / "exports",
            imports=root / "imports",
            logs=root / "logs",
            models=root / "models",
        )

    def ensure_exists(self) -> None:
        for directory in (
            self.root,
            self.backups,
            self.evidence,
            self.exports,
            self.imports,
            self.logs,
            self.models,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _default_data_root() -> Path:
    """Retorna uma pasta persistente de dados, nunca uma pasta temporária."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "ProspectorIA"
    return Path.home() / ".prospector-ia"


DEFAULT_SETTINGS: dict[str, object] = {
    "minimum_followers": 10_000,
    "positive_terms": [
        "faço publi",
        "faco publi",
        "publicidade",
        "parcerias",
        "contato comercial",
        "divulgação",
        "divulgacao",
        "anuncie aqui",
        "trabalhos",
        "recebo propostas",
    ],
    "betting_terms": ["apostas", "cassino", "casino", "bet", "palpites", "tigrinho", "jogo do tigre"],
    "family_terms": ["mãe", "mae", "mães", "maes", "família", "familia"],
    "negative_terms": [],
    "selection_threshold": 0.7,
    "evidence_max_age_days": 90,
    "backup_retention": 10,
    "sender_name": "",
    "ocr_enabled": False,
}
