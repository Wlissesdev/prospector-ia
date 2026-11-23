from __future__ import annotations

from prospector.integrations.official_instagram import InstagramConfig, InstagramGraphClient
from prospector.services.discovery_service import associate_item_with_username, run_hashtag_discovery


class FakeClient:
    def collect_hashtag_media(self, hashtag, max_results=100, max_pages=5, only_reels=True):
        assert hashtag == "maesolteira"
        assert only_reels is True
        return [
            {
                "id": "midia-1",
                "username": "criadora.oficial",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "permalink": "https://www.instagram.com/reel/teste/",
                "caption": "#maesolteira faço publi",
                "timestamp": "2026-10-09T12:00:00+0000",
            },
            {
                "id": "midia-2",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "permalink": "https://www.instagram.com/reel/sem-autor/",
                "caption": "Sem autor retornado",
                "timestamp": "2026-10-09T12:10:00+0000",
            },
        ]


def test_official_hashtag_run_imports_only_author_returned_by_api(repo):
    result = run_hashtag_discovery("maesolteira", 100, True, repo, FakeClient())
    assert result["media_count"] == 2
    assert result["imported_candidates"] == 1
    assert repo.find_candidate("criadora.oficial") is not None
    items = repo.list_discovery_items(result["run_id"])
    assert len(items) == 2
    assert any(item["candidate_id"] is None for item in items)


def test_manual_association_creates_candidate_when_author_is_not_returned(repo):
    result = run_hashtag_discovery("maesolteira", 100, True, repo, FakeClient())
    item = next(value for value in repo.list_discovery_items(result["run_id"]) if value["candidate_id"] is None)
    candidate_id = associate_item_with_username(item, "perfil.confirmado", "maesolteira", repo)
    assert repo.get_candidate(candidate_id)["username_normalized"] == "perfil.confirmado"
    assert next(value for value in repo.list_discovery_items(result["run_id"]) if value["id"] == item["id"])["candidate_id"] == candidate_id


def test_hashtag_client_paginates_and_filters_non_reels():
    client = InstagramGraphClient(InstagramConfig("secret", "123", "v25.0"))
    responses = {
        "ig_hashtag_search": {"data": [{"id": "tag-1"}]},
        "tag-1/recent_media": {"data": [{"id": "r1", "media_product_type": "REELS"}, {"id": "p1", "media_product_type": "FEED"}]},
        "tag-1/top_media": {"data": [{"id": "r1", "media_product_type": "REELS"}, {"id": "r2", "media_product_type": "REELS"}]},
    }
    client._get = lambda path, parameters: responses[path]  # type: ignore[method-assign]
    assert [item["id"] for item in client.collect_hashtag_media("maesolteira", max_results=10)] == ["r1", "r2"]
