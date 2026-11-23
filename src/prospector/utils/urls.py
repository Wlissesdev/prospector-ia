"""Validação e análise conservadora de URLs públicas."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from prospector.utils.text import normalize_text

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
MAX_BYTES = 512_000
TIMEOUT_SECONDS = 8
SHORTENER_DOMAINS = {"bit.ly", "t.co", "tinyurl.com", "cutt.ly", "is.gd", "rb.gy", "tiny.cc"}
BETTING_TERMS = {"apostas", "cassino", "casino", "bet", "sportsbook", "tigrinho", "jogo do tigre"}
SOCIAL_DOMAINS = {"instagram.com", "facebook.com", "tiktok.com", "youtube.com", "x.com", "twitter.com"}


@dataclass(frozen=True)
class UrlAnalysisResult:
    original_url: str
    final_url: str | None
    redirect_chain: list[str]
    final_domain: str | None
    http_status: int | None
    page_title: str | None
    visible_text: str | None
    destination_category: str
    classification_method: str
    confidence: float
    check_status: str
    error_code: str | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_title = tag.lower() == "title"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self.in_title:
            self.title_parts.append(data)


def normalize_http_url(value: str) -> str:
    """Aceita somente HTTP(S) e produz uma forma canônica básica."""
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme.casefold() not in ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError("A URL deve usar HTTP ou HTTPS e conter um domínio público.")
    if parsed.username or parsed.password:
        raise ValueError("URLs com usuário ou senha não são aceitas.")
    host = parsed.hostname.casefold().rstrip(".")
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.casefold(), host + port, path, "", parsed.query, ""))


def _is_public_host(host: str) -> bool:
    """Resolve o host e bloqueia loopback, privado, reservado e multicast."""
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            return False
    return True


def _validated_url(value: str) -> str:
    normalized = normalize_http_url(value)
    host = urlparse(normalized).hostname
    if host is None or not _is_public_host(host):
        raise ValueError("O destino aponta para uma rede local, privada ou não verificável.")
    return normalized


def _classify(domain: str | None, title: str | None, visible_text: str | None) -> tuple[str, str, float, str]:
    haystack = normalize_text(" ".join(value for value in (domain, title, visible_text) if value))
    hostname = (domain or "").casefold()
    if any(term in haystack for term in BETTING_TERMS):
        return "apostas", "domínio ou texto público", 0.75, "Termos de apostas encontrados no destino."
    if any(hostname == domain_name or hostname.endswith("." + domain_name) for domain_name in SOCIAL_DOMAINS):
        return "rede social", "domínio conhecido", 0.9, "O destino é uma rede social conhecida."
    if hostname in SHORTENER_DOMAINS:
        return "encurtador", "domínio conhecido", 0.9, "O destino ainda é um encurtador."
    if hostname:
        return "desconhecido", "sem evidência suficiente", 0.2, "Não há evidência suficiente para classificar o destino."
    return "suspeito", "falha de verificação", 0.0, "O destino não pôde ser verificado."


def analyze_url(value: str) -> UrlAnalysisResult:
    """Resolve uma URL pública com limites; nunca executa JavaScript ou envia cookies."""
    try:
        current = _validated_url(value)
    except ValueError as exc:
        return UrlAnalysisResult(value, None, [], None, None, None, None, "suspeito", "validação", 0.0, "bloqueado", "unsafe_url", str(exc))

    opener = build_opener(_NoRedirect)
    redirects: list[str] = []
    status: int | None = None
    content_type = ""
    content = b""
    try:
        for _ in range(MAX_REDIRECTS + 1):
            request = Request(current, headers={"User-Agent": "ProspectorIA/1.0 URL safety check", "Accept": "text/html, text/plain;q=0.8"})
            try:
                response = opener.open(request, timeout=TIMEOUT_SECONDS)
                status = response.status
                content_type = response.headers.get_content_type()
                content = response.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise ValueError("O conteúdo excede o limite de segurança.")
                break
            except HTTPError as exc:
                status = exc.code
                location = exc.headers.get("Location")
                if exc.code in {301, 302, 303, 307, 308} and location:
                    if len(redirects) >= MAX_REDIRECTS:
                        raise ValueError("Número máximo de redirecionamentos excedido.")
                    redirects.append(current)
                    current = _validated_url(urljoin(current, location))
                    continue
                content_type = exc.headers.get_content_type() if exc.headers else ""
                content = exc.read(MAX_BYTES) if exc.fp else b""
                break
        else:
            raise ValueError("Número máximo de redirecionamentos excedido.")
    except (URLError, socket.timeout, TimeoutError, ValueError) as exc:
        return UrlAnalysisResult(value, None, redirects, None, status, None, None, "desconhecido", "falha de rede", 0.0, "erro", "network_or_safety_error", str(exc))

    parsed = urlparse(current)
    title: str | None = None
    text: str | None = None
    if content and content_type in {"text/html", "text/plain"}:
        decoded = content.decode("utf-8", errors="replace")
        if content_type == "text/html":
            extractor = _TextExtractor()
            extractor.feed(decoded)
            title = unescape(" ".join(extractor.title_parts)).strip()[:300] or None
            text = unescape(" ".join(extractor.parts)).strip()[:4_000] or None
        else:
            text = decoded.strip()[:4_000] or None
    category, method, confidence, explanation = _classify(parsed.hostname, title, text)
    return UrlAnalysisResult(value, current, redirects, parsed.hostname, status, title, text, category, method, confidence, "concluído", None, explanation)
