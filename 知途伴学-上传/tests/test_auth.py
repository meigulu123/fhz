"""账户体系测试：注册 / 登录校验 / 密码哈希（PBKDF2-SHA256，标准库实现）"""
import pytest

from src.memory.db import MemoryStore


@pytest.fixture()
def mem(tmp_path):
    m = MemoryStore(str(tmp_path / "auth.db"))
    yield m
    m.close()


def test_create_and_login(mem):
    assert mem.create_account("alice", "pass123") is True
    assert mem.account_exists("alice") is True
    assert mem.check_account("alice", "pass123") is True
    assert mem.check_account("alice", "wrong-pass") is False
    assert mem.check_account("nobody", "x") is False


def test_duplicate_account_rejected(mem):
    assert mem.create_account("bob", "1234") is True
    assert mem.create_account("bob", "5678") is False  # 用户名唯一


def test_change_password(mem):
    mem.create_account("dave", "old123")
    assert mem.change_password("dave", "wrong", "new123") is False   # 原密码错
    assert mem.check_account("dave", "old123") is True
    assert mem.change_password("dave", "old123", "new123") is True
    assert mem.check_account("dave", "old123") is False
    assert mem.check_account("dave", "new123") is True


def test_account_info_and_stats(mem):
    mem.create_account("erin", "pass123")
    info = mem.account_info("erin")
    assert info["username"] == "erin" and info["created_at"] > 0
    assert mem.account_info("ghost") is None
    sid = mem.start_session("erin")
    mem.log_interaction(sid, "erin", "message", "", "hi")
    mem.snapshot_mastery("erin", "m01", 0.5, 1)
    stats = mem.account_stats("erin")
    assert stats == {"sessions": 1, "interactions": 1, "reflections": 0,
                     "snapshots": 1, "plans": 0}


def test_clear_student_data_keeps_account(mem):
    mem.create_account("frank", "pass123")
    sid = mem.start_session("frank")
    mem.log_interaction(sid, "frank", "message", "", "hi")
    mem.save_plan(sid, "frank", 1.0, {}, {"items": []})
    assert mem.clear_student_data("frank") >= 3
    assert mem.account_stats("frank")["sessions"] == 0
    assert mem.check_account("frank", "pass123") is True   # 账户本身保留


def test_password_stored_hashed(mem):
    mem.create_account("carol", "secret1")
    row = mem.conn.execute(
        "SELECT password_hash FROM accounts WHERE username='carol'").fetchone()
    stored = row["password_hash"]
    assert "secret1" not in stored      # 不明文存储
    assert stored.count("$") == 1       # 盐$摘要 格式
    salt_hex, digest_hex = stored.split("$")
    assert len(bytes.fromhex(salt_hex)) == 16
    assert len(bytes.fromhex(digest_hex)) == 32
