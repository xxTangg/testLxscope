# 龙信助手 Docker 启动说明

SOP 现支持 DAG 并行编排、节点级重试和断点恢复，使用与 API 说明见 [SOP DAG 编排与局部恢复](./SOP_DAG.md)。

本文说明如何使用仓库根目录的 `docker-compose.yml` 构建并启动龙信助手。

## 1. 环境要求

- Docker Engine 28 或更高版本（账号网络使用 isolated bridge）
- Docker Compose v2（使用 `docker compose` 命令）
- 建议至少 4 GB 可用内存
- 服务器能够访问配置的模型 API

检查 Docker：

```bash
docker --version
docker compose version
```

## 2. 创建环境配置

进入项目根目录，将示例配置复制为 `.env`。

Linux/macOS：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少修改登录密码、JWT 密钥和下载密钥。启动后在网页的「凭证」页面配置 `longxin_AI`。

```env
# 浏览器访问端口
WEB_UI_PORT=8000

# 初始管理员账号
AGENTSCOPE_USERNAME=admin
AGENTSCOPE_USER_ID=local-user
AGENTSCOPE_PASSWORD=请替换为安全密码

# JWT 签名密钥必须至少 32 字节
AGENTSCOPE_JWT_SECRET=请替换为至少32字节的随机长字符串

# JWT 有效期，单位为分钟；1440 表示 24 小时
AGENTSCOPE_JWT_EXPIRE_MINUTES=1440

# 文件下载签名密钥
AGENTSCOPE_DOWNLOAD_SECRET=请替换为随机长字符串

# 可选：Redis 密码
REDIS_PASSWORD=
```

生产环境可使用以下命令生成随机密钥：

```bash
openssl rand -hex 32
```

请勿将包含真实密码和密钥的 `.env` 提交到 Git。

启动后，在「凭证」页面选择 **longxin_AI**，填写 API Key 和 API Base URL。预填的 `http://lxcoreaihub.cnecc.com:5000/v1` 可以改成任意后端可访问的 HTTP(S) 网关。对话模型由用户直接填写模型名称（模型 ID），多个 ID 用换行、中文或英文逗号分隔，支持混用。添加和编辑凭证时不探测网关模型列表。创建知识库时选择已有凭证，再选择或输入 Embedding 模型，系统会自动检测并保存向量维度。检测失败时可重试，或在高级设置中手动填写维度。

## 3. 构建并启动

在项目根目录执行：

```bash
docker compose --profile build build agentscope user-sandbox egress web-ui
docker compose up -d --no-build
```

首次构建需要下载基础镜像和项目依赖，耗时取决于网络速度。启动后查看状态：

```bash
docker compose ps
```

升级已有部署时也执行上面的构建和启动命令。Compose 会按新配置重建服务，
移除后端的宿主机端口映射；数据卷会保留。若旧的 `8001` 规则仍在云安全组或防火墙中，
请一并删除。

正常情况下，以下服务应处于 `Up` 或 `healthy` 状态：

- `redis`：账号、会话等数据存储
- `agentscope`：后端 API
- `egress`：账号工具使用的 HTTP 出站代理
- `web-ui`：龙信助手前端

## 4. 访问系统

默认访问地址：

```text
http://服务器IP:8000
```

本机启动时可访问：

```text
http://127.0.0.1:8000
```

首次启动时，使用 `.env` 中设置的初始管理员账号登录。登录页也支持自助注册，每个注册账号会获得独立的用户 ID 和数据空间。管理员可以从左下角「账号中心 → 用户管理」搜索账号、重置密码、停用或恢复普通账号，并查看近 7 天或 30 天的 Token 用量。账号初始化后，密码和状态以 Redis 中的记录为准。

注册成功后，系统自动创建该账号专属的「通用智能体」并选中。登录或刷新页面时，如果账号没有智能体，也会自动创建一个；已有智能体会保留。新账号在注册成功、自动登录后进入聊天页时会自动打开一次新手引导。系统在服务端按账号记录这次机会，之后可点击左下角「新手引导」重新查看。

Web UI 通过同源 `/api/` 路径访问后端。Nginx 在 Docker Compose 内部将请求转发给
`agentscope:8000`，用户不需要访问或开放后端端口。服务器防火墙或安全组只需允许
`WEB_UI_PORT`（默认 `8000`）。

```text
http://服务器IP:8000/api/
```

## 5. 检查与排错

查看所有服务状态：

```bash
docker compose ps -a
```

持续查看日志：

```bash
docker compose logs -f --tail=200
```

只查看后端日志：

```bash
docker compose logs -f --tail=200 agentscope
```

经 Web UI Nginx 代理检查认证服务：

```bash
curl -i http://127.0.0.1:8000/api/auth/health
```

正常响应状态为 `204 No Content`。

## 6. 常用维护命令

重新构建并更新服务：

```bash
docker compose --profile build build agentscope user-sandbox egress web-ui
docker compose up -d --no-build
```

只重建后端配置：

```bash
docker compose up -d --force-recreate agentscope
```

停止服务但保留数据：

```bash
docker compose down
```

重新启动：

```bash
docker compose restart
```

查看资源占用：

```bash
docker stats
```

## 7. 数据持久化

Compose 使用以下 Docker 数据卷：

- `redis-data`：所有账号、会话及 Redis 数据
- `<部署前缀>-user-<账号哈希>`：每个账号单独的工作区数据卷，由 API 按需创建
- `agentscope-blobs`：上传和生成的文件
- `qdrant-data`：向量数据库数据

执行普通的 `docker compose down` 不会删除这些数据。不要在生产环境随意执行下面的命令：

```bash
docker compose down -v
```

该命令会删除 Compose 声明的 Redis、文件和向量数据卷。账号独立工作区卷需要单独管理，备份时也必须一并包含。

## 8. JWT 配置说明

- `AGENTSCOPE_JWT_EXPIRE_MINUTES` 控制新签发 JWT 的有效期。
- 修改过期时间后，需要重建或重新创建 `agentscope` 容器才能读取新环境变量。
- 已签发的 JWT 仍使用签发时的过期时间。
- 修改 `AGENTSCOPE_JWT_SECRET` 会让所有旧 JWT 失效，所有用户需要重新登录。

## 9. 会话时间标准

- 后端容器和智能体的默认时区为北京时间（`Asia/Shanghai`，UTC+08:00）。会话创建、更新时间仍以明确标注 UTC 的 ISO 8601 时间传输。
- Web UI 的会话默认标题、时间标签以及“今天／更早”分组统一按北京时间（`Asia/Shanghai`，UTC+08:00）显示，不跟随浏览器所在时区。
- 旧版 Docker 部署中未标注时区的会话时间按 UTC 读取，无需批量修改数据库。手动命名和对话生成的标题保持原样。
- 例如旧时间 `2026-11-13T06:51:38` 在界面显示为 `2026-11-13 14:51:38`。
- 容器共用宿主机时钟。若 UTC 时间本身有偏差，应在部署服务器上检查系统时间和 NTP 同步；修改时区不能修正时钟漂移。

可执行 `docker compose exec agentscope date -Iseconds` 检查容器时间，输出应包含 `+08:00`。

## 10. 新会话默认权限

通过 Web UI 或 `POST /sessions/` 创建的新会话默认使用 `accept_edits`。
工作目录内的文件创建、编辑及部分文件操作（包括普通删除、移动）可以自动执行；
Python 脚本、依赖安装、工作目录外写入等操作仍按权限规则确认。

用户仍可在会话中切换权限模式。已有会话保留原模式，定时任务和渠道会话的显式权限配置保持不变。

更完整的服务器、离线部署和反向代理说明参见 `OPS_DEPLOYMENT.md`。

## 账号工具运行边界

每个账号的工具在独立的非 root 容器中运行，只挂载本账号数据卷。账号网络使用 internal + isolated bridge，无宿主机桥接地址，普通公网 HTTP(S) 经 `egress` 代理访问。后端的聊天、模型发现和 Embedding 请求直接连接凭证指定的网关。

API 是可信容器编排入口，需要挂载 Docker socket；工具容器不会得到该 socket、API 源码、Redis 网络或服务密钥。`user-sandbox` 是只构建的镜像，不作为常驻 Compose 服务启动；首次使用文件或工具时，API 自动创建账号容器。账号容器和网络在 API 正常退出时释放，数据卷保留。每个活动账号默认限制 1 GiB 内存、2 CPU、256 个进程，部署容量需要按活跃账号数准备。

账号数据卷独立于 Compose 的静态卷列表，备份时可用 `docker volume ls --filter label=agentscope.deployment=<部署前缀>` 查找。文件空间规则见 [账号文件空间](docs/user-file-space.md)。
