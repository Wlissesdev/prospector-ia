"""Interface Streamlit local do Prospector IA."""
# ruff: noqa: E402

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from prospector.analysis.ml_pipeline import score_candidates, train
from prospector.analysis.rule_scoring import assess_candidate
from prospector.config import AppPaths
from prospector.database.backup import create_backup, maybe_create_automatic_backup, restore_backup
from prospector.database.engine import Database
from prospector.database.repository import ContactBlockedError, DuplicateCandidateError, Repository
from prospector.integrations.official_instagram import (
    InstagramAPIError,
    InstagramConfig,
    InstagramConfigurationError,
    InstagramGraphClient,
    check_health,
)
from prospector.logging_config import configure_logging
from prospector.services.evidence_service import save_uploaded_evidence
from prospector.services.discovery_service import associate_item_with_username, run_hashtag_discovery
from prospector.services.import_service import import_csv, preview_csv
from prospector.services.outreach_service import render_message
from prospector.utils.text import csv_safe, find_terms
from prospector.utils.urls import analyze_url


@st.cache_resource
def application() -> tuple[AppPaths, Database, Repository]:
    paths = AppPaths.from_environment()
    database = Database(paths)
    database.initialize()
    logger = configure_logging(paths)
    automatic_backup = maybe_create_automatic_backup(database)
    logger.info("Aplicação iniciada; backup automático criado=%s", bool(automatic_backup))
    return paths, database, Repository(database)


def candidate_label(candidate: dict) -> str:
    return f"@{candidate['username_normalized']} — {candidate.get('display_name') or 'sem nome'}"


def choose_candidate(repo: Repository, key: str, *, review_only: bool = False) -> dict | None:
    candidates = repo.list_candidates(limit=1000)
    if review_only:
        candidates = [item for item in candidates if item["review_status"] in {"novo", "pendente", "revisar novamente"}]
    if not candidates:
        st.info("Nenhum candidato disponível.")
        return None
    selected_id = st.selectbox("Candidato", [item["id"] for item in candidates], format_func=lambda item: candidate_label(next(candidate for candidate in candidates if candidate["id"] == item)), key=key)
    return repo.get_candidate(int(selected_id))


def render_dashboard(repo: Repository) -> None:
    st.header("Visão geral")
    counts = repo.dashboard_counts()
    columns = st.columns(5)
    labels = [("Candidatos", "total"), ("Pendentes", "pendentes"), ("Aprovados", "aprovados"), ("Rejeitados", "rejeitados"), ("Não contatar", "opt_outs")]
    for column, (label, key) in zip(columns, labels, strict=True):
        column.metric(label, counts[key])
    st.caption("Os números são registros reais do banco local. Nenhum perfil fictício é carregado no modo normal.")
    model = repo.active_model_run()
    if model:
        st.success(f"Modelo ativo: {model['model_version']} — {model['training_sample_count']} decisões de treino.")
    else:
        st.info("Modelo ainda não treinado. As regras transparentes continuam disponíveis.")
    st.subheader("Fluxo seguro")
    st.write("Importe ou cadastre dados obtidos legitimamente, revise as evidências e prepare o contato. O aplicativo não envia DMs, não segue nem curte perfis automaticamente.")


def render_candidates(repo: Repository) -> None:
    st.header("Candidatos")
    add_tab, list_tab, detail_tab = st.tabs(["Cadastrar", "Tabela e filtros", "Detalhes"])
    with add_tab:
        with st.form("candidate_form", clear_on_submit=True):
            first, second = st.columns(2)
            username = first.text_input("Nome de usuário *", placeholder="exemplo.perfil")
            display_name = second.text_input("Nome público")
            profile_url = st.text_input("URL do perfil (opcional)")
            bio = st.text_area("Bio observada ou fornecida")
            third, fourth, fifth = st.columns(3)
            followers = third.text_input("Seguidores")
            tags = fourth.text_input("Etiquetas de nicho (separadas por vírgula)")
            relation = fifth.selectbox("Relação de descoberta", ["desconhecida", "sugestão observada", "indicação manual", "importação", "pesquisa permitida"])
            notes = st.text_area("Notas")
            submitted = st.form_submit_button("Salvar candidato")
        if submitted:
            try:
                settings = repo.get_settings()
                signals = find_terms(bio, list(settings.get("positive_terms", [])))
                candidate = repo.create_candidate({"username": username, "display_name": display_name, "profile_url": profile_url, "bio_text": bio, "follower_count": followers, "niche_tags": [item.strip() for item in tags.split(",") if item.strip()], "commercial_signals": signals, "discovery_relation": relation, "notes": notes, "source_type": "manual", "verification_state": "parcialmente verificado"})
                st.success(f"Candidato @{candidate['username_normalized']} salvo.")
            except (ValueError, DuplicateCandidateError) as exc:
                st.error(str(exc))
    with list_tab:
        first, second, third = st.columns(3)
        search = first.text_input("Buscar por usuário, nome ou bio")
        review = second.selectbox("Revisão", ["Todos", "novo", "pendente", "aprovado", "rejeitado", "revisar novamente"])
        min_followers = third.number_input("Seguidores mínimos", min_value=0, value=0, step=1000)
        candidates = repo.list_candidates(search=search, review_status=review, min_followers=int(min_followers) if min_followers else None, limit=500)
        if candidates:
            table = pd.DataFrame(candidates)[["id", "username_normalized", "display_name", "follower_count", "review_status", "contact_status", "verification_state", "ml_score", "updated_at"]]
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.download_button("Exportar seleção em CSV", _candidates_to_csv(candidates), "candidatos.csv", "text/csv")
            selectable = [item for item in candidates if not item["do_not_contact"]]
            selected = st.multiselect("Pré-selecionar para revisão humana", [item["id"] for item in selectable], format_func=lambda item: candidate_label(next(value for value in selectable if value["id"] == item)))
            if st.button("Mover seleção para fila de revisão"):
                changed = repo.move_to_review(selected)
                st.success(f"{changed} candidatos movidos para revisão. Nenhum contato foi criado.")
        else:
            st.info("Nenhum candidato corresponde aos filtros.")
    with detail_tab:
        candidate = choose_candidate(repo, "candidate_detail")
        if candidate:
            settings = repo.get_settings()
            links = repo.list_link_analyses(candidate["id"])
            assessment = assess_candidate(candidate, settings, links).to_dict()
            st.subheader(candidate_label(candidate))
            st.json({"dados": {key: value for key, value in candidate.items() if key not in {"bio_text", "notes"}}, "regras": assessment})
            st.write("**Bio:**", candidate.get("bio_text") or "Não informada")
            st.write("**Notas:**", candidate.get("notes") or "Sem notas")
            events = repo.review_events(candidate["id"])
            if events:
                st.caption("Histórico de revisão")
                st.dataframe(pd.DataFrame(events)[["reviewer_action", "reason_code", "reason_text", "created_at"]], use_container_width=True, hide_index=True)
            with st.expander("Arquivar candidato"):
                confirmed = st.checkbox("Confirmo que desejo arquivar este candidato. O histórico será preservado.", key=f"archive_confirm_{candidate['id']}")
                if st.button("Arquivar candidato", key=f"archive_{candidate['id']}"):
                    try:
                        repo.soft_delete_candidate(candidate["id"], confirmed)
                        st.success("Candidato arquivado. Você pode restaurá-lo em Configurações.")
                    except (ValueError, LookupError) as exc:
                        st.error(str(exc))


def render_import_export(repo: Repository, paths: AppPaths) -> None:
    st.header("Importação e exportação")
    uploaded = st.file_uploader("CSV de candidatos", type=["csv"])
    if uploaded:
        content = uploaded.getvalue()
        try:
            preview = preview_csv(content, uploaded.name)
            st.write(f"{preview.row_count} linhas detectadas.")
            st.dataframe(pd.DataFrame(preview.sample), use_container_width=True, hide_index=True)
            for warning in preview.warnings:
                st.warning(warning)
            targets = ["ignorar", "username", "profile_url", "display_name", "bio_text", "follower_count", "niche_tags", "notes"]
            mapping: dict[str, str] = {}
            columns = st.columns(2)
            for position, column in enumerate(preview.columns):
                default = preview.mapped_columns.get(column, "ignorar")
                selected = columns[position % 2].selectbox(f"{column} →", targets, index=targets.index(default), key=f"mapping_{column}")
                if selected != "ignorar":
                    mapping[column] = selected
            if st.button("Importar linhas válidas", type="primary"):
                if len(set(mapping.values())) != len(mapping):
                    st.error("Cada campo de destino pode ser mapeado uma única vez.")
                else:
                    result = import_csv(content, uploaded.name, mapping, repo, paths)
                    st.success(f"Importação concluída: {result.valid_rows} válidas, {result.duplicate_rows} duplicadas, {result.invalid_rows} inválidas.")
                    if result.errors:
                        st.download_button("Baixar relatório de erros", json.dumps(result.errors, ensure_ascii=False, indent=2), "erros-importacao.json", "application/json")
        except ValueError as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Exportar toda a base")
    candidates = repo.list_candidates(limit=20_000)
    if candidates:
        st.download_button("Baixar CSV", _candidates_to_csv(candidates), "prospector-candidatos.csv", "text/csv")
    else:
        st.info("Ainda não há dados para exportar.")


def render_seeds(repo: Repository) -> None:
    st.header("Perfis-semente e descoberta")
    st.caption("As relações são registradas a partir de observação ou importação do usuário; o aplicativo não extrai sugestões do Instagram.")
    candidates = repo.list_candidates(limit=1000)
    if len(candidates) >= 2:
        seed_id = st.selectbox("Perfil-semente", [item["id"] for item in candidates], format_func=lambda item: candidate_label(next(value for value in candidates if value["id"] == item)), key="seed_candidate")
        derived = st.selectbox("Candidato derivado", [item["id"] for item in candidates if item["id"] != seed_id], format_func=lambda item: candidate_label(next(value for value in candidates if value["id"] == item)), key="derived_candidate")
        relation = st.selectbox("Fonte da relação", ["sugestão observada", "indicação manual", "importação", "pesquisa permitida"])
        if st.button("Registrar relação"):
            repo.create_seed_relation(int(seed_id), int(derived), relation)
            st.success("Relação registrada.")
    else:
        st.info("Cadastre pelo menos dois candidatos para criar relações.")
    stats = repo.seed_stats()
    if stats:
        st.subheader("Resultados por semente")
        st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)


def render_official_discovery(repo: Repository) -> None:
    st.header("Descoberta oficial")
    st.write("Busca mídia pública recente e popular por hashtag pela Instagram Graph API. Os limites, a disponibilidade dos campos e a paginação são definidos pela Meta.")
    st.warning("A API não fornece perfis sugeridos. Ela pode não retornar o usuário autor em mídias de hashtag; nesses casos, associe manualmente o perfil que você identificou no Reel.")
    health = check_health()
    st.caption(f"Conector: {health.status}. {health.message}")
    try:
        client = InstagramGraphClient(InstagramConfig.from_environment())
    except InstagramConfigurationError as exc:
        client = None
        st.info(str(exc))
    if client and st.button("Testar conexão oficial"):
        try:
            response = client.test_connection()
            st.success(f"Conexão confirmada para a conta: @{response.get('username') or response.get('id')}.")
        except InstagramAPIError as exc:
            st.error(str(exc))
    with st.form("official_discovery_form"):
        hashtag = st.text_input("Hashtag", placeholder="maesolteira")
        only_reels = st.checkbox("Somente Reels", value=True)
        max_results = st.slider("Máximo de mídias nesta execução", 1, 250, 100)
        submitted = st.form_submit_button("Buscar mídia pública", type="primary", disabled=client is None)
    if submitted and client:
        try:
            result = run_hashtag_discovery(hashtag, max_results, only_reels, repo, client)
            st.success(f"Execução concluída: {result['media_count']} mídias na fila; {result['imported_candidates']} novos candidatos associados automaticamente.")
        except (ValueError, InstagramAPIError) as exc:
            st.error(str(exc))
    runs = repo.list_discovery_runs()
    if not runs:
        st.info("Nenhuma descoberta oficial executada ainda.")
        return
    st.subheader("Execuções")
    st.dataframe(pd.DataFrame(runs)[["id", "query_text", "mode", "status", "result_count", "imported_candidate_count", "completed_at", "error_message"]], use_container_width=True, hide_index=True)
    run_id = st.selectbox("Ver itens da execução", [run["id"] for run in runs], format_func=lambda value: f"#{value} — {next(run['query_text'] for run in runs if run['id'] == value)}")
    selected_run = next(run for run in runs if run["id"] == run_id)
    items = repo.list_discovery_items(int(run_id))
    if not items:
        st.info("A execução não retornou mídia pública dentro dos limites atuais da API.")
        return
    display = pd.DataFrame(items)
    st.dataframe(display[["id", "author_username", "media_product_type", "media_type", "permalink", "posted_at", "candidate_id", "review_state"]], use_container_width=True, hide_index=True)
    item_id = st.selectbox("Item para revisar", [item["id"] for item in items], format_func=lambda value: f"Mídia #{value}")
    item = next(value for value in items if value["id"] == item_id)
    if item.get("permalink"):
        st.link_button("Abrir Reel/mídia", item["permalink"])
    st.text_area("Legenda retornada", item.get("caption") or "Sem legenda retornada", height=160, disabled=True)
    if not item.get("candidate_id"):
        username = st.text_input("Usuário do perfil que você confirmou no Reel", value=item.get("author_username") or "", key=f"discovery_username_{item_id}")
        left, right = st.columns(2)
        if left.button("Associar e criar candidato", key=f"associate_{item_id}"):
            try:
                candidate_id = associate_item_with_username(item, username, selected_run["query_text"], repo)
                st.success(f"Item associado ao candidato #{candidate_id} e enviado para revisão.")
            except ValueError as exc:
                st.error(str(exc))
        if right.button("Descartar item", key=f"discard_{item_id}"):
            repo.set_discovery_item_state(int(item_id), "descartado")
            st.success("Item descartado.")


def render_evidence_links(repo: Repository, paths: AppPaths) -> None:
    st.header("Evidências, Stories e links")
    candidate = choose_candidate(repo, "evidence_candidate")
    if not candidate:
        return
    evidence_tab, link_tab, history_tab = st.tabs(["Registrar evidência", "Analisar URL", "Histórico"])
    with evidence_tab:
        st.caption("O conteúdo é sempre marcado com a origem informada. Capturas não significam acesso automático a Stories.")
        with st.form("evidence_form"):
            kind = st.selectbox("Tipo", ["bio", "contagem de seguidores", "publicação", "Story", "URL", "nota manual", "resposta comercial"])
            source = st.selectbox("Origem", ["entrada manual", "texto colado", "URL informada", "captura fornecida pelo usuário", "integração autorizada"])
            source_uri = st.text_input("URL original, se houver")
            text = st.text_area("Texto visível ou anotação")
            state = st.selectbox("Estado de verificação", ["pendente", "confirmado", "parcialmente verificado", "inferido", "desatualizado", "não verificável"])
            if st.form_submit_button("Registrar evidência"):
                try:
                    repo.add_evidence(candidate["id"], {"evidence_type": kind, "source_type": source, "source_uri": source_uri, "raw_text": text, "verification_state": state})
                    st.success("Evidência registrada com origem e data.")
                except ValueError as exc:
                    st.error(str(exc))
        image = st.file_uploader("Associar captura de tela", type=["png", "jpg", "jpeg", "webp"], key="evidence_upload")
        if image:
            st.image(image, caption="Pré-visualização: captura fornecida pelo usuário")
        if image and st.button("Salvar captura fornecida"):
            try:
                save_uploaded_evidence(candidate["id"], image.name, image.getvalue(), repo, paths)
                st.success("Captura associada. OCR continua opcional e desativado por padrão.")
            except ValueError as exc:
                st.error(str(exc))
    with link_tab:
        st.warning("A análise acessa somente URL HTTP(S) pública, sem cookies, sem JavaScript e com bloqueio de redes locais. Use apenas links que você pode analisar legitimamente.")
        url = st.text_input("URL para analisar", key="link_url")
        if st.button("Analisar destino com segurança"):
            result = analyze_url(url)
            repo.add_link_analysis(candidate["id"], result.to_dict())
            st.json(result.to_dict())
    with history_tab:
        evidence = repo.list_evidence(candidate["id"])
        links = repo.list_link_analyses(candidate["id"])
        if evidence:
            st.subheader("Evidências")
            st.dataframe(pd.DataFrame(evidence)[["evidence_type", "source_type", "verification_state", "captured_at", "reviewer_notes"]], use_container_width=True, hide_index=True)
        if links:
            st.subheader("Análises de URL")
            st.dataframe(pd.DataFrame(links)[["original_url", "final_domain", "destination_category", "confidence", "check_status", "checked_at"]], use_container_width=True, hide_index=True)
            selected_link = st.selectbox("Corrigir classificação de link", [item["id"] for item in links], format_func=lambda item: next(value["original_url"] for value in links if value["id"] == item))
            category = st.selectbox("Categoria corrigida", ["apostas", "cassino", "afiliado", "comércio", "rede social", "encurtador", "desconhecido", "suspeito"])
            correction_note = st.text_input("Nota da correção")
            if st.button("Salvar correção de link"):
                repo.correct_link_category(int(selected_link), category, correction_note)
                st.success("Classificação corrigida por revisão humana.")


def render_review(repo: Repository) -> None:
    st.header("Fila de revisão")
    candidate = choose_candidate(repo, "review_candidate", review_only=True)
    if not candidate:
        return
    settings = repo.get_settings()
    links = repo.list_link_analyses(candidate["id"])
    assessment = assess_candidate(candidate, settings, links)
    st.subheader(candidate_label(candidate))
    left, right = st.columns(2)
    left.metric("Pontuação das regras", f"{assessment.score:.0f}/100")
    right.metric("Elegibilidade", assessment.eligibility)
    st.write("**Critérios satisfeitos:**", "; ".join(assessment.satisfied) or "nenhum")
    st.write("**Dados pendentes:**", "; ".join(assessment.pending) or "nenhum")
    if assessment.excluded:
        st.error("Bloqueios: " + "; ".join(assessment.excluded))
    if candidate["ml_score"] is not None:
        st.info(f"Pontuação ML: {candidate['ml_score']:.0%}. É uma prioridade de revisão, não uma confirmação nem garantia de resultado. {candidate.get('ml_explanation') or ''}")
    reason = st.text_input("Motivo / nota de revisão")
    actions = st.columns(4)
    for column, label, action in zip(actions, ["Aprovar", "Rejeitar", "Dados insuficientes", "Não contatar"], ["aprovar", "rejeitar", "dados insuficientes", "não contatar"], strict=True):
        if column.button(label, key=f"review_{action}"):
            repo.record_review(candidate["id"], action, reason_text=reason)
            st.success(f"Ação registrada: {label}.")
            st.rerun()


def render_messages(repo: Repository) -> None:
    st.header("Mensagens e contatos")
    candidate = choose_candidate(repo, "outreach_candidate")
    if not candidate:
        return
    templates = repo.list_templates()
    if not templates:
        st.warning("Cadastre um modelo de mensagem em Configurações.")
        return
    template = st.selectbox("Modelo", templates, format_func=lambda item: item["name"])
    sender = st.text_input("Nome de quem envia", value=str(repo.get_settings().get("sender_name", "")))
    try:
        message = render_message(template["body"], candidate, sender)
        st.code(message, language=None)
        st.caption("Use o botão de cópia do bloco acima. O aplicativo não envia mensagens.")
        if candidate.get("profile_url"):
            st.link_button("Abrir perfil para contato manual", candidate["profile_url"])
        if st.button("Salvar como mensagem preparada"):
            draft = repo.prepare_outreach(candidate["id"], template["id"], message)
            st.success(f"Rascunho #{draft['id']} preparado; ele não foi marcado como enviado.")
    except (ValueError, ContactBlockedError) as exc:
        st.warning(str(exc))
    st.subheader("Rascunhos e contatos registrados")
    outreach = repo.list_outreach(candidate["id"])
    if outreach:
        st.dataframe(pd.DataFrame(outreach)[["id", "status", "prepared_at", "sent_at", "response_summary"]], use_container_width=True, hide_index=True)
        draft_ids = [item["id"] for item in outreach]
        outreach_id = st.selectbox("Registro", draft_ids, format_func=lambda value: f"#{value}", key="outreach_record")
        if st.button("Registrar que enviei manualmente"):
            try:
                repo.record_manual_contact(int(outreach_id))
                st.success("Contato manual registrado.")
            except ContactBlockedError as exc:
                st.error(str(exc))
        response = st.selectbox("Resposta", ["respondeu", "interessado", "recusado", "opt-out"])
        summary = st.text_input("Resumo da resposta")
        if st.button("Registrar resposta"):
            repo.record_response(int(outreach_id), response, summary)
            st.success("Resposta registrada.")


def render_learning(repo: Repository, paths: AppPaths) -> None:
    st.header("Aprendizado local")
    run = repo.active_model_run()
    if run:
        st.success(f"Modelo ativo: {run['model_version']} ({run['training_sample_count']} registros).")
        st.json(run["metrics_json"])
    else:
        st.info("Modelo ainda não treinado. Registre aprovações e rejeições na fila de revisão.")
    training_data = repo.candidates_for_training()
    st.caption(f"Decisões disponíveis: {len(training_data)}. Mínimo: 8, com 3 aprovações e 3 rejeições.")
    if st.button("Treinar modelo local"):
        try:
            result, model = train(training_data, paths)
            repo.save_model_run({"model_version": result.model_version, "training_dataset_version": result.model_version, "trained_at": result.model_version.split("-")[1], "training_sample_count": result.sample_count, "positive_sample_count": result.positive_count, "negative_sample_count": result.negative_count, "metrics": result.metrics, "validation_method": result.validation_method, "notes": f"Algoritmo selecionado: {result.selected_algorithm}", "artifact_path": result.artifact_path})
            all_candidates = repo.list_candidates(limit=20_000)
            scored = score_candidates(model, all_candidates)
            repo.update_model_scores([(candidate_id, score, result.model_version, explanation) for candidate_id, score, explanation in scored])
            st.success("Modelo treinado e pontuações atualizadas para priorizar revisão.")
        except ValueError as exc:
            st.error(str(exc))
    st.subheader("Pré-seleção")
    threshold = st.slider("Limiar de compatibilidade", 0.0, 1.0, float(repo.get_settings().get("selection_threshold", 0.7)), 0.05)
    if st.button("Salvar limiar"):
        repo.set_setting("selection_threshold", threshold)
        st.success("Limiar salvo.")
    selected = [item for item in repo.list_candidates(limit=20_000) if item.get("ml_score") is not None and item["ml_score"] >= threshold and not item["do_not_contact"] and item["contact_status"] == "não contatado"]
    st.write(f"{len(selected)} candidatos estão acima do limiar para revisão humana.")
    if selected:
        st.dataframe(pd.DataFrame(selected)[["username_normalized", "ml_score", "review_status", "ml_explanation"]], use_container_width=True, hide_index=True)


def render_reports(repo: Repository) -> None:
    st.header("Relatórios")
    candidates = repo.list_candidates(limit=20_000)
    if not candidates:
        st.info("Os relatórios aparecerão quando houver candidatos.")
        return
    data = pd.DataFrame(candidates)
    st.subheader("Distribuição por revisão")
    st.bar_chart(data["review_status"].value_counts())
    st.subheader("Distribuição por contato")
    st.bar_chart(data["contact_status"].value_counts())
    stats = repo.seed_stats()
    if stats:
        st.subheader("Qualidade por perfil-semente")
        st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)


def render_settings(repo: Repository, database: Database) -> None:
    st.header("Configurações")
    settings = repo.get_settings()
    with st.form("settings_form"):
        minimum = st.number_input("Seguidores mínimos", min_value=0, value=int(settings["minimum_followers"]), step=1000)
        positives = st.text_area("Termos comerciais (um por linha)", "\n".join(settings["positive_terms"]))
        bets = st.text_area("Termos de apostas (um por linha)", "\n".join(settings["betting_terms"]))
        family = st.text_area("Termos de nicho/família (um por linha)", "\n".join(settings["family_terms"]))
        sender = st.text_input("Nome padrão de quem envia", value=str(settings.get("sender_name", "")))
        retention = st.number_input("Backups mantidos", min_value=1, max_value=100, value=int(settings["backup_retention"]))
        if st.form_submit_button("Salvar configurações"):
            for key, value in {"minimum_followers": int(minimum), "positive_terms": _lines(positives), "betting_terms": _lines(bets), "family_terms": _lines(family), "sender_name": sender.strip(), "backup_retention": int(retention)}.items():
                repo.set_setting(key, value)
            st.success("Configurações salvas.")
    st.subheader("Modelos de mensagem")
    with st.form("template_form", clear_on_submit=True):
        name = st.text_input("Nome do modelo")
        body = st.text_area("Texto", placeholder="Oi, sou {nome_remetente}...")
        if st.form_submit_button("Salvar modelo"):
            try:
                repo.save_template(name, body)
                st.success("Modelo salvo.")
            except ValueError as exc:
                st.error(str(exc))
    templates = repo.list_templates()
    if templates:
        selected_template = st.selectbox("Desativar modelo", templates, format_func=lambda item: item["name"])
        if st.button("Desativar modelo selecionado"):
            repo.deactivate_template(int(selected_template["id"]))
            st.success("Modelo desativado. Rascunhos existentes foram preservados.")
    st.subheader("Backup e restauração")
    if st.button("Criar backup agora"):
        destination = create_backup(database)
        st.success(f"Backup criado: {destination.name}")
    backups = sorted(database.paths.backups.glob("prospector-*.sqlite3"), reverse=True)
    if backups:
        backup = st.selectbox("Backup", backups, format_func=lambda item: item.name)
        confirmed = st.checkbox("Entendo que a restauração substitui o banco atual; será criado um backup de segurança antes disso.")
        if st.button("Restaurar backup selecionado", type="secondary"):
            try:
                safety_copy = restore_backup(database, backup, confirmed)
                st.success(f"Restauração concluída. Backup anterior preservado em {safety_copy.name}.")
                st.cache_resource.clear()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    st.subheader("Candidatos arquivados")
    archived = [item for item in repo.list_candidates(include_deleted=True, limit=20_000) if item["deleted_at"]]
    if archived:
        archived_id = st.selectbox("Candidato arquivado", [item["id"] for item in archived], format_func=lambda item: candidate_label(next(value for value in archived if value["id"] == item)))
        if st.button("Restaurar candidato arquivado"):
            repo.restore_candidate(int(archived_id))
            st.success("Candidato restaurado.")


def render_diagnostics(repo: Repository, database: Database, paths: AppPaths) -> None:
    st.header("Diagnóstico e logs")
    connector = check_health()
    model = repo.active_model_run()
    disk = shutil.disk_usage(paths.root)
    st.json({"versão": "1.0.0", "python": sys.version.split()[0], "banco": str(paths.database), "integridade": database.integrity_check(), "último_backup": database.latest_backup().name if database.latest_backup() else None, "espaço_livre_gb": round(disk.free / 1024**3, 2), "conector": connector.to_dict(), "modelo_ativo": model["model_version"] if model else None})
    log_file = paths.logs / "prospector.log"
    if log_file.exists():
        st.text_area("Últimas linhas do log", "\n".join(log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]), height=250, disabled=True)
    st.caption("Logs evitam tokens, senhas, cookies e conteúdos privados. O conector oficial não está ativo até configuração explícita.")


def _candidates_to_csv(candidates: list[dict]) -> bytes:
    safe = [{key: csv_safe(json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value) for key, value in candidate.items()} for candidate in candidates]
    return pd.DataFrame(safe).to_csv(index=False).encode("utf-8-sig")


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def main() -> None:
    st.set_page_config(page_title="Prospector IA", page_icon="🔎", layout="wide")
    paths, database, repo = application()
    st.sidebar.title("Prospector IA")
    page = st.sidebar.radio("Navegação", ["Visão geral", "Candidatos", "Descoberta oficial", "Perfis-semente", "Evidências e Links", "Fila de revisão", "Mensagens", "Aprendizado", "Relatórios", "Importação/exportação", "Configurações", "Diagnóstico"])
    pages = {
        "Visão geral": lambda: render_dashboard(repo),
        "Candidatos": lambda: render_candidates(repo),
        "Descoberta oficial": lambda: render_official_discovery(repo),
        "Perfis-semente": lambda: render_seeds(repo),
        "Evidências e Links": lambda: render_evidence_links(repo, paths),
        "Fila de revisão": lambda: render_review(repo),
        "Mensagens": lambda: render_messages(repo),
        "Aprendizado": lambda: render_learning(repo, paths),
        "Relatórios": lambda: render_reports(repo),
        "Importação/exportação": lambda: render_import_export(repo, paths),
        "Configurações": lambda: render_settings(repo, database),
        "Diagnóstico": lambda: render_diagnostics(repo, database, paths),
    }
    pages[page]()


if __name__ == "__main__":
    main()
