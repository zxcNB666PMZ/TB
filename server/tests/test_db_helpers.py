# -*- coding: utf-8 -*-
"""db 层辅助函数与密码哈希测试"""

import db


class TestLikeEscape:
    def test_escape_percent_and_underscore(self):
        assert db._like_escape("100%") == "100\\%"
        assert db._like_escape("a_b") == "a\\_b"
        assert db._like_escape("back\\slash") == "back\\\\slash"

    def test_plain_text_untouched(self):
        assert db._like_escape("滴滴出行") == "滴滴出行"


class TestNumAndDate:
    def test_num(self):
        assert db._num("1,234.56") == 1234.56
        assert db._num(88) == 88.0
        assert db._num(None) is None
        assert db._num("abc") is None

    def test_date(self):
        assert str(db._date("2026-11-01")) == "2026-11-01"
        assert db._date("2026/11/01") == "2026-11-01"
        assert db._date("") is None
        assert db._date("2026年11月01日") == "2026-11-01"


class TestPasswordHashing:
    def test_hash_format(self):
        hashed = db.hash_password("123456")
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60
        assert hashed != "123456"

    def test_same_password_different_salt(self):
        assert db.hash_password("123456") != db.hash_password("123456")

    def test_is_hash(self):
        assert db._is_hash(db.hash_password("x"))
        assert not db._is_hash("123456")
        assert not db._is_hash("")
        assert not db._is_hash(None)


class TestVerifyLogin:
    def test_correct_password(self, monkeypatch):
        hashed = db.hash_password("secret")
        monkeypatch.setattr(db, "find_user", lambda u: {"username": u, "password": hashed, "role": "管理员"})
        user, upgraded = db.verify_login("admin", "secret")
        assert user is not None
        assert upgraded is False

    def test_wrong_password(self, monkeypatch):
        hashed = db.hash_password("secret")
        monkeypatch.setattr(db, "find_user", lambda u: {"username": u, "password": hashed, "role": "管理员"})
        user, upgraded = db.verify_login("admin", "wrong")
        assert user is None
        assert upgraded is False

    def test_unknown_user(self, monkeypatch):
        monkeypatch.setattr(db, "find_user", lambda u: None)
        user, upgraded = db.verify_login("nobody", "secret")
        assert user is None

    def test_plaintext_auto_upgrade(self, monkeypatch):
        calls = {}

        monkeypatch.setattr(
            db, "find_user", lambda u: {"username": u, "password": "123456", "role": "管理员"}
        )

        def fake_set_password(username, password):
            calls["username"] = username
            calls["password"] = password

        monkeypatch.setattr(db, "set_password", fake_set_password)
        user, upgraded = db.verify_login("admin", "123456")
        assert user is not None
        assert upgraded is True
        assert calls == {"username": "admin", "password": "123456"}

    def test_plaintext_wrong_not_upgraded(self, monkeypatch):
        monkeypatch.setattr(
            db, "find_user", lambda u: {"username": u, "password": "123456", "role": "管理员"}
        )
        monkeypatch.setattr(db, "set_password", lambda u, p: (_ for _ in ()).throw(AssertionError("不应调用")))
        user, upgraded = db.verify_login("admin", "wrong")
        assert user is None
        assert upgraded is False
