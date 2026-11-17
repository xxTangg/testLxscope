# 用户隔离深入检查

日期：2026-11-16（Asia/Shanghai）

状态：以下为修复前的审计快照。修复和部署验收见 [隔离漏洞修复验收](user-isolation-fix-2026-11-16.md)。

## 结论

**当前仍有用户读取其他用户数据的缺口，不能按不互信账号之间的完整隔离验收。** 上一轮完成了目录选择和普通文件接口的静态路径限制；这次确认工具执行、同源文件脚本、会话控制及文件打开时序仍存在问题。

共确认 5 类缺口，另记录 1 项内网访问能力需要按部署信任模型约束。没有修改业务代码或部署配置。

## 验证方法与边界

- 9 个关键文件与当前运行容器的源码一致（统一换行后的 SHA-256）：工作区路由、聊天路由、会话路由、ChatService、SessionService、LocalBackend、LocalWorkspace、auth.py、main.py。
- 在服务容器内另建测试应用，使用真实路由、真实 JWT 验签和账号状态检查、真实 ResourceAccessService + DenyAllResourceAccessPolicy、真实工作区与权限引擎。
- 两个虚构账号，严格按用户与 Agent 过滤的内存存储，独立 InMemoryMessageBus，临时目录；没有读取生产用户的聊天、文件或密钥，没有调用模型。
- 运行 36 个场景，其中 25 个身份/归属对照场景全部通过，其余为缺口复现或能力确认。HTML 脚本另用已安装的 Chromium 实际执行，只在隔离端口写入和读取模拟令牌标记。
- 对实际 Nginx 入口只使用不存在的随机式测试标识和无效令牌做 4 次只读探测。目录伪造 X-User-ID 返回 401，两个下载入口缺少 token 返回 422，无效登录令牌返回 401。
- 只读检查确认当前工具与服务共用 UID 0 环境，Redis 在应用网络内不带密码可 PING；没有读取 Redis 用户记录。Redis 没有因本次检查增加对外端口。
- 这里不是所有第三方 MCP、外部聊天渠道、远程工作区和 SQL 部署的完整渗透测试。主要运行结论针对当前 LocalWorkspaceManager + Redis + Nginx 部署。

证据：[复现脚本](user-isolation-deep-repro-2026-11-16.py)、[逐项结果](user-isolation-deep-results-2026-11-16.json)。

复现命令（只使用内存存储和临时文件）：

```powershell
Get-Content -Raw docs/reviews/user-isolation-deep-repro-2026-11-16.py |
    docker exec -i ori_asv1-agentscope-1 python -
```

## F1 / P0：Agent 的 Read 工具可以直接读取其他账号文件

位置：[本地工作区提供工具](../../src/agentscope/workspace/_local_workspace.py#L151)、[Read 只读声明](../../src/agentscope/tool/_builtin/_read.py#L126)、[权限引擎只读自动放行](../../src/agentscope/permission/_engine.py#L659)、[本地读取](../../src/agentscope/tool/_builtin/_backend.py#L882)、[子进程启动](../../src/agentscope/tool/_builtin/_backend.py#L807)。

API 的 resolve_file_path 不会自动约束 Read / Glob / Bash / 自定义 MCP 的后端。Read 被视为只读操作，因此权限引擎自动 ALLOW；随后按绝对路径直接读取服务进程可读的文件。

复现中，A 的权限上下文只登记 A 工作目录，使用默认 ACCEPT_EDITS 模式，读取 B 的临时 private.txt：权限结果 ALLOW，读到了 B 的模拟标记。**不需要 A 先批准越权读取，也不需要手动伪造 B 的 JWT。** 这里直接调用真实工具和权限引擎，不依赖模型是否愿意执行提示词。

另用本地工具子进程确认继承了模拟的服务环境变量；没有读取真实 secret。当前工具处于服务的 UID 0 环境，且从该环境可以无密码 PING Redis。这使服务配置、存储与其他用户文件处在同一权限域。

同一缺口还允许硬链接：把 B 的测试文件硬链接到 A 自己的目录后，A 的下载 token 可正常签发，并通过普通下载 API 读到 B 标记。realpath 不能识别文件 inode 的跨用户归属。该复现需要有在共享文件系统创建硬链接的能力；当前任意本地工具执行提供了这个条件。

建议：让不互信账号的工具运行在不同的受限进程/容器，仅挂载本账号数据；工具不能继承 API/JWT/download 密钥，也不能访问应用 Redis、其他用户挂载或 Docker socket。Read、Glob 等直接 I/O 工具也必须通过相同的受限环境。仅关闭 Bash、增加确认弹窗或再加一次字符串路径判断不够。公共注册入口目前存在，不能默认所有新账号都可信。

## F2 / P1：用户文件以应用同源 HTML 返回，可读取查看者登录令牌

位置：[下载响应类型和响应头](../../src/agentscope/app/_router/_workspace.py#L574)、[前端令牌存储](../../examples/web_ui/frontend/src/api/client.ts#L12)、[同源 API 代理](../../examples/web_ui/nginx.conf#L10)。

GET /workspace/files 在 download=false 时依据文件扩展名直接返回 text/html，没有强制附件或 sandbox CSP。Nginx 把它放在与网页相同的 origin 下；JWT 存在 localStorage，任何同源脚本都可读取。

复现链路：

1. A 通过真实技能上传 API 上传含 SKILL.md 和 audit.html 的文件夹，返回 201；没有调用模型、Bash 或管理员接口。
2. A 为自己文件签发正常下载 token。
3. 隔离 Chromium 先在测试 origin 的 localStorage 放入模拟的 B 登录令牌，再访问 A 的文件 URL。
4. HTML 内脚本运行，成功读取模拟 B 令牌。

影响需要受害者打开攻击者控制的文件链接。这里未读取真实用户令牌；但当前真实前端的令牌保存方式相同，攻击脚本可据此在受害者身份下调用 API。X-Content-Type-Options: nosniff 不会禁止正确标为 text/html 的脚本执行。

建议：文件响应采用明确的安全内联类型白名单，对 HTML、SVG 等主动内容强制附件，或在独立且不共享应用登录信息的文件 origin 提供；需要预览主动内容时使用有隔离效果的 sandbox/CSP。不能只修改前端预览组件，因为直接打开签名 URL 仍会走该响应。

## F3 / P1：跨账号发送和确认请求在授权前写入目标事件流或队列

位置：[聊天入口](../../src/agentscope/app/_router/_chat.py#L304)、[确认投影查询](../../src/agentscope/app/_router/_chat.py#L369)、[启动聊天](../../src/agentscope/app/_router/_chat.py#L393)、[运行持锁](../../src/agentscope/app/_service/_chat.py#L918)、[失败事件与消息写入](../../src/agentscope/app/_service/_chat.py#L712)。

聊天入口没有先验证请求会话归属，直接登记任务。ChatService 在只以 session_id 标识的目标锁下组装运行；授权失败后仍向请求指定的 session_id 发布失败事件。

复现：A 向 B 的测试会话 POST /chat/，返回 200；B 的事件流增加 2 个事件。B 的持久消息没有被读取或写入；错误回复写在 A 的用户命名空间下。因此本项确认的是事件污染、状态干扰及授权前持锁，而不是通过该接口直接读到 B 的聊天正文。

确认请求还有额外泄露：A 提交 B 的 leader session_id 和已知 reply_id，入口在未检查归属前解析 B 的确认投影，返回 B 的 worker session_id，并将 A 身份的恢复触发器写入队列。复现返回 200，目标 worker ID 被带回，队列新增 1 条。后续运行仍会拒绝跨账号资源，但不能抵消已经产生的信息泄露和队列副作用。

前提：知道目标 session_id；确认路由额外需要对应 reply_id。标识的随机性降低发现概率，不能替代授权。

建议：统一在读取投影、登记进程任务、获取目标锁、查询状态或入队之前验证用户/会话归属；确认转发后再次验证 worker 的账号与团队关系；只有已授权会话才能接收失败事件。

## F4 / P1：越权删除返回 404，但取消他人任务并清空运行信息

位置：[SessionService.delete_session](../../src/agentscope/app/_service/_session.py#L326)。

get_session 返回 None 后没有立即退出，仍继续清理投影、广播取消和清空消息总线。

复现：A 删除 B 的测试会话，HTTP 返回 404，B 的持久会话记录仍在；但 B 的取消广播已经发出、事件日志被清空、确认投影被删除。不能把 HTTP 404 当成没有越权副作用的证据。需要知道目标 session_id。

建议：任何取消、投影、事件或工作区清理之前完成完整归属检查；查无会话立即结束。并补充“返回 404 时目标状态完全不变”的回归测试。

## F5 / P1：路径检查后到实际打开前存在竞争窗口

位置：[路径校验](../../src/agentscope/tool/_builtin/_backend.py#L193)、[延迟流式读取](../../src/agentscope/app/_router/_workspace.py#L585)、[文件打开](../../src/agentscope/tool/_builtin/_backend.py#L931)。

realpath 检查通过后，StreamingResponse 中的文件流在后续迭代时才打开文件；检查结果是一个字符串路径，没有锁定被检查的目录/文件对象。

复现使用有效的 A 文件 token：接口先校验 A 的普通子目录并产生流式响应；在消费流之前，把 A 的该子目录改名，并在原位置建立指向 B 工作目录的符号链接；随后读到了 B 的模拟文件标记。

这需要用户能改变自己目录结构；在当前本地工具环境下该前提成立。测试刻意控制调度时序，证明存在窗口，不表示任意一次请求都能稳定撞中。它也不表示上一轮静态 symlink 拒绝测试失效：那些测试仍能正确拒绝在检查时已经存在的越界链接。

建议：在账号文件沙箱内打开文件，或用受限目录句柄进行不可逃逸的文件打开并从已打开句柄输出。预览、上传与文件元信息检查也需要统一考虑检查和使用之间的时序。只在 read_stream 前重复 realpath 仍然会留下新的窗口。

## R1 / 需按部署约束：网关探测允许访问任意内网 HTTP 地址

位置：[客户端指定 base_url](../../src/agentscope/app/_router/_schema/_credential.py#L68)、[网关 HTTP 请求](../../src/agentscope/app/_service/_newapi.py#L145)。

普通账号可提交自己的 api_key 和 base_url，服务端会向该地址请求 /models。隔离测试让它访问同进程另起的 localhost 端口，返回了模拟的“内部服务”模型列表。当前关闭 HTTP 重定向是正确措施，但不限制 localhost 和内网目标。

本项证明的是内网 HTTP 访问能力，没有据此声称已经读取到其他真实用户数据。内网模型网关本来就是产品用途，不能直接把所有私网地址一禁了之；建议由管理员定义允许访问的网关，或通过受限出站代理约束目标及访问权限。

## 已通过的边界

25 个对照场景全部通过，覆盖：JWT 缺失/伪造身份头、停用账号、撤销版本令牌、普通账号管理员接口、Agent/凭据列表、跨账号 Agent 修改、凭据修改/删除、会话消息/状态/SSE/配置、目录浏览、父目录越界、他人绝对路径、旧工作区绑定请求、下载旧身份入口、知识库原文 token、文档分块和检索。另有所属用户正常目录和知识库下载的正向对照。

这里的“通过”仅指本次指定操作。它不覆盖 F1 的直接工具 I/O、F2 的浏览器执行、F3/F4 的副作用或 F5 的受控并发窗口。

## 建议修复顺序

1. 优先封住工具到共享服务环境的权限通道，并限制主动内容文件的同源执行。
2. 把聊天、确认和删除的资源归属检查统一放到副作用之前。
3. 用账号文件沙箱与受限打开机制处理路径竞争和硬链接，不能只加强目录选择器。
4. 明确网关与第三方 MCP 的信任边界，完成出站访问控制。
5. 继续用两个测试账号验证拒绝结果和“目标状态未变”，并在真实浏览器中回归文件预览。
