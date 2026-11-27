# 多用户与角色（accounts 模式）

> 状态：已实现（v1.10.49 账号；v1.10.54 个人模式）。单令牌部署仍保留；`personal`/`accounts` 为显式启用的模式。

bacmap 支持两种 Web 身份形态：

| 模式 | 配置 | 适用 |
|---|---|---|
| 单令牌（默认） | `BACMAP_WEB_AUTH=bearer` 或 `cookie` + `BACMAP_WEB_TOKEN` | 自动化、兼容旧部署 |
| 个人模式 | `BACMAP_WEB_AUTH=personal` + `bacmap personal init` | 个人工作站（单用户、全功能） |
| 本地账号 | `BACMAP_WEB_AUTH=accounts` | 单位内多人共用一台工作站 |

```bash
# 首个管理员必须在本机 shell 创建（Web 没有匿名注册入口）
# 本机 shell 能读数据库，视为服务器管理员，不受 Web RBAC 约束。
BACMAP_HOME=/srv/bacmap bacmap user create admin --role admin

export BACMAP_WEB_AUTH=accounts
BACMAP_HOME=/srv/bacmap bacmap start web
```

## 个人模式（hash-key 登录）

单用户工作站推荐个人模式：不需要用户名/密码，只有一枚访问密钥。

```bash
bacmap personal init            # 生成 bk_… 密钥并创建内置 owner（admin）
export BACMAP_WEB_AUTH=personal
bacmap start web                # 默认仍只绑回环地址

bacmap personal status          # 是否已初始化（不显示密钥）
bacmap personal init --rotate   # 轮换密钥，旧密钥立即失效
```

- 密钥只在 init/rotate 时显示一次；`$BACMAP_HOME/personal.json` 只存 scrypt
  派生值，文件权限 0600。
- 登录后为内置 `owner` 创建**服务端会话**；owner 固定 admin，拥有全部功能。
- 密钥轮换不会自动撤销已有会话；需要时执行登出或重启 Web。
- 个人模式仍可用 `bacmap user` 管理账号，但 Web 登录只接受访问密钥。

## 在 personal 与 accounts 之间切换

两种模式共用同一套表（迁移 4 的 `users` / `web_sessions` / `api_tokens`），
切换只改 `BACMAP_WEB_AUTH`，**不触发数据库迁移、不改业务表**，也不需要重建库。

- **accounts → personal**：现有账号、API 令牌与浏览器会话都保留。其他账号的
  旧会话在 12 小时到期前仍有效，个人 API 令牌也仍可用；若要严格单用户，
  先吊销令牌，并在停 Web 后清空 `web_sessions`（或使用独立的 `BACMAP_HOME`）。
- **personal → accounts**：`personal init` 创建的 `owner` 是 admin，但密码是
  随机值、不会显示；切换前请在本机创建或重置一个管理员：

  ```bash
  bacmap user create ops-admin --role admin
  # 或
  bacmap user passwd owner
  ```

- `personal.json` 只影响 personal 登录；切回 accounts 后保留也无妨（被忽略），
  删除它不会删除 `owner` 账号或已有会话。
- 业务数据、`owner_user_id`、导入提案的 `created_by` / `reviewed_by` 均原样
  保留；个人模式以 `owner`（admin）登录，因此能看到全部数据。

## 角色

| 权限 | admin | analyst | user |
|---|---|---|---|
| 查看全部样本/菌株/结果 | ✓ | ✓ | 仅自己 |
| 提交分析任务 | ✓ | ✓ | ✓ |
| 创建计划 / 确认计划 / 任务签批 | ✓ | ✓ | — |
| 登记元数据/化验/知识库 | ✓ | ✓ | — |
| 上传湿实验导入提案 | ✓ | ✓ | ✓（仅自己的，需审核） |
| 提交修改/删除/新建/关联提案 | ✓ | ✓ | ✓（仅自己可见数据，需审核） |
| 审核提案 | ✓ | ✓ | — |
| 删除样本/菌株、清理运行产物 | ✓ | ✓ | — |
| 研究、运行记录、GOM、系统概览 | ✓ | ✓ | — |
| 用户管理 | ✓ | — | — |

审核通过后，无主 specimen/isolate 会自动归属到提交人；已有 owner 不会被覆盖。
普通用户的“自己”指：任务/计划的 `submitted_by`，以及样本/菌株/结果索引上的
`owner_user_id`。无主的历史数据默认仅 analyst/admin 可见，管理员可用
`bacmap specimen assign-owner <specimen> <username>` 归属。

## 安全实现

- 密码：stdlib `scrypt`（N=16384, r=8, p=1），每用户随机盐；只存派生值。
- 浏览器会话：服务端 `web_sessions` 表存 SHA-256 哈希；cookie 只含随机令牌。
  禁用用户或改密码会立即撤销该用户的会话与 API 令牌；改角色在下一次请求按新角色生效。
- 登录限速：同一用户名 + 来源 IP 5 分钟内失败 10 次后返回 429。
- CSRF：沿用 ADR-14 的 `SameSite=Strict` + `Origin/Referer` + 双提交令牌。
- 审批/计划确认的操作者由服务端从登录主体认定；请求体里的 `approver`/`confirmer`
  仅用于旧单令牌模式兼容。
- 审计：登录/登出/用户创建/角色变更/停用写入领域事件（D2，不含密码/令牌）。
- API 令牌：`bacmap user token create <username>` 生成 `bm_...`，只显示一次；
  用于脚本/API 客户端（本机 CLI 直接读数据库，无需令牌），角色随账号。**MCP 仍是独立的服务令牌 + Profile，尚未按用户绑定**；
  只应交给可信操作员/本机智能体，普通用户的浏览器会话不要转给 Harness。

## AI 数据上限

组织模式可在配置中给所有 AI 调用加一条总上限：

```toml
[llm.data_policy]
cloud_max_data_class = "D1"   # 云端点位置上限（默认 D1，最多 D2）
ai_max_data_class = "D2"      # AI 总上限：D0–D4，默认 D4
```

实际生效级别 = **min(AI 总上限, 端点位置策略, 角色 max_data_class)**。
例如把 `ai_max_data_class` 设为 `D2` 后，本地端点也不会收到 D3/D4 载荷；
导入映射顾问会自动退回“仅列名与聚合统计”模式。云端点在任何情况下都只能
看到 schema/聚合（D1），除非显式开启 v1.10.51 的 debug 双开关。

## 数据存储

`data/bacmap.sqlite` 迁移 4：

```
users(user_id, username UNIQUE COLLATE NOCASE, password_hash, role,
      display_name, disabled, created_at, updated_at)
web_sessions(session_hash PK, user_id, created_at, expires_at,
             last_seen_at, client_ip, user_agent)
api_tokens(token_hash PK, user_id, name, created_at, last_used_at,
           expires_at, revoked_at)
specimens.owner_user_id / isolates.owner_user_id
```

禁止停用或降级最后一个可用管理员。

## CLI

```bash
bacmap user list
bacmap user create <username> --role admin|analyst|user
bacmap user set-role <username> admin
bacmap user disable <username> [--enable]
bacmap user passwd <username>
bacmap user token create <username> --name cli-laptop
bacmap user token list <username>
bacmap user token revoke <username> <token-prefix>

bacmap specimen assign-owner <specimen> <username>
bacmap specimen assign-owner <specimen> --clear
```

## 结果索引与检索

10 万级列表不再逐请求扫描 `results/*/report/*_summary.json`，也不再全量拉到浏览器：

- `strain_genotype_index` 增加 specimen/isolate、基因组大小、contigs、GC、
  CARD/VFDB/质粒计数、owner、分析时间；
- analyze 的 ingest 步骤直接写索引；
- 历史结果执行一次 `bacmap results reindex --backfill-metadata`（已有索引行只补新列，保留 GOM 关联）；
- `/api/v1/samples`、`/api/v1/species`、`/api/v1/specimens`、`/api/v1/isolates`
  提供 `q`/`species`/`st`/`serotype`/`amr_gene` 等服务端过滤与分页；
- 控制台新增“物种”页与“用户管理”页，测序数据列表改为服务端分页。

SQLite 在 10 万级（合成 10 万样本 + 12 万菌株 + 10 万索引，约 38 MB）的实测：
计数 <0.1 ms、深分页 <1 ms、物种过滤 + 分页约 3 ms、全表 `LIKE` 约 20 ms。
**不引入 DuckDB 作为主库**；如未来出现千万级或大量 Parquet/宽表即席分析需求，
再评估只读分析侧车。
