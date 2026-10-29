# CLI 参考

`bacmap` 可执行文件有两类顶层入口：

- **接口/模式**，接管终端或绑定端口：`mcp`、`web`、`tui`、`console`；
- **命令**，执行一次操作后退出：`overview`、`task`、`plan`、`record`、`run`、
  `gom`、`isolate`、`sample`、`search`、`doctor`、`backup`、`restore`、`results`、`events`。

`--version` 打印程序版本。

| 常用参数 | 含义 |
|---|---|
| `--home DIR` | 本次命令覆盖 `BACMAP_HOME` |
| `--json` | 输出单个 JSON 文档（查询命令） |
| `--by ACTOR` | 任务/记录提交的审计主体（默认 `cli`） |
| `--limit N` | 限制列表条数 |
| `--type TYPE` | 过滤 GOM 对象（`sample`、`analysis`、`report`、`task`…） |

## `bacmap mcp`

```text
bacmap mcp [--home H] [--read-only] [--profile {cloud,local-trusted}]
           [--transport {stdio,http}] [--host H] [--port 8765]
           [--uds PATH] [--token-env ENV]
```

- 默认使用 stdio；HTTP 为 Streamable HTTP，且要求 bearer token。
- `--read-only` 移除任务/计划的写工具。
- `local-trusted` 要求 `[mcp] allow_local_trusted = true`。

```bash
bacmap mcp
bacmap mcp --read-only
bacmap mcp --profile local-trusted
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
bacmap mcp --transport http --uds /run/bacmap-mcp.sock
```

## `bacmap web`

```text
bacmap web [--home H] [--host 127.0.0.1] [--port 8800] [--token-env BACMAP_WEB_TOKEN]
```

默认绑定回环地址。非回环主机且无 token 时拒绝启动。

```bash
bacmap web
BACMAP_WEB_TOKEN=secret bacmap web --host 0.0.0.0 --port 8800
BACMAP_WEB_AUTH=cookie BACMAP_WEB_TOKEN=secret bacmap web
```

## `bacmap tui` / `bacmap console`

```bash
bacmap tui
bacmap console
```

TUI 按键与斜杠命令见[界面](../guide/interfaces.zh.md)。`console` 是
带编号的菜单。

## `bacmap overview`

```bash
bacmap overview
bacmap overview --json
```

只读摘要：版本、路径、数据策略、端点、沙箱、任务计数。

## `bacmap task`

```text
bacmap task list|ls [--limit N] [--home H] [--json]
bacmap task show <task_id> [--json]
bacmap task submit --type {analyze,curate}
                    (--samples IDS | --fasta-dir DIR | --fastq-dir DIR)
                    [--species CODE] [--scope JSON] [--by ACTOR] [--json]
bacmap task approve <task_id> --approver NAME --decision {approve,reject}
                    --signature SIG [--comment TEXT]
bacmap task cancel <task_id>
```

示例：

```bash
bacmap task list
bacmap task show 3f9c2a1b
bacmap task submit --type analyze --samples SAM-001,SAM-002
bacmap task submit --type analyze --fasta-dir /data/genomes --species VPA
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task approve 3f9c2a1b --approver "Jane" --decision approve --signature "jd-2026-10-30"
bacmap task cancel 3f9c2a1b
```

只有 `analyze`/`curate` 可以从 CLI 提交。`mine`/`write` 仅支持计划；`record` 有
自己的命令。

## `bacmap plan`

```text
bacmap plan list|ls [--limit N]
bacmap plan show <plan_id> [--version N]
bacmap plan confirm <plan_id> [--version N] [--hash PREFIX]
bacmap plan reject <plan_id> --version N --reason TEXT
```

`--hash` 接受至少 12 个十六进制字符的唯一前缀。未提供时，`confirm` 会打印计划
并交互式询问。`reject` 只对未确认的计划有效。

```bash
bacmap plan show 9a3f2c1b7d4e4f60
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
bacmap plan reject 9a3f2c1b7d4e4f60 --version 1 --reason "wrong sample"
```

## `bacmap record`

```text
bacmap record metadata --strain-id ID [--sample-id ID] [--field k=v ...] [--by ACTOR]
bacmap record lab --strain-id ID --category CAT --test-name NAME --result VALUE
                  [--unit U] [--method M] [--interpretation I] [--standard S]
                  [--tested-date D] [--tested-by WHO] [--lab LAB] [--notes TEXT]
bacmap record knowledge-import --title TITLE [--authors A] [--year Y] [--source S]
                               [--identifier ID] [--content TEXT]
                               [--entry-kind {literature,method,report}]
bacmap record knowledge-approve <entry_id>
```

示例见[数据与身份](../guide/data.zh.md#5-记录元数据化验结果与知识库)。

## `bacmap run`

```text
bacmap run list|ls [--limit N] [--json]
bacmap run show <run_id> [--json]
bacmap run compare <run_a> <run_b> [--json]
```

```bash
bacmap run compare 4f2c... 9a31...
```

## `bacmap gom`

```text
bacmap gom list|ls [--type TYPE] [--limit N] [--json]
bacmap gom show <object_id> [--version N] [--json]
```

对象类型：`sample`、`analysis`、`report`、`workflow`、`plugin`、`knowledge`、`task`。

## `bacmap isolate`

```text
bacmap isolate list|ls [--json]
bacmap isolate show <isolate_id> [--json]
```

## `bacmap sample`

```text
bacmap sample ls [--json]
bacmap sample show <sample_id> [--json]
```

`sample` ID 即 dataset ID；输出取自最新的摘要。

## `bacmap search`

```text
bacmap search [--query TEXT] [--serotype TEXT] [--st ST] [--gene GENE]
              [--home H] [--json]
```

```bash
bacmap search --query Salmonella
bacmap search --serotype Typhimurium --st 19 --gene blaCTX-M-15
```

## `bacmap doctor`

```text
bacmap doctor [--json]
```

检查 home、数据库、沙箱、LLM、磁盘与工具。仅 `fail` 时退出码为 `1`。

## `bacmap backup` / `bacmap restore`

```text
bacmap backup --out FILE [--with-results]
bacmap restore --from FILE [--home DIR] [--force]
```

见[运维](../operations/index.zh.md)。

## `bacmap results`

```text
bacmap results migrate [--dry-run]
```

把遗留的扁平结果目录移入 `runs/legacy-<name>/`，并用链接替换它们。

## `bacmap events`

```text
bacmap events prune --days N [--json]
```

`--days 0` 删除所有事件。门审批与运行记录不受影响。

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 操作失败，或 `doctor` 发现 `fail` |
| 2 | 参数解析错误 |
