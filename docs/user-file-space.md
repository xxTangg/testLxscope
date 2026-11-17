# 账号文件空间

登录账号的 `user_id` 是数据和工具执行的隔离边界。服务部署统一使用 `UserWorkspaceManager`，每个账号一个非 root 容器、独立数据卷及独立 internal/isolated Docker 网络。

```text
账号数据卷（仅挂载到本账号容器）
/workspace/
  shared/
  agents/<agent_id>/
  sessions/<sop_workspace_id>/
```

每个 Agent 使用自己的工作目录；同账号可以访问自己的其他 Agent 和 shared 文件，团队成员可以复用同账号的工作区。账号之间没有共享文件挂载。API 只根据已认证账号创建工作区标识，公共会话创建接口不接受 workspace_id；管理器在读取缓存前检查账号归属。

路径选择默认打开当前 Agent 目录，可以返回“我的空间”。API 返回 `~` 开头的逻辑路径和服务端确定的 parent_path，个人根目录的 parent_path 为 null，不能继续向上浏览。cwd 只决定文件浏览和 Git 状态的目录，工具工作目录仍是当前 Agent 目录。

目录、工作目录保存、状态、预览、附件、下载 token 均使用相同的账号边界。普通路径和符号链接解析必须在个人空间内。下载与预览沿根目录句柄逐层以 O_NOFOLLOW 打开文件，拒绝硬链接与非普通文件，从已打开的描述符读取元信息和正文，避免路径检查后的替换竞争。安全打开实现用于 Linux 服务部署，不会回退到不受限读取。

文件响应统一应用安全内联类型白名单。HTML、SVG 等主动内容强制附件，所有用户文件带 sandbox CSP、nosniff 和 no-store。工作区下载 token 绑定账号、Agent、会话和路径；知识库原文下载也必须使用签名 token。Office 转 PDF 在对应账号的容器内执行。

Read、Write、Bash、Glob、Grep、MCP、技能以及长期记忆都使用账号容器的同一后端。工具 UID 为 1000，根文件系统只读、能力全部移除、禁止提权；只挂载本账号数据卷和临时目录，不继承 API 密钥、源码、Docker socket 或应用 Redis 网络。API 负责可信容器编排，只有 API 挂载 Docker socket。独立容器仍共享 Docker 宿主内核，属于容器隔离边界。

工具通过 HTTP 出站代理访问公网 80/443。代理拒绝回环、云元数据和私网地址，账号网络隔离跨账号和宿主机路由。聊天、模型发现和 Embedding 请求由后端直接连接凭证指定的网关。

聊天入口、后台运行和删除流程在读取投影、持锁、入队、广播取消或清理状态前完成 user/Agent/session 校验；团队确认转发再次校验 worker 的账号和团队关系。

本次直接替换服务运行架构，不提供旧目录、旧绑定或旧接口适配。LocalWorkspaceManager 保留为可信本地 SDK 用法，生产服务入口没有本地工具回退。账号容器重建时保留独立数据卷；工作区视图关闭不销毁账号文件。
