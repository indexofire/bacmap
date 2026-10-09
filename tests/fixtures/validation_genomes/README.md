# 物种鉴定验证基因组集

NCBI Pathogen Detection 追踪病原的 RefSeq 参考/代表基因组（完整/染色体级），
作为物种鉴定方法的验证真值集——每个基因组的 NCBI 分类学即期望答案。

- 生成：`uv run python scripts/download_validation_genomes.py`（幂等，可重复执行）
- 清单对账：`--verify-list` 校验配置病原与 NCBI 实时追踪组一致
- 真值表：`manifest.tsv`（入库；列：accession / organism / expected / role / fna 路径）
- 基因组本体 `genomes/*.fna` 不入 git（体积），由脚本按需下载
- role 语义：`target`=四种支持病原（必须被正确鉴定）；`negative`=近缘
  阴性对照（正确答案 = 不属于四种支持病原）
