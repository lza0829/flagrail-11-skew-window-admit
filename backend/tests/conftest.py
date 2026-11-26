"""pytest 公共夹具：把数据目录指到临时处，保证用例隔离、不污染工作区。"""
import os
import tempfile
from pathlib import Path

# 必须在 import app.* 之前设置，使 db.数据目录/库路径 落到临时目录。
os.environ.setdefault("数据目录", tempfile.mkdtemp(prefix="flagrail-pytest-"))

import pytest  # noqa: E402


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    from app import db
    p = tmp_path / "时间窗测试.db"
    monkeypatch.setattr(db, "库路径", p)
    from app import seed
    seed.初始化库()
    return p


@pytest.fixture
def client(db_path):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def chain(client):
    """建一条时间窗测试链，返回票号/版本/桶与三联时刻构造器。"""
    from datetime import datetime, timedelta, timezone

    def iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    D, C = now - timedelta(seconds=600), now
    client.post("/api/入轨", json={"版本": [{"开关键": "tw.pytest", "版本号": 1, "版本键": "tw.pytest@1"}]})
    client.post("/api/分桶", json={"桶键": "tw-pt-b", "开关键": "tw.pytest"})
    client.post("/api/下发", json={"票号": "tw-pt-t", "版本键": "tw.pytest@1",
                                   "桶键": "tw-pt-b", "下发时": iso(D)})
    return {"client": client, "D": D, "C": C, "iso": iso, "票号": "tw-pt-t", "vk": "tw.pytest@1"}
