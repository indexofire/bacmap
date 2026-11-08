"""图片产物质量门（P2：PDF/PNG 校验）。

``bacmap research figure attach`` 对非 SVG 输出做确定性校验（纯标准库，不引入
PDF/PNG 解析依赖）：

- **PDF**：文件头、页数 ≥1、字体嵌入——声明了字体（``/BaseFont``）却既无
  ``/FontFile*``（Type0/TrueType/Type1 的嵌入字体程序）也无 ``/Subtype /Type3``
  （字形程序内联，matplotlib 默认即 Type3）时判"未嵌入"。matplotlib 不使用
  ObjStm，token 可直接扫描；完全扫描不到字体 token 的 PDF（纯图像图）视为无文本，
  放行（已知放行面，见模块测试）。
- **PNG**：签名与 chunk 结构（含 CRC）、IHDR 合法（尺寸>0、色彩类型 ∈
  灰度/RGB/索引/灰度A/RGBA、位深 ≤16）、pHYs 密度 ≥ 契约 dpi；缺 pHYs 视为
  无法验证（契约要求栅格 ≥300 dpi，写不出密度即不合格）。
- **SVG**：XML 良构（ElementTree 解析）。

规则贴合实测：bacmap-figures:py312（matplotlib 3.10，PDF fonttype=3 默认）产出
的 PDF 必须通过；72 dpi 或未嵌字体的产物必须被拒且给出可操作原因。
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path

_PDF_FONT_FILE = re.compile(rb"/FontFile[123]?\b")
_PDF_BASE_FONT = re.compile(rb"/BaseFont\b")
_PDF_TYPE3 = re.compile(rb"/Subtype\s*/Type3\b")
_PDF_PAGE = re.compile(rb"/Type\s*/Page\b")

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_COLOR_TYPES = frozenset({0, 2, 3, 4, 6})


def _pdf_problems(data: bytes) -> list[str]:
    problems: list[str] = []
    if not data.startswith(b"%PDF-"):
        return ["PDF 缺少 %PDF- 文件头（不是有效的 PDF）"]
    n_pages = len(_PDF_PAGE.findall(data))  # \b 已排除 /Type /Pages
    if n_pages < 1:
        problems.append("PDF 没有可数的页面对象（/Type /Page）")
    n_fonts = len(_PDF_BASE_FONT.findall(data))
    if n_fonts and not _PDF_FONT_FILE.search(data) and not _PDF_TYPE3.search(data):
        problems.append(
            f"PDF 声明了 {n_fonts} 个字体（/BaseFont）但没有任何嵌入字体程序"
            "（/FontFile* 或 Type3 字形内联）——期刊要求字体嵌入；"
            "matplotlib 请用默认 fonttype 或 `pdf.fonttype: 42` 后重新导出"
        )
    return problems


def _iter_png_chunks(data: bytes):
    offset = len(_PNG_SIGNATURE)
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        crc = data[offset + 8 + length : offset + 12 + length]
        if len(body) < length or len(crc) < 4:
            return  # 截断：由 IHDR/pHYs 检查兜底报错
        yield chunk, body, crc
        if chunk == b"IEND":
            return
        offset += 12 + length


def _png_problems(data: bytes, min_dpi: int) -> list[str]:
    problems: list[str] = []
    if not data.startswith(_PNG_SIGNATURE):
        return ["PNG 签名无效（不是 PNG 文件）"]
    ihdr: bytes | None = None
    phys: bytes | None = None
    for chunk, body, crc in _iter_png_chunks(data):
        if zlib.crc32(chunk + body) & 0xFFFFFFFF != int.from_bytes(crc, "big"):
            problems.append(f"PNG chunk {chunk.decode('latin-1', '?')} CRC 校验失败")
            return problems
        if chunk == b"IHDR" and ihdr is None:
            ihdr = body
        if chunk == b"pHYs" and phys is None:
            phys = body
    if ihdr is None or len(ihdr) < 13:
        problems.append("PNG 缺少有效的 IHDR chunk")
        return problems
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth = ihdr[8]
    color_type = ihdr[9]
    if width < 1 or height < 1:
        problems.append(f"PNG 尺寸非法（{width}×{height}）")
    if bit_depth > 16:
        problems.append(f"PNG 位深非法（{bit_depth}）")
    if color_type not in _PNG_COLOR_TYPES:
        problems.append(
            f"PNG 色彩类型非法（{color_type}；合法值 0/2/3/4/6 = 灰度/RGB/索引/灰度A/RGBA）"
        )
    if phys is not None and len(phys) >= 9:
        x_ppm = int.from_bytes(phys[0:4], "big")
        unit = phys[8]
        if unit == 1 and x_ppm > 0:
            # ppm 整数比较：matplotlib 等工具写 300 dpi 为 round(300/0.0254)=11811
            # ppm（=299.999… dpi）——按生态约定对齐，避免浮点/取整误差误拒
            min_ppm = round(min_dpi / 0.0254)
            if x_ppm < min_ppm:
                dpi = x_ppm * 0.0254
                problems.append(
                    f"PNG 分辨率 {dpi:.0f} dpi 低于契约要求的 {min_dpi} dpi"
                )
    else:
        problems.append(
            "PNG 没有 pHYs 密度 chunk——栅格分辨率无法验证；"
            "请以 >= 契约 dpi 重新导出（matplotlib savefig(dpi=...) 会写入 pHYs）"
        )
    return problems


def _svg_problems(data: bytes) -> list[str]:
    import xml.etree.ElementTree as ET

    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        # 渲染器产出的 SVG 不含 DTD/实体；出现即拒绝，规避 XML 实体扩展攻击面
        return ["SVG 含 DTD/ENTITY 声明（渲染产物不应有，拒绝解析）"]
    if len(data) > 10 * 1024 * 1024:
        return ["SVG 超过 10 MB 上限"]
    try:
        ET.fromstring(data)  # noqa: S314 — DTD/实体已前置排除，仅判良构性
    except ET.ParseError as exc:
        return [f"SVG 不是良构的 XML：{exc}"]
    return []


def validate_output(path: str | Path, *, min_dpi: int) -> list[str]:
    """校验一个图片产物；返回问题清单（空列表 = 通过）。

    纯确定性检查：只看字节事实（嵌入字体程序、pHYs 密度、XML 良构），
    不猜测渲染效果；未知布局（如纯图像 PDF）放行并在此注明。
    """
    data = Path(path).read_bytes()
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return _pdf_problems(data)
    if suffix == ".png":
        return _png_problems(data, min_dpi)
    if suffix == ".svg":
        return _svg_problems(data)
    return []  # 其它格式只做存在性检查（build_artifact 已限格式白名单）
