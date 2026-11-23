"""Conector oficial de leitura da Instagram Graph API."""

from __future__ import annotations

import os
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InstagramConfigurationError(ValueError):
    """A integração não possui as variáveis locais necessárias."""


class InstagramAPIError(RuntimeError):
    """Erro sanitizado da API, sem expor token ou URL completa."""


@dataclass(frozen=True)
class ConnectorHealth:
    name: str
    configured: bool
    status: str
    message: str
    capabilities: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InstagramConfig:
    access_token: str
    account_id: str
    api_version: str

    @classmethod
    def from_environment(cls) -> "InstagramConfig":
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
        account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()
        version = os.environ.get("INSTAGRAM_API_VERSION", "v25.0").strip()
        if not token or not account_id:
            raise InstagramConfigurationError(
                "Defina INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_ACCOUNT_ID no ambiente local."
            )
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise InstagramConfigurationError("INSTAGRAM_API_VERSION deve ter formato vNN.N.")
        return cls(token, account_id, version)


class InstagramGraphClient:
    """Leitura limitada a endpoints oficiais, sem scraping ou ações de contato."""

    def __init__(self, config: InstagramConfig) -> None:
        self.config = config
        self.base_url = f"https://graph.facebook.com/{config.api_version}"

    def test_connection(self) -> dict[str, Any]:
        return self._get(self.config.account_id, {"fields": "id,username"})

    def collect_hashtag_media(
        self, hashtag: str, max_results: int = 100, max_pages: int = 5, only_reels: bool = True
    ) -> list[dict[str, Any]]:
        """Coleta mídia pública recente/popular nos limites da resposta oficial."""
        query = _normalize_hashtag(hashtag)
        max_results = min(max(1, max_results), 250)
        max_pages = min(max(1, max_pages), 10)
        search = self._get("ig_hashtag_search", {"user_id": self.config.account_id, "q": query})
        data = search.get("data", [])
        if not data:
            return []
        hashtag_id = str(data[0]["id"])
        fields = "id,caption,media_type,media_product_type,permalink,timestamp"
        found: dict[str, dict[str, Any]] = {}
        for edge in ("recent_media", "top_media"):
            after: str | None = None
            for _ in range(max_pages):
                params: dict[str, str] = {"user_id": self.config.account_id, "fields": fields, "limit": "50"}
                if after:
                    params["after"] = after
                payload = self._get(f"{hashtag_id}/{edge}", params)
                for media in payload.get("data", []):
                    media_id = str(media.get("id", ""))
                    is_reel = media.get("media_product_type") == "REELS"
                    if media_id and (not only_reels or is_reel):
                        found.setdefault(media_id, media)
                    if len(found) >= max_results:
                        return list(found.values())
                after = payload.get("paging", {}).get("cursors", {}).get("after")
                if not after:
                    break
        return list(found.values())[:max_results]

    def business_discovery(self, username: str) -> dict[str, Any]:
        """Enriquece um perfil profissional já conhecido; não busca sugestões."""
        handle = _normalize_username(username)
        fields = (
            f"business_discovery.username({handle})"
            "{username,name,biography,followers_count,media_count,website,media.limit(10){id,caption,media_type,permalink,timestamp}}"
        )
        response = self._get(self.config.account_id, {"fields": fields})
        return dict(response.get("business_discovery") or {})

    def _get(self, path: str, parameters: dict[str, str]) -> dict[str, Any]:
        path = path.strip("/")
        if not path or ".." in path:
            raise InstagramAPIError("Caminho de API inválido.")
        params = {**parameters, "access_token": self.config.access_token}
        request = Request(
            f"{self.base_url}/{path}?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "ProspectorIA/1.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                return _parse_json(response.read())
        except HTTPError as exc:
            raise InstagramAPIError(_api_error_message(exc.read())) from exc
        except (URLError, TimeoutError) as exc:
            raise InstagramAPIError("Não foi possível conectar à API oficial. Verifique a rede e a configuração.") from exc


def _parse_json(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstagramAPIError("A API retornou uma resposta inválida.") from exc
    if not isinstance(value, dict):
        raise InstagramAPIError("A API retornou um formato inesperado.")
    return value


def _api_error_message(content: bytes) -> str:
    try:
        error = _parse_json(content).get("error", {})
        message = str(error.get("message", "Erro da API oficial."))
        code = error.get("code")
        return f"API oficial: {message}" + (f" (código {code})" if code else "")
    except InstagramAPIError:
        return "A API oficial recusou a solicitação. Verifique permissões, conta e configuração."


def _normalize_hashtag(value: str) -> str:
    result = value.strip().lstrip("#").casefold()
    if not re.fullmatch(r"[a-z0-9_]{1,100}", result):
        raise ValueError("Use hashtag sem espaços, acentos ou símbolos; por exemplo, maesolteira.")
    return result


def _normalize_username(value: str) -> str:
    result = value.strip().lstrip("@").casefold()
    if not re.fullmatch(r"[a-z0-9._]{1,100}", result):
        raise ValueError("Nome de usuário inválido.")
    return result


def check_health() -> ConnectorHealth:
    """Relata apenas configuração local; não testa API sem ação explícita do usuário."""
    configured = bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN") and os.environ.get("INSTAGRAM_ACCOUNT_ID"))
    if not configured:
        return ConnectorHealth(
            "Instagram Graph API",
            False,
            "não configurado",
            "Informe credenciais oficiais por variáveis de ambiente para habilitar testes de conectividade.",
            ["testar configuração", "coletar mídia pública por hashtag", "enriquecer perfil profissional conhecido"],
        )
    return ConnectorHealth(
        "Instagram Graph API",
        True,
        "configurado, não testado",
        "As credenciais existem no ambiente. Um teste de conectividade deve ser iniciado explicitamente e respeitar as permissões concedidas.",
        ["testar configuração", "coletar mídia pública por hashtag", "enriquecer perfil profissional conhecido"],
    )
