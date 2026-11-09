# Tutorial: running bacmap end-to-end with a local Strata + DeepSeek backend

A hands-on, hardware-specific walkthrough (Chinese, 335 lines) for driving bacmap's
full loop — batch genome analysis (`analyze`), data mining (`mine`), and paper
writing (`write`) — on a personal Linux workstation, using
[Strata](https://strata.ai) with a quantised DeepSeek model as the local LLM
backend (example hardware: RTX 5060 Ti 16 GB + 64 GB RAM, ≥300 GB disk).

The full text is maintained in Chinese:
[bacmap-strata-deepseek-tutorial.zh.md](bacmap-strata-deepseek-tutorial.zh.md)
（[中文版](bacmap-strata-deepseek-tutorial.zh.md)：在个人电脑上用 Strata 跑
DeepSeek 量化模型，为 bacmap 提供 LLM 后端——NCBI 沙门菌 ~100 株基因组
「分析 → 数据挖掘 → 论文写作」全流程教程）。

Key stages covered: Strata install & model download → bacmap pixi environment &
config → NCBI datasets download of ~100 *Salmonella* genomes → batch `analyze`
plans → `mine` sandbox mining with human sign-off → research sessions & submission
packages → `write` task with citation gates.
