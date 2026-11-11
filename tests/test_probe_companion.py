import httpx
import respx

from character_planner.probe_companion import BASE_URL, exact_match, probe_item

GIRDLE = {"id": 250101, "name": "Kindlegem Girdle", "itemLevel": 20, "armor": "mail"}


def test_exact_match_picks_the_named_item() -> None:
    body = {"data": [{"id": 1, "name": "Kindlegem Bracers"}, GIRDLE]}
    assert exact_match(body, "kindlegem girdle") == GIRDLE
    assert exact_match(body, "Flamefist Grips") is None
    assert exact_match("Not Found", "Kindlegem Girdle") is None


@respx.mock
def test_probe_fetches_detail_for_an_exact_match() -> None:
    search = respx.get(f"{BASE_URL}/items").mock(
        return_value=httpx.Response(200, json={"data": [GIRDLE], "meta": {}})
    )
    detail = respx.get(f"{BASE_URL}/items/250101").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": GIRDLE
                | {
                    "tooltip": [{"left": "120 Armor", "kind": "plain"}],
                    "dropsFrom": [
                        {"dungeon": {"id": "x", "name": "Hall of Thanes"}, "source": "Magmatus"}
                    ],
                }
            },
        )
    )
    with httpx.Client() as http:
        results = probe_item(http, "Kindlegem Girdle")

    assert search.calls.last.request.url.params["q"] == "Kindlegem Girdle"
    assert detail.called
    assert [r.status for r in results] == [200, 200]


@respx.mock
def test_probe_stops_after_search_without_a_match() -> None:
    respx.get(f"{BASE_URL}/items").mock(return_value=httpx.Response(200, json={"data": []}))
    with httpx.Client() as http:
        results = probe_item(http, "Cape of the Brotherhood")
    assert len(results) == 1
