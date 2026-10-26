"""Web 任务页测试（ADR-14）：列表 / 提交 / 轮询 / 审批签名发布。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store import baseline
from bacmap.store.strain_metadata import StrainMetadataService


def _sal_summary() -> dict:
    return {
        "sample": "SAM-001",
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
            "qc": {"after_filtering": {"total_reads": 1000}},
            "dec": {},
        },
    }


class _Proc:
    returncode = 0


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    meta = StrainMetadataService(tmp_path / "data" / "metadata.sqlite")
    meta.upsert(
        "SAM-001",
        {
            "sample_id": "S1",
            "isolation_date": "2025-06-01",
            "province": "Guangdong",
            "city": "Shenzhen",
            "sample_source": "food",
        },
    )
    monkeypatch.setattr(eng, "_run_snakemake", lambda p: _Proc())
    monkeypatch.setattr(eng, "_generate_report_for", lambda s: {"sample_id": s})
    monkeypatch.setattr(eng, "_step_create_run", lambda p: {"run_id": "web-run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda rid, p: None)
    import contextlib

    class _Arb:
        @contextlib.contextmanager
        def heavy_step(self):
            yield

    monkeypatch.setattr(eng, "_memory_arbiter", lambda: _Arb())
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


@pytest.fixture
def client(engine):
    yield TestClient(create_app(engine)), Path(engine.home)


def _poll_fragment(c: TestClient, tid: str, want: str, timeout_s: float = 30.0) -> str:
    deadline = time.time() + timeout_s
    body = ""
    while time.time() < deadline:
        body = c.get(f"/tasks/{tid}/fragment").text
        if want in body:
            return body
        time.sleep(0.2)
    return body


class TestWebInterface:
    def test_index_returns_page(self, client):
        c, _ = client
        r = c.get("/")
        assert r.status_code == 200
        assert "bacmap" in r.text
        assert "暂无任务" in r.text or "SAM-" in r.text

    def test_submit_analyze_polls_to_succeeded(self, client):
        c, _ = client
        r = c.post(
            "/tasks/submit",
            data={"task_type": "analyze", "samples": "SAM-001"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        tid = str(r.url).rstrip("/").split("/")[-1]
        body = _poll_fragment(c, tid, "succeeded")
        assert "succeeded" in body

    def test_curate_approve_publishes_baseline(self, client):
        c, home = client
        r = c.post(
            "/tasks/submit",
            data={"task_type": "curate", "scope": "{}"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        tid = str(r.url).rstrip("/").split("/")[-1]
        body = _poll_fragment(c, tid, "awaiting_approval")
        assert "awaiting_approval" in body
        assert "审批签名" in body

        r2 = c.post(
            f"/tasks/{tid}/approve",
            data={"approver": "reviewer", "decision": "approve", "signature": "sig-web"},
            follow_redirects=True,
        )
        assert r2.status_code == 200
        assert "published baseline v1" in r2.text
        releases = baseline.list_releases(home / "baseline.sqlite")
        assert len(releases) == 1
        assert releases[0]["n_strains"] == 1

    def test_unknown_task_type_rejected(self, client):
        c, _ = client
        r = c.post("/tasks/submit", data={"task_type": "deploy", "samples": "X"})
        assert r.status_code == 400

    def test_analyze_without_samples_rejected(self, client):
        c, _ = client
        r = c.post("/tasks/submit", data={"task_type": "analyze", "samples": ""})
        assert r.status_code == 400

    def test_open_path_task_type_rejected(self, client):
        c, _ = client
        r = c.post("/tasks/submit", data={"task_type": "mine", "samples": "SAM-001"})
        assert r.status_code == 400

    def test_unknown_task_404(self, client):
        c, _ = client
        assert c.get("/tasks/nope").status_code == 404
        assert c.get("/tasks/nope/fragment").status_code == 404

    def test_overview_page(self, client):
        c, home = client
        from sqlite3 import connect

        conn = connect(home / "tasks.sqlite")
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at, workflow_id, current_step)"
            " VALUES ('ov-1','analyze','succeeded','{}','t','2026-01-01T00:00:00',"
            "'2026-01-01T00:00:00','','analyze')"
        )
        conn.commit()
        conn.close()
        r = c.get("/overview")
        assert r.status_code == 200
        assert "系统概览" in r.text
        assert "LLM 端点" in r.text
        assert "D1" in r.text
        assert "BACMAP_HOME" in r.text
        assert "任务分布" in r.text
        assert "succeeded" in r.text


class TestResultsPages:
    """结果查询界面（深度补全：任务台之外的人工查询面）。"""

    def test_samples_page_lists_completed(self, client):
        c, _ = client
        r = c.get("/samples")
        assert r.status_code == 200
        assert "SAM-001" in r.text
        assert "Salmonella" in r.text

    def test_sample_detail_shows_species(self, client):
        c, _ = client
        r = c.get("/samples/SAM-001")
        assert r.status_code == 200
        assert "Salmonella" in r.text
        assert "blaCTX-M-15" in r.text

    def test_missing_sample_404(self, client):
        c, _ = client
        assert c.get("/samples/NOPE").status_code == 404

    def test_search_finds_by_gene(self, client):
        c, _ = client
        r = c.get("/search", params={"query": "blaCTX-M-15"})
        assert r.status_code == 200
        assert "SAM-001" in r.text

    def test_report_file_route_404_when_absent(self, client):
        c, _ = client
        assert c.get("/samples/SAM-001/report").status_code == 404

    def test_report_route_rejects_path_traversal(self, client):
        c, _ = client
        # urllib 对 ..%2f 的处理因版本而异；用编码斜杠确保路径参数带 .. 语义
        r = c.get("/samples/..%2f..%2fetc%2fpasswd/report")
        assert r.status_code in (400, 404)

    def test_sample_detail_rejects_path_traversal(self, client):
        c, _ = client
        r = c.get("/samples/..%2f..%2fetc%2fpasswd")
        assert r.status_code in (400, 404)


class TestWebAuth:
    """ADR-14：配置 token 时局域网访问需鉴权（未配置则本机直通）。"""

    def test_token_enforced(self, engine):
        c = TestClient(create_app(engine, auth_token="tok"))
        assert c.get("/").status_code == 401
        assert c.get("/", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/", headers={"Authorization": "Bearer tok"}).status_code == 200

    def test_no_token_means_no_auth(self, engine):
        c = TestClient(create_app(engine))
        assert c.get("/").status_code == 200


class TestAssistantRemoved:
    """v1.6（ADR-21）：Web 内置助手页移除；计划确认留在 /plans。"""

    def test_assistant_routes_gone(self, client):
        c, _ = client
        assert c.get("/assistant").status_code == 404
        assert c.post("/assistant", data={"sid": "", "text": "x"}).status_code == 404
        assert c.post("/assistant/execute", data={"sid": "nope"}).status_code == 404
        assert "/assistant" not in c.get("/").text
        assert 'href="/plans"' in c.get("/").text

class TestWebCookieAuth:
    """v1.4.15：浏览器 cookie 会话 + CSRF（BACMAP_WEB_AUTH=cookie）。"""

    def _client(self, engine, monkeypatch) -> TestClient:
        monkeypatch.setenv("BACMAP_WEB_AUTH", "cookie")
        monkeypatch.setenv("BACMAP_WEB_SECRET", "s3cr3t-sign")
        return TestClient(create_app(engine, auth_token="tok"))

    def test_unauthenticated_html_redirects_to_login(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login")

    def test_unauthenticated_xhr_gets_401(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        assert c.get("/tasks/nope/fragment").status_code == 401

    def test_login_sets_httponly_cookies_and_grants_access(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        r = c.post("/login", data={"token": "tok", "next": "/"}, follow_redirects=False)
        assert r.status_code == 303
        set_cookie = r.headers.get("set-cookie", "")
        assert "bacmap_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "samesite=strict" in set_cookie.lower()
        assert "bacmap_csrf=" in set_cookie
        assert c.get("/", headers={"accept": "text/html"}).status_code == 200

    def test_login_wrong_token_401(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        assert c.post("/login", data={"token": "nope", "next": "/"}).status_code == 401

    def test_bearer_still_works_in_cookie_mode(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        assert c.get("/", headers={"Authorization": "Bearer tok"}).status_code == 200

    def test_open_redirect_blocked(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        r = c.post(
            "/login", data={"token": "tok", "next": "https://evil.example"}, follow_redirects=False
        )
        assert r.headers["location"] == "/"

    def test_post_without_csrf_forbidden(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        c.post("/login", data={"token": "tok", "next": "/"})
        r = c.post(
            "/tasks/submit",
            data={"task_type": "analyze", "samples": "SAM-001"},
            headers={"origin": "http://testserver"},
        )
        assert r.status_code == 403

    def test_post_with_csrf_ok(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        c.post("/login", data={"token": "tok", "next": "/"})
        csrf = c.cookies.get("bacmap_csrf")
        r = c.post(
            "/tasks/submit",
            data={"task_type": "analyze", "samples": "SAM-001", "csrf": csrf},
            headers={"origin": "http://testserver"},
            follow_redirects=False,
        )
        assert r.status_code == 303

    def test_post_cross_origin_rejected(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        c.post("/login", data={"token": "tok", "next": "/"})
        csrf = c.cookies.get("bacmap_csrf")
        r = c.post(
            "/tasks/submit",
            data={"task_type": "analyze", "samples": "SAM-001", "csrf": csrf},
            headers={"origin": "http://evil.example"},
        )
        assert r.status_code == 403

    def test_logout_clears_session(self, engine, monkeypatch):
        c = self._client(engine, monkeypatch)
        c.post("/login", data={"token": "tok", "next": "/"})
        csrf = c.cookies.get("bacmap_csrf")
        assert c.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
        r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303

    def test_logout_requires_csrf(self, engine, monkeypatch):
        """登出也是状态变更 POST：跨站不得强制登出（错误的 csrf → 403）。"""
        c = self._client(engine, monkeypatch)
        c.post("/login", data={"token": "tok", "next": "/"})
        r = c.post("/logout", data={"csrf": "wrong"}, follow_redirects=False)
        assert r.status_code == 403

    def test_expired_session_rejected(self, engine, monkeypatch):
        import time

        from bacmap.interfaces.web.auth import SESSION_COOKIE, _sign

        c = self._client(engine, monkeypatch)
        past = int(time.time()) - 10
        c.cookies.set(SESSION_COOKIE, f"sid.{past}.{_sign('s3cr3t-sign', 'sid', past)}")
        r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303


class TestWebHardening:
    """巡检加固：安全头 / 报告下载 / 助手输入边界 / 会话上限。"""

    def test_security_headers_present(self, client):
        c, _ = client
        r = c.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert csp.startswith("default-src 'self'")
        assert "frame-ancestors 'none'" in csp
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"

    def test_security_headers_on_401(self, engine):
        c = TestClient(create_app(engine, auth_token="tok"))
        r = c.get("/")
        assert r.status_code == 401
        assert "content-security-policy" in r.headers

    def test_report_inline_by_default_and_sandboxed(self, client):
        """v1.4.25：默认内联查看（sandbox CSP 隔离），下载走 ?download=1。"""
        c, home = client
        rep = home / "results" / "SAM-001" / "report" / "SAM-001_report.html"
        rep.write_text("<html><body>ok</body></html>", encoding="utf-8")
        r = c.get("/samples/SAM-001/report")
        assert r.status_code == 200
        assert "inline" in r.headers.get("content-disposition", "").lower()
        assert "sandbox" in r.headers.get("content-security-policy", "")
        r2 = c.get("/samples/SAM-001/report?download=1")
        assert "attachment" in r2.headers.get("content-disposition", "")


class TestWebBearerLogin:
    """v1.4.25：bearer 模式下 /login 不再重定向（旧实现与中间件形成死循环）。"""

    def test_login_page_explains_bearer_mode(self, engine, monkeypatch):
        monkeypatch.delenv("BACMAP_WEB_AUTH", raising=False)
        c = TestClient(create_app(engine, auth_token="tok"))
        r = c.get("/login", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 200  # 不是 303
        assert "bearer" in r.text
        assert "BACMAP_WEB_AUTH=cookie" in r.text

    def test_html_navigation_gets_401_with_hint_not_redirect(self, engine, monkeypatch):
        monkeypatch.delenv("BACMAP_WEB_AUTH", raising=False)
        c = TestClient(create_app(engine, auth_token="tok"))
        r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 401
        assert "/login" in r.text  # 给出可操作提示

    def test_api_clients_still_get_plain_401(self, engine, monkeypatch):
        monkeypatch.delenv("BACMAP_WEB_AUTH", raising=False)
        c = TestClient(create_app(engine, auth_token="tok"))
        r = c.get("/tasks/nope/fragment")
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"


class TestWebNoAuthLoginPage:
    """/login 始终可达：未启用鉴权时给出说明，而非静默重定向。"""

    def test_login_page_when_auth_disabled(self, engine):
        c = TestClient(create_app(engine, auth_token=None))
        r = c.get("/login", follow_redirects=False)
        assert r.status_code == 200
        assert "无需登录" in r.text


class TestSampleReportDelivery:
    """报告默认内联查看（sandbox CSP），?download=1 才附件下载。"""

    def _client_with_report(self, engine) -> TestClient:
        rep = Path(engine.home) / "results" / "SAM-001" / "report"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "SAM-001_report.html").write_text(
            "<!doctype html><html><body><h1>报告</h1></body></html>", encoding="utf-8"
        )
        return TestClient(create_app(engine, auth_token=None))

    def test_inline_by_default_with_sandbox_csp(self, engine):
        c = self._client_with_report(engine)
        r = c.get("/samples/SAM-001/report")
        assert r.status_code == 200
        assert "attachment" not in r.headers.get("content-disposition", "").lower()
        assert "inline" in r.headers["content-disposition"].lower()
        csp = r.headers["content-security-policy"]
        assert "sandbox" in csp and "default-src 'none'" in csp
        assert "报告" in r.text

    def test_download_flag_forces_attachment(self, engine):
        c = self._client_with_report(engine)
        r = c.get("/samples/SAM-001/report?download=1")
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"].lower()

    def test_detail_page_offers_both_links(self, engine):
        c = self._client_with_report(engine)
        r = c.get("/samples/SAM-001")
        assert r.status_code == 200
        assert "/samples/SAM-001/report" in r.text
        assert "/samples/SAM-001/report?download=1" in r.text
