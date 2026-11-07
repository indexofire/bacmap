# CLI 参考

`bacmap` 可执行文件有两类顶层入口：

- **`start`**，启动一个接管终端或绑定端口的长驻界面：
  `bacmap start mcp|web|tui|console`；各界面保留自己的参数；
- **命令**，执行一次操作后退出：`overview`、`task`、`plan`、`record`、`run`、
  `gom`、`isolate`、`sample`、`search`、`selection`、`doctor`、`backup`、`restore`、
  `results`、`events`。

`--version` 打印程序版本。

| 常用参数 | 含义 |
|---|---|
| `--home DIR` | 本次命令覆盖 `BACMAP_HOME` |
| `--json` | 输出单个 JSON 文档（查询命令） |
| `--by ACTOR` | 任务/记录提交的审计主体（默认 `cli`） |
| `--limit N` | 限制列表条数 |
| `--type TYPE` | 过滤 GOM 对象（`sample`、`analysis`、`report`、`task`…） |

## 显示语言

CLI 帮助与提示文案跟随显示语言：环境变量 `BACMAP_LANG`（`en` | `zh`）优先于
`config.toml` 的 `[ui] language`；内置默认 `en`。见[配置参考](configuration.zh.md)。

## `bacmap start mcp`

```text
bacmap start mcp [--home H] [--read-only] [--profile {cloud,local-trusted}]
                 [--transport {stdio,http}] [--host H] [--port 8765]
                 [--uds PATH] [--token-env ENV]
```

- 默认使用 stdio；HTTP 为 Streamable HTTP，且要求 bearer token。
- `--read-only` 移除任务/计划的写工具。
- `local-trusted` 要求 `[mcp] allow_local_trusted = true`。

```bash
bacmap start mcp
bacmap start mcp --read-only
bacmap start mcp --profile local-trusted
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
bacmap start mcp --transport http --uds /run/bacmap-mcp.sock
```

## `bacmap start web`

```text
bacmap start web [--home H] [--host 127.0.0.1] [--port 8800] [--token-env BACMAP_WEB_TOKEN]
```

默认绑定回环地址。非回环主机且无 token 时拒绝启动。

```bash
bacmap start web
BACMAP_WEB_TOKEN=secret bacmap start web --host 0.0.0.0 --port 8800
BACMAP_WEB_AUTH=cookie BACMAP_WEB_TOKEN=secret bacmap start web
```

## `bacmap start tui` / `bacmap start console`

```bash
bacmap start tui
bacmap start console
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

## `bacmap research`

```text
bacmap research list|ls [--limit N] [--json]
bacmap research show <session_id> [--json]
bacmap research create --run-id ID --gene NAME --test-name NAME
                       [--profile open-test|research|publication]
                       [--study ID] [--cohort ID] [--plan ID]
                       [--by ACTOR] [--json]
bacmap research artifact <session_id> {figure|report|manuscript|figure_spec|figure_custom|figure_manifest}
bacmap research figure recipes [--executable-only] [--json]
bacmap research figure runtimes [--json]
bacmap research figure spec <session_id> [--json]
bacmap research figure render <session_id> [--recipe ID] [--by ACTOR] [--json]
bacmap research figure template [--output FILE] [--json]
bacmap research figure draft <session_id> --path FILE [--note TEXT]
bacmap research figure drafts <session_id>
bacmap research figure feedback <draft_id> --text TEXT
bacmap research figure finalize <draft_id> [--recipe ID] [--code FILE]
bacmap research figure reject <draft_id> [--note TEXT]
bacmap research figure attach <session_id> --path FILE [--code FILE] [--spec FILE]
                              [--renderer agent-script|bacmap-deterministic] [--recipe ID]

bacmap research phylo profile --alignment FILE [--dates FILE] [--partitions A,B]
bacmap research phylo plan --profile FILE [--goal ml|bayesian]
bacmap research phylo validate --profile FILE --plan FILE
bacmap research phylo xml --profile FILE --plan FILE --alignment FILE -o XML [--validate]
bacmap research phylo iqtree --plan FILE --alignment FILE [--prefix P]

bacmap research stats logistic --data FILE --outcome COL --predictors A,B
bacmap research stats power --p1 P --p2 P [--alpha A] [--power P] [--ratio R]
                             [--baseline P --odds OR] [--n1 N --n2 N]
                             [--session ID] [--home DIR] [--json]
bacmap research stats validate --derivation ID --validation ID [--alpha A] [--json]
bacmap research advstats render --method M --data FILE [--outcome C] [--treatment C]
                                [--predictors A,B] [--confounders A,B] [--group C]
                                [--time C] [--event C] [--output FILE]
bacmap research package <study_id> --out DIR

bacmap research request create --question TEXT [--run-id ID]... [--gene NAME]
                              [--test-name NAME] [--analysis association|logistic|phylo|figure]
bacmap research request list [--status proposed|approved|rejected]
bacmap research request show <request_id>
bacmap research request approve <request_id> [--members JSON] [--spec JSON]
bacmap research request reject <request_id> [--note TEXT]

bacmap research evidence <identifier>

bacmap research study create --question TEXT [--pathogen SCOPE] [--data-class 0-4]
bacmap research study ls|list [--limit N]
bacmap research study show <study_id>

bacmap research cohort create --study ID --members FILE [--name NAME] [--rules JSON]
bacmap research cohort preview --study ID --members FILE
bacmap research cohort freeze <cohort_id>
bacmap research cohort ls|list [--study ID]

bacmap research plan create --study ID --cohort ID --spec JSON|FILE
bacmap research plan freeze <plan_id>
bacmap research plan run <plan_id>

bacmap research claim create --study ID --type association --wording TEXT --level E2
bacmap research claim review <claim_id> --decision support|challenge|reject|approve
bacmap research claim ls|list [--study ID]

bacmap research experiment record --plan ID --status success|failed|negative|deviated
                                   [--run-id ID ...] [--outcome JSON] [--deviation TEXT]
bacmap research experiment ls|list [--study ID] [--plan ID]
bacmap research publication <study_id> [--json]

bacmap research benchmark {amr|bvbrc|osf|verify-bvbrc|verify-osf} [--data DIR]

bacmap research outbreak --events FILE [--min-count N]
bacmap research sensitivity --table a,b,c,d [--strata JSON|FILE]
bacmap research explore --study ID --cases FILE
                        [--max-tests N] [--max-candidates N] [--min-n N] [--max-q Q]
```

P1 从已有 run 生成确定性 AMR 关联草案。`open-test` 产物为 `TEST/UNVERIFIED`；
`research`/`publication` 为 `REVIEW REQUIRED`。

P2 增加完整对象生命周期：Study → 冻结 Cohort → 冻结 AnalysisPlan → Experiment 账本 →
Claim 审核 → `publication-readiness`（G0–G3）。`--members`、`--spec`、`--rules`、
`--evidence`、`--outcome` 接受内联 JSON 或 JSON 文件；`cohort create` 也接受完整的
`cohort_members.json`（读取其中的 `members` 数组）。

## `bacmap selection`

```text
bacmap selection path [--selection PATH] [--home H] [--json]
bacmap selection options [--tool gspec|gmlst|all] [--species CODE] [--datadir DIR]
                         [--selection PATH] [--downloaded-only] [--home H] [--json]
bacmap selection show [--species CODE] [--selection PATH] [--diff] [--home H] [--json]
bacmap selection validate [PATH] [--datadir DIR] [--downloaded-only] [--home H] [--json]
bacmap selection select [--tool gspec|gmlst|all] [--species CODE] [--databases A,B]
                        [--modes mlst,cgmlst] [--schemes mlst=NAME,cgmlst=NAME]
                        [--from-json FILE] [--from-yaml FILE] [--selection PATH]
                        [--mode extend|replace] [--yes] [--dry-run] [--home H] [--json]
```

查看与编辑 `tool_selection.yaml` 覆盖层（见
[配置 §13](configuration.zh.md#13-tool_selectionyaml)）：

- `path` 显示实际解析到的覆盖层路径（显式 → 环境变量 → home；不会创建文件）；
- `options` 合并实时 catalog（gspec `db list --json`、gmlst `scheme list -f json`）与当前
  选择，输出一个 JSON 文档——与只读 MCP 工具 `bio_tool_selection_options` 返回的文档相同；
- `show` 显示生效的物种映射；`--diff` 与 registry 默认值比较；
- `validate` 拒绝未知库/scheme、mode/scheme 类型不匹配、未下载 scheme、cgmlst/wgmlst
  冲突、对读段使用 cluster 库以及 license 违规；校验失败退出码 `1`；
- `select` 通过交互、命令行参数或 `--from-json`/`--from-yaml` 构造选择，校验后原子写入
  （`.bak` 保留上一份文档）；`--dry-run` 只打印不写盘。

`bacmap db ...` 是固定 `--tool gspec` 的同一套解析器，保留为 gspec-only 别名：
`bacmap db path|options|show|validate|select`。

```bash
bacmap selection options --tool all --json | jq '.species[0]'
bacmap selection show --diff
bacmap selection select --tool gspec --species VPA --databases vpa_ok,vpa_pai
```

## `bacmap agent`

```text
bacmap agent list [--json]
bacmap agent export --harness NAME [--format instructions|mcp-config|skill] [--role ROLE] [--json]
bacmap agent install --harness NAME [--scope project|user] [--target DIR]
                      [--with-skills] [--inline-skills] [--inline-role ROLE]
                      [--force] [--json]
bacmap agent doctor [--target DIR] [--json]
```

为用户自选的 agent harness 生成薄适配文件。事实来源仍在 bacmap（MCP instructions、
角色 prompts 与 `skill://` resources）；安装出的文件是指导，不是权限。

- `list` 列出支持的 harness 及其配置格式；
- `export` 打印指导文件、MCP 配置片段或某个角色的 `SKILL.md`；
- `install` 写入 harness 指导文件与 `.bacmap-agent.json`；幂等，且除非 `--force`
  否则拒绝覆盖用户文件；`--with-skills` 同时写 `.bacmap/skills/<role>/SKILL.md`；
- `doctor` 校验文件 hash，并在内容或 bacmap 版本不一致时告警。

## `bacmap config`

```text
bacmap config init [--user|--project] [--force]
bacmap config path [--json]
```

- 默认写入 `$BACMAP_HOME/config.toml`；
- `--user` 写入 `$XDG_CONFIG_HOME/bacmap/config.toml`（默认 `~/.config/bacmap/config.toml`）；
- `--project` 写入当前目录 `config.toml`；源码检出中该文件已被 gitignore，使用时设置
  `BACMAP_CONFIG="$PWD/config.toml"`；
- 模板来自仓库根目录 `config.example.toml`；
- `path` 显示当前实际读取的配置文件。

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
