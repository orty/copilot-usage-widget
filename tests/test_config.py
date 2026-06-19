import json
import pytest
from pathlib import Path


def test_load_config_defaults(W, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "CONFIG_PATH", tmp_path / "config.json")
    cfg = W.load_config()
    assert cfg.oauth_token == ""
    assert cfg.refresh_interval == W.POLL_DEFAULT
    assert cfg.display_mode == "essential"
    assert cfg.notified == {}


def test_load_config_reads_file(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"oauth_token": "gho_abc", "refresh_interval": 60}))
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.oauth_token == "gho_abc"
    assert cfg.refresh_interval == 60


def test_load_config_clamps_interval(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"refresh_interval": 1}))
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.refresh_interval == W.POLL_MIN


def test_load_config_corrupted_json(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("not json{{")
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.load_config()
    assert cfg.oauth_token == ""


def test_save_config_roundtrip(W, tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    cfg = W.AppConfig(oauth_token="gho_xyz", refresh_interval=30)
    W.save_config(cfg)
    raw = json.loads(p.read_text())
    assert raw["oauth_token"] == "gho_xyz"
    assert raw["refresh_interval"] == 30


def test_save_config_creates_parent_dirs(W, tmp_path, monkeypatch):
    p = tmp_path / "nested" / "deep" / "config.json"
    monkeypatch.setattr(W, "CONFIG_PATH", p)
    W.save_config(W.AppConfig())
    assert p.exists()
