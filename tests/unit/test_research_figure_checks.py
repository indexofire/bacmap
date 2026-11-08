"""图片产物质量门（P2 PDF/PNG 校验）：纯 stdlib、确定性、贴合 matplotlib 现实。

关键回归：bacmap-figures:py312（matplotlib 3.10，pdf fonttype=3 默认）产出的
PDF 形态 = /BaseFont + /Subtype /Type3、无 /FontFile —— Type3 字形程序内联，
必须判为已嵌入。
"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from bacmap.research import figure_checks
from bacmap.research.figures import build_artifact

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (
        len(body).to_bytes(4, "big") + kind + body +
        (zlib.crc32(kind + body) & 0xFFFFFFFF).to_bytes(4, "big")
    )


def _png(
    *, dpi: int | None = 300, color_type: int = 2, width: int = 8, height: int = 6
) -> bytes:
    ihdr = (
        width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, color_type, 0, 0, 0])
    )
    parts = [_SIG, _chunk(b"IHDR", ihdr)]
    if dpi is not None:
        ppm = round(dpi / 0.0254)
        parts.append(_chunk(b"pHYs", ppm.to_bytes(4, "big") + ppm.to_bytes(4, "big") + b"\x01"))
    parts.append(_chunk(b"IDAT", zlib.compress(b"")))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


# matplotlib Type3 形态（真实 figure_custom.pdf 的 token 分布）
_MPL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
    b"4 0 obj << /Type /Font /Subtype /Type3 /BaseFont /Helvetica >> endobj\n"
    b"trailer << /Root 1 0 R >>\n%%EOF"
)


class TestPdf:
    def test_matplotlib_type3_passes(self):
        assert figure_checks.validate_output(
            _write(_MPL_PDF, ".pdf"), min_dpi=300
        ) == []

    def test_fontfile_passes(self):
        pdf = _MPL_PDF.replace(b"/Subtype /Type3", b"/Subtype /TrueType") + b" /FontFile2 5 0 R"
        assert figure_checks.validate_output(_write(pdf, ".pdf"), min_dpi=300) == []

    def test_unembedded_font_rejected(self):
        pdf = _MPL_PDF.replace(b"/Subtype /Type3 ", b"/Subtype /Type1 ")
        problems = figure_checks.validate_output(_write(pdf, ".pdf"), min_dpi=300)
        assert any("字体" in p and "嵌入" in p for p in problems)

    def test_bad_header_rejected(self):
        problems = figure_checks.validate_output(_write(b"not a pdf", ".pdf"), min_dpi=300)
        assert any("%PDF-" in p for p in problems)

    def test_no_pages_rejected(self):
        pdf = _MPL_PDF.replace(b"/Type /Page /Parent", b"/Foo /Page /Parent")
        problems = figure_checks.validate_output(_write(pdf, ".pdf"), min_dpi=300)
        assert any("页" in p for p in problems)

    def test_image_only_pdf_passes(self):
        # 无字体 token（纯图像图 / ObjStm 不可见）——放行面，模块文档注明
        pdf = _MPL_PDF.replace(
            b"4 0 obj << /Type /Font /Subtype /Type3 /BaseFont /Helvetica >> endobj\n", b""
        )
        assert figure_checks.validate_output(_write(pdf, ".pdf"), min_dpi=300) == []


class TestPng:
    def test_300dpi_rgb_passes(self):
        assert figure_checks.validate_output(_write(_png(), ".png"), min_dpi=300) == []

    def test_600dpi_passes(self):
        assert figure_checks.validate_output(_write(_png(dpi=600), ".png"), min_dpi=300) == []

    def test_72dpi_rejected(self):
        problems = figure_checks.validate_output(_write(_png(dpi=72), ".png"), min_dpi=300)
        assert any("72" in p and "300" in p for p in problems)

    def test_missing_phys_rejected(self):
        problems = figure_checks.validate_output(_write(_png(dpi=None), ".png"), min_dpi=300)
        assert any("pHYs" in p for p in problems)

    def test_bad_signature_rejected(self):
        problems = figure_checks.validate_output(_write(b"JFIF....", ".png"), min_dpi=300)
        assert any("PNG" in p for p in problems)

    def test_bad_crc_rejected(self):
        data = bytearray(_png())
        data[-6] ^= 0xFF  # 破坏 IEND CRC
        problems = figure_checks.validate_output(_write(bytes(data), ".png"), min_dpi=300)
        assert any("CRC" in p for p in problems)

    def test_bad_color_type_rejected(self):
        problems = figure_checks.validate_output(
            _write(_png(color_type=9), ".png"), min_dpi=300
        )
        assert any("色彩" in p for p in problems)


class TestSvg:
    def test_wellformed_passes(self):
        assert figure_checks.validate_output(_write(b"<svg xmlns='http://www.w3.org/2000/svg'/>", ".svg"), min_dpi=300) == []

    def test_malformed_rejected(self):
        problems = figure_checks.validate_output(_write(b"<svg><unclosed>", ".svg"), min_dpi=300)
        assert any("XML" in p for p in problems)

    def test_dtd_rejected(self):
        svg = b"<?xml version='1.0'?><!DOCTYPE svg [<!ENTITY x 'y'>]><svg/>"
        problems = figure_checks.validate_output(_write(svg, ".svg"), min_dpi=300)
        assert any("DTD" in p for p in problems)


class TestAttachGate:
    def test_attach_rejects_low_dpi_png(self, tmp_path: Path):
        spec = _spec()
        out = tmp_path / "figure.png"
        out.write_bytes(_png(dpi=72))
        with pytest.raises(ValueError, match="quality gate"):
            build_artifact(spec, out, renderer="agent-script")

    def test_attach_accepts_300dpi_png(self, tmp_path: Path):
        spec = _spec()
        out = tmp_path / "figure.png"
        out.write_bytes(_png(dpi=300))
        artifact = build_artifact(spec, out, renderer="agent-script")
        assert len(artifact.output_sha256) == 64

    def test_attach_accepts_matplotlib_type3_pdf(self, tmp_path: Path):
        spec = _spec()
        out = tmp_path / "figure.pdf"
        out.write_bytes(_MPL_PDF)
        artifact = build_artifact(spec, out, renderer="agent-script")
        assert len(artifact.output_sha256) == 64


def _write(data: bytes, suffix: str) -> Path:
    path = Path("/tmp/opencode") / f"figcheck{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _spec():
    from bacmap.research.figures import FigureSource, FigureSpec

    return FigureSpec(
        figure_id="rs-check-fig1",
        kind="association_bar",
        title="t",
        caption="c",
        data={"n": 1},
        source=FigureSource(
            session_id="rs-check", run_id="run-1", stat_sha256="0" * 64, data_class=2
        ),
    )
