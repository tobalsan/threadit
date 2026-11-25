def test_new_areas_use_the_first_unused_preset(admin):
    presets = ["blue", "purple", "pink", "orange", "green", "teal", "indigo", "brown", "coral", "gray"]
    areas = [admin.make_area(f"Area {i}") for i in range(11)]
    assert [area["color"] for area in areas[:10]] == presets
    assert areas[10]["color"] in presets
    response = admin.post("/api/areas", {"name": "Custom", "color": "teal"})
    assert response.status_code == 422


def test_color_edit_is_reflected_in_thread_and_feed_responses(admin, alice, area):
    area_url = f"/api/areas/{area['slug']}"
    thread = admin.make_thread(area["id"], "Shared launch", "Shared launch @alice")["thread"]
    thread_url = f"/api/threads/{thread['id']}"
    admin.make_thread(area["id"], "Follow-up", f"See #{thread['id']}")

    assert alice.ok("PATCH", area_url, {"color": "teal"})["color"] == "teal"
    response = alice.call("PATCH", area_url, json={"color": "ultraviolet"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert alice.ok("GET", area_url)["color"] == "teal"
    assert alice.ok("GET", "/api/areas")["areas"][0]["color"] == "teal"
    detail = alice.ok("GET", thread_url)
    assert detail["thread"]["area_color"] == "teal"
    assert detail["messages"][0]["area_color"] == "teal"
    assert detail["referenced_by"][0]["area_color"] == "teal"
    assert alice.ok("GET", "/api/attention")["items"][0]["area_color"] == "teal"
    search = alice.ok("GET", "/api/search", params={"q": "Shared launch"})
    assert search["threads"][0]["area_color"] == "teal"
    assert search["messages"][0]["area_color"] == "teal"
    assert alice.ok("GET", "/api/activity")["events"][0]["area_color"] == "teal"
