# 用户对话与数据隔离检查

检查日期：2026-11-10（Asia/Shanghai）

## 结论

**用户数据隔离没有做到位，当前不能按可靠的多用户系统验收。** 常规会话和消息查询有用户过滤，JWT 登录也已接入，但下载接口、工作区绑定、文件访问和会话控制存在绕过路径。数据库有 user_id 不等于整个系统已隔离。

发现 6 项需要修复的安全或隔离问题，另有 2 项对话体验问题和 1 项退出登录语义待明确。

## 检查与验证边界

- 检查当前工作区代码，以及正在运行的 ori_asv1 Docker 服务。
- 核对工作区文件路由、会话路由、ChatService、SessionService、LocalWorkspaceManager 共 5 个关键源码文件：规范化换行后的 SHA-256 与运行容器一致。
- 在运行容器内另建 FastAPI 测试应用，加载真实路由、JWTAuthService、WorkspaceService、SessionService、ChatService 和 LocalWorkspaceManager。持久存储使用严格按用户过滤的内存替身，消息总线使用独立的 InMemoryMessageBus，文件放在自动清理的临时目录。
- 共运行 13 个验证场景，完整执行成功；包含正常鉴权的对照场景和漏洞复现。没有连接生产 Redis、调用模型或修改真实对话。
- 对实际 Web 入口另做只读探测，全部使用随机且不存在的用户和会话标识：文件接口不带身份返回 401，添加任意 X-User-ID 后返回 404；目录接口添加同样请求头仍返回 401。这证明下载接口的旧身份入口确实能穿过当前 Nginx。
- 前端问题通过代码审查确认，没有做浏览器断网或切换账号的端到端测试。
- 本次不是所有模块的完整渗透测试；没有据此认定 SQL 后端、全部外部渠道或所有工具均已安全。

可复现脚本：[user-isolation-repro-2026-11-10.py](user-isolation-repro-2026-11-10.py)。

在仓库根目录运行（不访问生产存储，容器名按当前环境填写）：

```powershell
Get-Content -Raw -LiteralPath .\docs\reviews\user-isolation-repro-2026-11-10.py |
    docker exec -i ori_asv1-agentscope-1 python -
```

## F1 / P0：工作区与知识库下载绕过 JWT

代码：

- [工作区下载](../../src/agentscope/app/_router/_workspace.py#L585)：602–603 行直接把 X-User-ID 当作调用者。
- [知识库原始文档下载](../../src/agentscope/app/_router/_knowledge_base.py#L877)：922–923 行存在相同处理。
- [JWT 接入](../../examples/agent_service/main.py)：仅替换 get_current_user_id；上述两个下载函数没有依赖它，因此没有受到替换保护。

影响：知道目标用户及资源标识后，不需要密码、Bearer token 或签名下载 token，便可伪造用户身份读取目标文件。目标标识不可猜测只能提高利用门槛，不能代替授权。

复现：没有 JWT，仅提供 B 的 X-User-ID，工作区文件和知识库文档均返回 200，并读到测试 B 的私有标记。反而仅带合法 Bearer、没有下载 token 或旧请求头时，工作区下载返回 401，说明这里保留了与当前登录体系不一致的路径。

修复：下载只接受统一 JWT 鉴权或受限的签名下载能力；删除可由外部调用者任意设置的身份请求头分支。签名应绑定完整资源身份，不能靠客户端提供的用户 ID 认人。对两个接口分别补未登录和跨用户回归验证。

## F2 / P0：文件浏览和读取允许跳出用户工作区

代码：

- [目录浏览](../../src/agentscope/app/_router/_workspace.py#L453)：注释明确允许离开工作区；466 行只规范化路径。
- [文件读取](../../src/agentscope/app/_router/_workspace.py#L616)：同样只执行 abspath，没有根目录边界验证。
- [下载 token 签发](../../src/agentscope/app/_router/_workspace.py#L548)：验证自己的会话存在后，直接签署客户端原始路径。
- [本地路径解析](../../src/agentscope/tool/_builtin/_backend.py#L285)：绝对路径原样规范化，其他路径与 cwd 拼接，均没有权限判断。文件预览路径也应一并修复。

影响：A 可以使用自己的合法会话列出上层目录，读取 B 的文件；不需要伪造 B 的 JWT 或知道 B 的会话 ID。在当前 LocalWorkspaceManager 部署下，可读范围是后端容器进程有权读取的文件，可能包括其他用户产物、记忆及服务配置。

复现：A 合法登录后，为 ../agent-b/private.txt 申请 token，再下载，返回 200 且读到 B 标记；浏览 .. 能看到 B 的工作区目录。

修复：统一在服务端解析真实路径并检查所属工作区边界，覆盖读取、目录、预览、token 签发和上传；同时处理绝对路径、父目录跳转、符号链接和平台差异。API 路径校验不能替代 F6 的工具运行隔离。

## F3 / P1：客户端可以绑定他人的 workspace_id

代码：

- [创建会话](../../src/agentscope/app/_router/_session.py#L345)：349 行无条件采用 body.workspace_id。
- [本地工作区缓存](../../src/agentscope/app/workspace_manager/_local_workspace_manager.py#L103)：只按 workspace_id 查缓存，命中后不核对 user_id 或调用者是否具有共享授权。

影响：知道 B 的 workspace_id 时，A 可以给自己的 Agent 新建会话并指定这个 ID，命中 B 的已有工作区。由此可能访问 B 的文件和长期记忆，改变后续工具执行位置。对当前 LocalWorkspaceManager，复现依赖目标工作区已在相应进程缓存；其他远程管理器需要分别验证，不能据此断言都存在同样结果。

复现：B 工作区已载入后，A 创建会话指定 workspace-b，返回 201；通过真实 WorkspaceService 解析 A 的新会话，获得的对象与 B 的工作区是同一个对象。

修复：将工作区作为有 owner 和共享授权的服务端资源；普通创建请求不能任意指定外部绑定。团队借用需要独立的授权流程，工作区缓存命中也必须检查权限。

## F4 / P1：越权删除虽返回 404，却会取消他人的任务并清空事件

代码：

- [删除会话](../../src/agentscope/app/_service/_session.py#L379)：会话为空时没有提前返回。
- 384 行先清理投影，386–388 行发送取消信号，394–395 行清理消息总线；均发生在确认删除成功之前。
- [取消广播](../../src/agentscope/app/_service/_session.py#L299)及[消费者](../../src/agentscope/app/_manager/_cancel_dispatcher.py#L164)使用 session_id 定位任务。

影响：A 提交 B 的 session_id，最终虽然收到 404，但仍能干扰 B 的聊天、实时语音或后台任务，清除其回放事件、收件箱和确认投影。没有证据表明这条路径删除了 B 的持久聊天记录。

复现：A 删除 B 的测试会话，返回 404；B 会话记录保留，但 B 的取消广播已经发送，预先存在的 B 事件日志被清空。

修复：任何取消、投影或消息总线操作之前，先验证完整的用户、Agent、会话归属；找不到立即返回。后台控制对象也应携带经过验证的归属信息。

## F5 / P1：越权发送消息会污染他人的对话事件流

代码：

- [发送入口](../../src/agentscope/app/_router/_chat.py#L392)：未检查会话归属就登记后台任务并返回 started。
- [执行流程](../../src/agentscope/app/_service/_chat.py#L953)：先占用只含 session_id 的锁，再检查资源。
- [失败上报](../../src/agentscope/app/_service/_chat.py#L1342)无论是否已经完成授权，都会调用 _report_failure。
- [错误事件发布](../../src/agentscope/app/_service/_chat.py#L783)：向请求指定的 session_id 发布 REPLY_START 和 REPLY_END。
- [事件键](../../src/agentscope/app/message_bus/_keys.py)：回放、锁、投影等均以 session_id 为主要边界。

影响：A 无权读取 B 的持久消息，但可以让 B 的实时界面收到伪造的失败回复，也可能错误切换“生成中”状态。这里确认的是事件污染和运行干扰，没有证据表明此路径让 A 读取到 B 的聊天正文。

复现：A 对 B 会话 POST /chat/，返回 200 started；真实 ChatService 拒绝资源访问后，却向 B 的事件日志写入两个回复事件。B 的持久消息没有被本次测试写入。

修复：在登记运行、持锁、查询确认投影或入队之前完成会话授权；授权失败不能发布到目标会话。错误上报仅适用于已确认归属的会话。统一梳理事件、取消、锁和投影的用户与会话边界。

## F6 / P1：本地工作区不是用户间的工具执行沙箱

代码：

- [当前服务配置](../../examples/agent_service/main.py)：使用 LocalWorkspaceManager，长期记忆使用 workspace.workdir。
- [工作目录构造](../../src/agentscope/app/workspace_manager/_local_workspace_manager.py#L129)：物理路径是 basedir/agent_id，没有 user_id 或 workspace_id。
- [本地工具进程](../../src/agentscope/tool/_builtin/_backend.py#L799)：直接在服务环境启动子进程，没有独立用户、文件系统或显式净化的环境变量。

影响：

1. 用户通过自己的工具权限执行代码时，实际处于同一个后端容器的权限环境；模型提示词和“用户确认工具”都不能充当不同账号之间的安全边界。
2. 同一个 Agent 的多个会话默认共用文件和长期记忆是当前 PER_AGENT 设计。如果业务需要对话间隔离，当前默认值不满足要求。
3. 即便切到 PER_SESSION，LocalWorkspaceManager 仍会把不同工作区 ID 映射到相同的 agent_id 目录。若启用跨用户共享 Agent，同一个 agent_id 的路径也需要额外处理。

复现：PER_SESSION 下两个不同 workspace_id 的 workdir 完全相同。LocalBackend 启动的子进程能读取审计进程设置的无敏感环境标记，证实环境继承。检查运行配置还确认后端进程 UID=0，Redis 未配置密码；本次没有读取服务密钥或用户 Redis 数据。

修复：对不互信用户采用独立的工具工作进程或容器、最小挂载、独立身份和必要的网络访问限制；API 服务密钥不能继承给用户工具进程。物理目录同时体现经过验证的用户与工作区身份。仅修改 isolation 枚举或目录命名不能解决本地任意工具代码的权限问题。

## 对话体验问题（代码审查）

### U1 / P2：SSE 中断后没有自动恢复

[useMessages.ts:398](../../examples/web_ui/frontend/src/hooks/useMessages.ts#L398)只打开一次事件流，异常时设置 error，正常 EOF 直接退出，没有重连或历史同步。

网络闪断、休眠或代理断开后，服务端可能继续生成，而界面停止更新；若错过 REPLY_END，phase 可能一直留在 streaming。建议增加重连退避、恢复后的历史与状态同步，以及事件游标去重。当前客户端事件生成器没有向上层保留每个事件的回放 ID，需要一起设计恢复协议。

### U2 / P2：发送失败的乐观消息没有回滚或失败状态

[useMessages.ts:435](../../examples/web_ui/frontend/src/hooks/useMessages.ts#L435)先把消息放到本地列表；450–452 行请求失败时仅切换 phase 和 error。

请求返回 409 或网络失败时，消息仍留在界面，缺少明确的“未送达”状态，刷新后可能消失。建议区分发送中、已确认和失败，并支持使用同一客户端消息 ID 安全重试。

## 已有的隔离措施

- 当前示例服务把普通 get_current_user_id 替换为 JWT 验证；签名校验固定 HS256，要求 issuer、audience、过期时间和身份字段。
- Redis 的会话、消息、Agent、凭据等主要键包含 user_id。
- 普通消息列表和事件订阅在进入前调用 storage.get_session(user_id, agent_id, session_id)。
- 默认 DenyAllResourceAccessPolicy 拒绝跨所有者资源共享。
- 前端退出登录时清理 token、React Query 缓存和上次对话定位；登录时也清理查询缓存。
- 双用户对照：A 读取 B 的普通消息接口返回 404；没有 JWT 的目录请求返回 401。这些正确路径不能覆盖前述漏洞。

## 配置与退出语义

- 当前运行容器的管理员密码、JWT secret、download secret 均已偏离仓库默认值。本次没有输出具体值，也没有声称这些值已经泄漏。
- 仓库的 docker-compose.yml 和 auth.py 仍提供可用的默认管理员密码、签名 secret。新部署应在生产模式下拒绝占位配置；这属于部署模板风险，不能等同于当前实例正在使用默认密钥。
- /auth/logout 当前只返回 204，没有服务端撤销 token。复现显示退出后重用原 token，/auth/me 仍返回 200。当前默认 token 有效期 1440 分钟。若产品的退出含义只是清理本机登录，这是现有设计；若要求丢失设备下线或立即失效，需要 token 版本、撤销记录或更短令牌配合刷新机制。不要将此项与前述已经确认的越权读取混为一谈。
- 库本身 deps.py 的默认身份依赖仍然信任 X-User-ID。当前示例入口做了 JWT override；若部署其他 create_app 入口，必须重新确认鉴权，不能假定库默认安全。

## 修复顺序与验收

1. 优先修复 F1 与 F2：关掉旧身份入口，封住文件越界访问。
2. 同时修复 F3、F4、F5：工作区授权，以及对话所有副作用发生前的统一归属检查。
3. 在给不互信用户开放工具能力前完成 F6；根据产品要求明确会话之间是否共享长期记忆。
4. 修复 SSE 恢复和发送失败状态，明确退出登录的安全语义。
5. 用两个真实测试账号补全端到端验收：会话、消息、文件、知识库原文、工作区、确认、取消、实时语音，以及任务恢复。越权请求返回 401/404 时还必须验证没有事件、取消、队列或工作区副作用。

本次仅新增审计报告和隔离复现脚本，没有修复业务代码或更改部署配置。

