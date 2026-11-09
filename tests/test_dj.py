import time

from shelf import dj


def login(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    client.patch("/api/dj/settings", json={"enabled": True})  # the DJ is off until an admin turns it on


def test_the_dj_is_off_until_turned_on(client):
    assert client.post("/api/login", json={"password": "hunter2"}).status_code == 200
    assert client.get("/api/session").json()["features"] == {"dj": False}
    assert client.post("/api/dj/next", json={"first": True}).status_code == 404
    assert client.post("/api/dj/prepare", json={}).status_code == 404
    assert client.get("/api/dj/settings").json()["enabled"] is False  # admins can still see and set it up
    client.patch("/api/dj/settings", json={"enabled": True})
    assert client.get("/api/session").json()["features"] == {"dj": True}
    assert client.post("/api/dj/next", json={"first": True}).status_code == 200
    client.patch("/api/dj/settings", json={"enabled": False})
    assert client.post("/api/dj/next", json={"first": True}).status_code == 404


def test_dj_segments_and_lines(client, monkeypatch):
    prompts = []
    monkeypatch.setattr(dj, "write", lambda provider, key, model, system, prompt, **k: prompts.append(prompt) or None)
    login(client)
    first = client.post("/api/dj/next", json={"first": True, "when": "Saturday", "hour": 21, "minute": 20}).json()
    assert first["tracks"] and first["text"].startswith(("Hey admin", "Good", "admin, welcome"))
    assert first["voice"] is None and first["written"] is False  # no voice installed here; built-in line
    assert "very start of the show" in prompts[0] and "Listener's first name: admin" in prompts[0]
    assert first["talks"][0]["kind"] == "open" and first["talks"][0]["next"] == first["tracks"][0]["id"]
    seen = [t["id"] for t in first["tracks"]]
    nxt = client.post("/api/dj/next", json={"exclude": seen, "previous": seen[-1], "when": "Saturday", "hour": 21, "minute": 20}).json()
    assert nxt["kind"] == "break" and nxt["sting"] is True and nxt["post"] > 0
    assert "Saturday, twenty past nine in the evening" in prompts[0]  # the opening gives the time...
    assert "Just played:" in prompts[-1] and "When:" not in prompts[-1]  # ...the next break doesn't
    assert "no welcome or hello" in prompts[-1]
    assert nxt["tracks"] and nxt["theme"] != first["theme"]  # (a 4-song shelf: repeats allowed)


def test_dj_with_a_writer(client, monkeypatch):
    calls = []
    monkeypatch.setattr(dj, "write", lambda *a, **k: calls.append(k) or '{"intro": "Hey admin, here\'s one you love.", "links": {}}')
    login(client)
    r = client.post("/api/dj/next", json={"first": True}).json()
    assert r["text"].startswith("Hey admin, here's one you love. Here's ") and r["written"] is True  # song named
    assert calls[0]["json_mode"] is True and len(calls) == 1  # one request for the whole set


def test_dj_settings_are_admin_only_and_keep_the_key_secret(client):
    login(client)
    s = client.patch("/api/dj/settings", json={"provider": "gemini", "key": "secret-key", "voice": "bf_emma"}).json()
    assert s["hasKey"] is True and "key" not in s and s["voice"] == "bf_emma"
    assert s["provider"] == "gemini" and s["defaultModel"]
    client.post("/api/users", json={"username": "sam", "password": "sam-pass"})
    from fastapi.testclient import TestClient
    with TestClient(client.app) as other:
        other.post("/api/login", json={"username": "sam", "password": "sam-pass"})
        assert other.get("/api/dj/settings").status_code == 403
        assert other.post("/api/dj/next", json={"first": True}).status_code == 200  # everyone gets the DJ


def test_cleaning_model_output():
    assert dj.clean('<think>hmm</think> **Hey** "Etienne" 🎸 here\'s *War Pigs*.') == "Hey Etienne here's War Pigs."
    assert len(dj.clean("word " * 100).split()) <= 61
    assert dj.year_words(1970) == "19 70" and dj.year_words(2004) == "two thousand four"


def test_pronunciation_and_titles():
    assert dj.for_speech("YUNGBLUD and Måneskin", {"Slipknot": "Slip-not"}) == "Youngblood and Maaneskin"
    assert dj.for_speech("Slipknot", dj.parse_say("Slipknot = Slip-not")) == "Slip-not"
    assert dj.speakable_title("Snuff (Radio Edit)") == "Snuff"
    assert dj.speakable_title("Paranoid - 2009 Remaster") == "Paranoid"
    snuff = {"title": "Snuff (Radio Edit)", "artist": "Slipknot", "album": "Snuff (Promo)"}
    pigs = {"title": "War Pigs - 2009 Remaster", "artist": "Black Sabbath", "album": "Paranoid"}
    line = dj.fallback_line("break", "Etienne", 21, pigs, snuff, {"theme": "discover", "tracks": [snuff]})
    assert line.startswith("That was War Pigs by Black Sabbath.") and "Snuff by Slipknot" in line and "Radio Edit" not in line
    assert dj.fallback_line("open", "Etienne", 21, None, snuff, {"theme": "discover"}).count("Shelf Radio") == 1


def test_radio_prompt():
    nxt = {"title": "Snuff", "artist": "Slipknot", "album": "All Hope Is Gone", "year": 2008}
    p = dj.prompt_for("break", "Etienne", "Saturday 9:20 PM", {"title": "War Pigs", "artist": "Black Sabbath", "album": "Paranoid"},
                      nxt, {"brief": "Deeper cuts.", "why": None, "tracks": [nxt, {"title": "Psychosocial", "artist": "Slipknot"}]},
                      "They've played it 4 times this month.", None, None, "Sam has played Slipknot 5 times this week.", 12)
    assert "Just played: War Pigs by Black Sabbath" in p and "Local time: Saturday 9:20 PM" in p
    assert "Later in this set" in p and "Psychosocial" in p and "Sam has played" in p and "at most 31 words" in p


def test_say_list_saved(client):
    login(client)
    s = client.patch("/api/dj/settings", json={"say": "Slipknot = Slip-not", "voice": "gemini:Puck"}).json()
    assert s["say"] == "Slipknot = Slip-not" and s["voice"] == "gemini:Puck" and s["hasGeminiKey"] is False


def test_dj_link(client, monkeypatch):
    monkeypatch.setattr(dj, "write_line", lambda *a: None)
    login(client)
    ids = [t["id"] for t in client.get("/api/tracks/random?limit=2").json()]
    r = client.post("/api/dj/link", json={"previous": ids[0], "next": ids[1], "hour": 9}).json()
    assert r["kind"] == "link" and r["sting"] is False and r["next"] == ids[1] and r["text"].startswith("That was")


class FakeLocal:
    """Stands in for llama.cpp: 'installed', and answers every line."""
    def __init__(self):
        self.calls = []
    def installed(self):
        return ["small"]
    def chat(self, key, system, prompt, max_tokens=160, json_mode=False, schema=None):
        self.calls.append((key, prompt, json_mode, system, schema))
        return '<think>hmm</think> {"intro": "Alright, this is Shelf Radio, and here\'s one for you.", "links": {}}' 
    def info(self):
        return {"models": {}, "running": False, "installing": None}


def test_builtin_writer(client, monkeypatch):
    fake = FakeLocal()
    monkeypatch.setattr(dj, "local_writer", fake)
    login(client)
    client.patch("/api/dj/settings", json={"provider": "builtin", "model": "small"})
    r = client.post("/api/dj/next", json={"first": True}).json()
    assert r["text"].startswith("Alright, this is Shelf Radio, and here's one for you.") and r["written"] is True
    assert fake.calls[0][0] == "small" and fake.calls[0][2] is True and "Write JSON" in fake.calls[0][1]
    assert fake.calls[0][3] == dj.SET_SYSTEM  # the same opening every time, so llama.cpp keeps it loaded
    assert fake.calls[0][4]["required"] == ["intro", "links"]  # the answer's shape is enforced


def test_prepared_opening(client, monkeypatch):
    import time as _t
    monkeypatch.setattr(dj, "write", lambda *a, **k: '{"intro": "Prepared hello."}')
    login(client)
    assert client.post("/api/dj/prepare", json={"when": "Saturday evening", "hour": 19}).json()["ok"]
    for _ in range(50):
        r = client.post("/api/dj/next", json={"first": True})
        if r.json().get("text", "").startswith("Prepared hello."):
            break
        _t.sleep(0.05)
    assert r.json()["text"].startswith("Prepared hello.") and r.json()["kind"] == "open"


def test_a_set_with_links_in_one_request(client, monkeypatch, library):
    """Five songs: a break before the first and a link before the fourth, from one answer."""
    calls = []
    monkeypatch.setattr(dj, "write", lambda *a, **k: calls.append(a[4]) or
                        '{"intro": "Big opener.", "links": {"4": "That was lovely. Here is another."}}')
    import shelf.app as appmod
    seg = {"theme": "deep", "brief": "Deeper cuts.", "why": None,
           "tracks": [{"id": i, "title": f"Song {i}", "artist": "Band", "album": "First", "year": 2001, "mix": None}
                      for i in range(1, 6)]}
    login(client)
    # Drive _dj_set through the endpoint with a fixed set: patch the segment picker.
    app = client.app
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/dj/next")
    closure = {c.cell_contents.__name__: c.cell_contents for c in route.endpoint.__closure__
               if callable(c.cell_contents) and hasattr(c.cell_contents, "__name__")}
    assert "_dj_set" in closure
    talks = closure["_dj_set"]("break", type("U", (), {"id": 1, "username": "admin"})(), seg, None, "Saturday", 21, 20)
    assert [t["kind"] for t in talks] == ["break", "link"] and talks[1]["next"] == 4
    assert talks[0]["text"] == "Big opener. Here's Song 1 by Band." and talks[1]["text"].startswith("That was lovely.")
    assert len(calls) == 1 and '"4": "..."' in calls[0] and "before song 4" in calls[0]


def test_time_words_and_notes():
    assert dj.time_words(21, 20) == "twenty past nine in the evening"
    assert dj.time_words(0, 10) == "ten past twelve at night"
    assert dj.time_words(14, 45) == "quarter to three in the afternoon"
    assert dj.parse_notes('{"facts": ["Formed in Des Moines.", "Nine members."]}') == ["Formed in Des Moines.", "Nine members."]
    assert dj.first_sentence("Slipknot is a band from Iowa. They wear masks.") == "Slipknot is a band from Iowa."


def test_fit_keeps_the_song_name():
    long = "Welcome to Shelf Radio, it's ten to eight. Tonight you've been stuck on these. Big treat coming. Here's Wild Woman by Aerosmith."
    out = dj.fit(long, 12)
    assert out.endswith("Here's Wild Woman by Aerosmith.") and len(out.split()) < len(long.split())
    assert dj.fit("Short and sweet. Here's War Pigs.", 20) == "Short and sweet. Here's War Pigs."


def test_lines_always_name_their_song():
    t = {"title": "cotton candy", "artist": "YUNGBLUD"}
    assert dj.ensure_named("Welcome to Shelf Radio, let's keep it loud!", t).endswith("Here's cotton candy by YUNGBLUD.")
    assert dj.ensure_named("Here's Cotton Candy, turn it up.", t) == "Here's Cotton Candy, turn it up."


def test_titles_with_letters_in_brackets():
    assert dj.speakable_title("(O)rdinary") == "Ordinary"
    assert dj.speakable_title("(D)eath (Live)") == "Death"


def test_requests_and_feedback(client, monkeypatch):
    monkeypatch.setattr(dj, "write", lambda *a, **k: None)  # built-in lines; requests read from the words
    login(client)
    r = client.post("/api/dj/request", json={"text": "play me some Band please", "hour": 20}).json()
    assert r["understood"]["artist"].lower() == "band" and r["theme"] == "spotlight" and r["kind"] == "request"
    assert r["text"].startswith(("You asked", "Request taken", "Good call"))
    r = client.post("/api/dj/request", json={"text": "something chill for studying", "hour": 20}).json()
    assert r["understood"]["energy"] == 0.15
    # Feedback is stored and steers sets: a skipped song sits out.
    tid = r["tracks"][0]["id"]
    assert client.post("/api/dj/feedback", json={"kind": "skip", "track": tid, "theme": r["theme"]}).json()["ok"]
    assert client.post("/api/dj/feedback", json={"kind": "up", "text": "Nice line."}).json()["ok"]
    assert client.post("/api/dj/feedback", json={"kind": "bogus"}).status_code == 422
    nxt = client.post("/api/dj/next", json={"first": True, "hour": 20}).json()
    assert tid not in [t["id"] for t in nxt["tracks"]] or len(nxt["tracks"]) >= 3  # (tiny shelf: may come back)


def test_countdown_fallback_lines():
    line = dj.fallback_line("link", "Etienne", 20, {"title": "A", "artist": "B"}, {"title": "C", "artist": "D", "rank": 3}, None)
    assert line == "That was A by B. At number 3 this week, C by D."


def test_two_hosts(client, monkeypatch):
    seen = {}
    def fake(*a, **k):
        seen["schema"], seen["prompt"] = k.get("schema"), a[4]
        return '{"intro": [{"host": "A", "line": "Big night on Shelf Radio."}, {"host": "B", "line": "It really is."}, {"host": "A", "line": "Turn it up."}], "links": {}}'
    monkeypatch.setattr(dj, "write", fake)
    login(client)
    client.patch("/api/dj/settings", json={"provider": "gemini", "key": "x", "cohost": "bf_emma"})
    r = client.post("/api/dj/next", json={"first": True}).json()
    assert r["duo"] is True and r["text"].startswith("Big night on Shelf Radio.\nIt really is.\nTurn it up. Here's ")
    assert seen["schema"]["properties"]["intro"]["type"] == "array" and "two hosts" in seen["prompt"]
    client.patch("/api/dj/settings", json={"cohost": ""})
    assert "duo" not in client.post("/api/dj/next", json={"first": True}).json()
