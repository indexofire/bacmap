"""gmlst MST JSON → Newick（报告渲染用，纯格式转换）。

输入：`gmlst visual mst --format json` 的 node/edge 载荷
（MST 边集无环，可确定性转为有根 Newick：根取 nodes[0]，枝长 = edge weight）。
输出：单行 Newick（含末尾分号），供 phylotree.js 渲染。

用法: mst_to_newick.py <mst_payload.json> [out.treefile]（缺省写 stdout）
"""

from __future__ import annotations

import argparse
import json
import re
import sys


def _sanitize(label: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.\-]", "_", label)
    return s or "node"


def _unwrap(payload: dict) -> dict:
    """解封装 `gmlst visual * --format json` 的 {schema_version, data} 外壳。

    gmlst 0.5.5 把真正的 node/edge 载荷放在顶层 ``data`` 键下；直接读顶层
    ``nodes`` 会 KeyError，导致 cgMLST cohort 建树整条规则失败。
    """
    if not isinstance(payload, dict):
        return payload
    if "nodes" not in payload and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def to_newick(payload: dict) -> str:
    payload = _unwrap(payload)
    nodes = payload["nodes"]
    edges = payload.get("edges", [])
    adj: dict[int, list[tuple[int, float]]] = {n["id"]: [] for n in nodes}
    for e in edges:
        w = e.get("weight", 0)
        adj[e["source"]].append((e["target"], w))
        adj[e["target"]].append((e["source"], w))
    label = {n["id"]: _sanitize(str(n.get("label", n["id"]))) for n in nodes}
    if not nodes:
        return ";"
    root = nodes[0]["id"]

    def build(node: int, parent: int | None) -> str:
        children = [(nb, w) for nb, w in adj[node] if nb != parent]
        if not children:
            return label[node]
        inner = ",".join(f"{build(nb, node)}:{w}" for nb, w in sorted(children))
        return f"({inner}){label[node]}"

    return build(root, None) + ";"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("payload", help="gmlst visual mst --format json 输出文件")
    ap.add_argument("out", nargs="?", help="输出 treefile（缺省 stdout）")
    args = ap.parse_args()

    payload = json.loads(open(args.payload, encoding="utf-8").read())
    newick = to_newick(payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(newick + "\n")
    else:
        print(newick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
