from app.config import (Config, DEFAULT_SHORTCUTS, load_config, save_config, is_local_url,
                        validate_shortcut, validate_shortcuts, normalize_shortcut)


def test_defaults_valid():
    assert Config().validate() == []


def test_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    c = Config(model="llama3.2:1b", context_length=2048)
    save_config(c, p)
    assert load_config(p).model == "llama3.2:1b"
    assert load_config(p).context_length == 2048


def test_missing_and_corrupt_file(tmp_path):
    assert load_config(tmp_path / "none.json") == Config()
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_config(p) == Config()
    p.write_text("[1,2]")
    assert load_config(p) == Config()


def test_invalid_values_reset():
    c = Config.from_dict({"context_length": -5, "temperature": 99, "theme": "neon",
                          "unknown": 1, "ollama_url": "http://evil.example.com:11434"})
    assert c.context_length == 4096 and c.temperature == 0.2 and c.theme == "dark"
    assert c.ollama_url == "http://127.0.0.1:11434"
    assert c.validate() == []


def test_remote_url_rejected():
    assert is_local_url("http://localhost:11434")
    assert not is_local_url("http://192.168.1.5:11434")
    assert not is_local_url("ftp://127.0.0.1")
    assert Config(ollama_url="https://api.example.com").validate()


def test_bad_shortcuts_fall_back():
    c = Config.from_dict({"shortcuts": {"capture": "s", "submit": "ctrl+shift+s"}})
    assert c.shortcuts == DEFAULT_SHORTCUTS


def test_custom_shortcuts_kept_and_normalized():
    c = Config.from_dict({"shortcuts": {"capture": "Shift+Ctrl+F9"}})
    assert c.shortcuts["capture"] == "ctrl+shift+f9"
    assert c.shortcuts["submit"] == DEFAULT_SHORTCUTS["submit"]


def test_no_secrets_in_config():
    bad = ("api_key", "apikey", "secret", "password", "auth")
    assert not any(b in k for k in Config().to_dict() for b in bad)
