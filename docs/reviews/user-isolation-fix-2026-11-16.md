# 用户隔离漏洞修复验收

日期：2026-11-16，针对同日深入审计确认的 F1—F5 和 R1。

## 实现

| 问题 | 统一实现 |
| --- | --- |
| F1：工具越过账号文件边界、继承服务权限 | 服务入口强制使用 UserWorkspaceManager。每个账号独立非 root 容器、数据卷、internal + isolated 网络；Read/Write/Bash/Glob/Grep、MCP、技能及记忆均通过该容器。工具不继承 API 源码、服务环境密钥、Docker socket 或 Redis 网络。无本地执行回退。 |
| F2：HTML/SVG 文件同源脚本读取令牌 | 工作区与知识库原文统一安全响应头；主动内容强制附件，所有用户文件附加 sandbox CSP、nosniff 和 no-store。 |
| F3：聊天/确认在授权前操作目标会话 | 统一 require_session，在投影读取、任务登记、入队或持锁前验证 user/Agent/session。确认转发再次校验 worker 归属及团队关系。 |
| F4：越权删除仍取消或清空目标运行 | 删除前完成完整会话归属检查，未授权直接退出，不广播取消、不清投影、不改事件。 |
| F5：校验后替换目录或建立硬链接 | 文件下载和预览使用根目录描述符逐层 O_NOFOLLOW 打开，拒绝非普通文件和多链接文件；大小和正文来自同一已打开句柄。Docker 读写以容器 UID 执行，删除 daemon archive 读写实现。Office 转 PDF 也在账号容器内运行。 |
| R1：任意内网网关访问 | 工具网络无直连公网、其他账号和宿主机路由；公网 HTTP(S) 经过过滤代理。管理员按 origin 放行内网模型网关，其他私网拒绝。回环、未指定 IPv6、IPv4 映射 IPv6、链路本地和元数据目标始终拒绝。NewAPI 模型发现、Embedding 探测显式使用代理。 |

账号内保留 Agent 各自工作目录，并允许浏览自己的其他 Agent 和 shared 文件；个人根目录显示为 `~`，不能继续向上。容器数据卷由账号稳定标识决定，正常重启保留文件；关闭工作区视图释放其 MCP，账号运行时由管理器负责生命周期。失败启动释放容器和网络，保留账号数据卷。

## 验证

- 27 个核心测试文件：**391 passed，1 skipped，30 subtests passed**。跳过项为需要 Chromium 的浏览器测试，随后在真实浏览器集成中单独通过。覆盖会话、聊天、团队、SOP/DAG、文件、知识库、凭据、Redis/SQL、渠道和本地 SDK 基础功能。
- 最终运行时镜像的 **10 项真实集成测试全部通过**：跨账号 Read 拒绝；UID/服务密钥/源码/socket 边界；3 MB 二进制流；同账号 Agent 目录；容器网络与代理；MCP 注册及工作区关闭后重建；浏览器 MCP 公网访问；Office 转 PDF；异常启动清理；工作区视图重开；HTML/SVG 在 Chromium 中下载且不能读取模拟令牌；内网网关允许规则及禁止地址验证。部分测试同时包含多个场景。
- 部署后对生产代理再次验证：B 容器启动绑定 `0.0.0.0` 的临时监听端口，B 自己可以连接，A 无法连接；回环、元数据、代理管理接口被拒绝，公网 HTTPS 正常。全部使用随机前缀测试容器和虚构文件，完成后删除测试容器、网络与卷。
- 修改的 Python 文件通过 Black/Flake8 检查；8 个新增或核心实现文件通过严格函数注解的 Mypy 检查；Compose 配置校验和 git diff 空白检查通过。

测试入口：

- `tests/user_isolation_security_test.py`
- `tests/user_sandbox_integration_test.py`
- `tests/egress_policy_integration_test.py`

后两项需在有 Docker socket 的隔离测试控制容器运行，设置 `RUN_USER_SANDBOX_TESTS=1`；容器测试还需指定 `TEST_SANDBOX_IMAGE`、`TEST_EGRESS_CONTAINER`，网关策略测试需指定 `TEST_GATEWAY_HOST`、`TEST_CONTROL_NETWORK`。使用合成账号和临时存储，不应对生产用户内容运行旧的漏洞复现脚本来验收新架构。

## 部署与边界

已重新构建 API、账号运行时和代理镜像，并用 `docker compose up -d --no-build --wait` 重建运行服务。API、Web UI 和 Redis 健康检查通过。实际 Nginx 入口首页返回 200，`/api/auth/health` 返回 204，未认证的目录请求返回 401；16 个关键运行源码文件与工作区哈希一致。

管理员当前使用的模型网关是公网 HTTPS origin，本次无需额外私网例外。新的内网网关由管理员配置 `AGENTSCOPE_ALLOWED_GATEWAYS` 后重新创建 egress。工具容器默认限制 1 GiB 内存、2 CPU、256 进程；部署要求 Docker Engine 28+，isolated 模式见 [Docker 官方说明](https://docs.docker.com/engine/release-notes/28/)。

容器共享宿主内核，API 和 Docker daemon 属于可信管理平面。LocalWorkspaceManager 保留给可信本地 SDK，不能作为不互信账号的服务运行时。本次没有证明第三方 MCP、外部平台、宿主内核或全部未来接口不存在漏洞；验收结论针对已确认缺口及当前服务入口。

不提供旧数据迁移、旧绑定或旧接口适配。部署说明和离线打包脚本已同步增加账号运行时、代理镜像及账号卷备份规则。
