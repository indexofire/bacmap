# 安全与数据分级

bacmap 假设工作站可信，而*模型*不可信。设计上把数据留在本机、约束外部智能体能看到的范围，
并让人类对具有后果的操作负责。

## 1. 数据分级（ADR-16）

| 分级 | 示例 | Cloud 端点 | Cloud MCP Profile |
|---|---|---|---|
| **D0** | 公开参考元数据、诊断信息 | 允许 | 允许 |
| **D1** | 去标识化的汇总统计 | 允许（默认上限） | 允许 |
| **D2** | 单株分型结果、样本 ID | 默认阻止；管理员可将上限提高到 D2 | 仅当上限为 D2 时允许 |
| **D3** | 序列、比对、组装 | **永不** | 需要 `local-trusted` |
| **D4** | 个人/流行病学标识、元数据、实验室结果 | **永不** | 需要 `local-trusted` |

上限在两处强制执行：

1. **LLM 网关** —— 发送前，`LlmGateway` 将载荷分级与 `[llm.data_policy].cloud_max_data_class`
   比较；D3/D4 不能配置到 D2 以上。
2. **MCP Profile** —— `cloud` 服务器甚至不会注册输出级别超过上限的工具；调用时还会再次检查。

```toml
[llm.data_policy]
cloud_max_data_class = "D1"      # "D1" or "D2" only
```

```
DataClassViolationError: payload D4 exceeds cloud limit D1
```

## 2. MCP Profile

```bash
bacmap mcp                          # cloud (default)
bacmap mcp --profile local-trusted  # requires [mcp] allow_local_trusted = true
```

| | `cloud` | `local-trusted` |
|---|---|---|
| 工具输出 | ≤ cloud 上限 | 最高到 D4 |
| 任务消息 | 不予返回 | 完整 |
| 任务结果 | 门计数 | 逐样本结论 |
| Record 工具 | 不注册 | `bacmap_record_data` |
| 目标模型 | cloud API | 本地/局域网 |

Profile 在启动时固定；客户端无法在会话中途提权。若两者都需要，请运行独立实例（不同端口与令牌）。

## 3. 确认不等于工具审批

MCP elicitation 与 harness 工具审批由客户端/模型作答。因此 bacmap 只接受来自以下途径的确认：

- Web 计划页面 / 签批卡片（会话 + CSRF）；
- CLI `plan confirm` / `task approve`；
- 本机系统弹窗（`bacmap_confirm_plan_locally`，stdio，人工点击）；
- 可选的 `[plans.auto_confirm]` 策略，适用于针对已登记样本的低风险 analyze 计划。

模型可以提议、修订与轮询，但不能确认或签字。

## 4. 沙箱

`mine` 脚本在容器（Apptainer 或 Podman）中运行，具有：

- 无网络（`--network none`）；
- 可写工作区；
- 对结果、GOM 与已登记数据集的只读挂载；
- 主机文件系统不挂载（除声明的输入外）。

除非 `BACMAP_ALLOW_UNSANDBOXED=1`（仅开发用），否则拒绝直通。有意不支持 Docker。
安全边界是容器本身，而不是命令白名单。

## 5. Web 与 MCP 身份验证

### Web

- 默认绑定回环地址；非回环主机若无令牌则拒绝启动。
- `bearer` 模式：`Authorization: Bearer <BACMAP_WEB_TOKEN>`；浏览器无法设置该头，
  因此请使用 SSH 隧道或 cookie 模式。
- `cookie` 模式：`/login` 签发带签名的 `HttpOnly`、`SameSite=Strict` 会话 cookie；
  每个改变状态的 POST 都需要 CSRF 令牌与同源 Origin/Referer。
- `BACMAP_WEB_COOKIE_SECURE=1` 在 TLS 之后加上 `Secure`。
- 安全响应头包括严格 CSP、nosniff、frame-deny、referrer-policy 与 COOP。
- JSON API 是可信操作员界面；绝不要把它令牌交给 harness。

### MCP HTTP

- Bearer 令牌为必需（`BACMAP_MCP_TOKEN` 或 `--token-env`）。
- 绑定到回环地址或 unix socket。
- 通过 allowed hosts 做 DNS 重绑定防护；MCP SDK 传输层安全。
- stdio 会话以操作系统用户作为操作者（`mcp-stdio:<profile>:<user>`）；HTTP 使用
  `mcp-http:<profile>`。

## 6. 脱敏与最小权限

- `cloud` 下的 `bacmap_task_status` 不返回原始任务消息（其中可能包含样本 ID、路径或其他
  D2 数据），而是返回脱敏后的失败块：`{kind, suggested_fix, recovery_commands}`。
- `bacmap_task_result` 在 cloud 下返回门计数，而不是逐样本结论。
- 工具处理器在意外失败时只返回异常**类型**，不返回消息/路径。
- 计划的读取/修订限于创建该计划的客户端。
- 任务取消限于同一客户端提交的任务（直接提交或经其自己的计划提交）。

## 7. 威胁模型

| 威胁 | 控制措施 |
|---|---|
| Cloud 模型看到序列/D4 | 数据分级在网关 + MCP Profile 中强制执行 |
| 提示注入让智能体确认或签字 | 确认只在可信界面进行；模型没有确认工具 |
| 智能体在你确认前调换计划 | 计划归属 + 版本/哈希绑定 + 输入指纹 |
| 伪造请求写入元数据 | record 任务 + 任务层；MCP 仅在 local-trusted 下可用 D4 |
| 恶意 mine 脚本逃逸 | 无网络容器、只读挂载、不挂载主机 |
| Web 令牌泄露给 harness | Web/MCP 令牌分离；文档与启动提示；操作员界面不面向智能体 |
| 会话窃取 / CSRF | 带签名的 HttpOnly cookie、SameSite=Strict、CSRF 令牌 + 来源检查 |
| 经样本 ID 的路径穿越 | `^[A-Za-z0-9._-]+$`，拒绝 `.`/`..`，在每个接口处校验 |
| 数据库篡改 | 只追加的运行记录/清单；GOM 不可变；清单中记录哈希 |

## 8. 外部智能体部署检查清单

```bash
# dedicated account, private home
sudo useradd -r -m -d /srv/bacmap bacmap
sudo chmod 700 /srv/bacmap

# run services as that account, loopback only
BACMAP_HOME=/srv/bacmap bacmap web --host 127.0.0.1 --port 8800
BACMAP_HOME=/srv/bacmap BACMAP_MCP_TOKEN=... \
  bacmap mcp --transport http --host 127.0.0.1 --port 8765

# the harness runs as your normal user and gets only the MCP URL/token
```

MCP Profile 无法阻止 harness 自己的 shell 读取文件。真正阻止这一点的是操作系统账户边界；
bacmap 无法控制被复制进 harness 工作区的文件，也无法控制模型提供方如何处理它收到的内容。
