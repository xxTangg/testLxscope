# AgentScope 服务器部署与访问指南

本文适用于仓库中的 `docker-compose.yml`，用于在 Linux 服务器上部署
AgentScope 后端、Web UI 和 Redis。

## 先回答：部署成功后用户访问什么地址？

默认情况下，用户在浏览器打开 Web UI 地址：

```text
http://<服务器公网 IP 或内网 IP>:8000
```

其中 `8000` 是 `WEB_UI_PORT` 的默认值。如果 `.env` 中修改了
`WEB_UI_PORT`，用户访问修改后的端口，例如：

```text
http://192.168.1.20:8080
```

前端 Nginx 会把 `/api/` 请求转发到 Compose 内部的 `agentscope` 服务。用户只需访问
Web UI 地址；后端 API 和 Redis 都不发布到宿主机端口。

注意：`localhost` 或 `127.0.0.1` 指的是当前浏览器所在的电脑。服务器部署后，
用户不能访问 `http://localhost:8000`，除非浏览器就在服务器上；用户应使用服务器
的公网 IP、内网 IP 或域名。

## 1. 服务和端口

| 服务 | 容器端口 | 服务器端口 | 用途 |
| --- | ---: | ---: | --- |
| `web-ui` | 80 | `WEB_UI_PORT`，默认 `8000` | 前端页面；Nginx 同时代理 `/api/` 到后端 |
| `agentscope` | 8000 | 不映射到宿主机 | 后端 API，只允许 Compose 内部访问 |
| `redis` | 6379 | 不映射到宿主机 | 后端存储，只允许 Compose 内部访问 |

默认访问链路如下：

```text
用户浏览器 ── http://服务器:8000 ──> web-ui Nginx
                                      ├── 页面请求 ──> 静态前端
                                      └── /api/* ──> agentscope:8000 ──> redis
```

## 2. 服务器要求

- Linux 服务器，已安装 Docker Engine 和 Docker Compose v2
- 用户网络能够访问 `WEB_UI_PORT`（默认 `8000`）
- 服务器能够访问配置的模型 API；离线内网环境需要确保模型 API 在内网可达
- 至少准备一个可用的 OpenAI-compatible 模型 API Key

确认 Docker Compose 版本：

```bash
docker --version
docker compose version
```

## 3. 准备部署文件

### 3.1 在线构建部署

如果服务器可以访问代码仓库和镜像构建所需的网络资源：

```bash
git clone <项目仓库地址> agentscope
cd agentscope
cp .env.example .env
```

### 3.2 离线部署

在可联网且安装了 Docker 的机器上构建离线包：

```powershell
.\scripts\package_offline.ps1
```

脚本会在 `dist/agentscope-offline-时间戳/` 生成：

- `agentscope-images.tar`：AgentScope 后端、Web UI 和 Redis 镜像
- `docker-compose.yml`
- `.env.example`
- `OPS_DEPLOYMENT.md`
- `manifest.json`：镜像包 SHA256

镜像归档使用打包机器 Docker 的 Linux 架构；请在与目标服务器架构一致的 Linux/amd64
或 Linux/arm64 Docker 环境中打包。`manifest.json` 会标明归档的平台。

将整个目录复制到服务器后执行：

```bash
docker load -i agentscope-images.tar
cp .env.example .env
```

离线启动时使用 `--no-build`，否则 Compose 可能尝试重新构建镜像：

```bash
docker compose up -d --no-build
```

## 4. 配置 `.env`

服务器上至少检查和修改以下配置：

```env
# 用户浏览器访问的 Web UI 端口
WEB_UI_PORT=8000

# 默认登录账号。user_id 是后端数据隔离使用的稳定标识
AGENTSCOPE_USERNAME=admin
AGENTSCOPE_USER_ID=local-user
AGENTSCOPE_PASSWORD=请设置登录密码

# JWT 签名密钥，至少 32 字节；非本地部署必须替换
AGENTSCOPE_JWT_SECRET=请替换为至少32字节的随机长字符串
AGENTSCOPE_JWT_EXPIRE_MINUTES=1440

# 非本地部署必须替换为随机长字符串
AGENTSCOPE_DOWNLOAD_SECRET=请替换为随机长字符串

# 可选，但生产环境建议设置
REDIS_PASSWORD=请设置 Redis 密码

```

默认配置创建一个账号。若需要多个用户，可在 `.env` 中设置
`AGENTSCOPE_AUTH_USERS`，每个账号必须使用不同的 `user_id`：

```env
AGENTSCOPE_AUTH_USERS={"alice":{"user_id":"user-alice","password":"alice-password"},"bob":{"user_id":"user-bob","password":"bob-password"}}
```

登录成功后，Web UI 使用 JWT 访问 API；API 从已验证的 token 中取得 `user_id`，
并沿用现有的用户维度存储隔离。修改账号配置或 JWT 密钥后需要重启
`agentscope` 服务；修改 JWT 密钥会使之前签发的 token 失效。

用户也可以在登录页自助注册。注册账号及其密码校验数据保存在 Redis 数据卷中，
每个注册账号会自动生成独立的 `user_id`；重建容器不会丢失，删除 Redis 数据卷则
会同时删除这些注册账号。登录后的用户入口提供账号信息、切换账号、退出登录和
当前账号的 Token 用量统计。

## 5. 启动服务

### 在线构建并启动

```bash
docker compose up -d --build
docker compose ps
```

### 使用已加载的离线镜像启动

```bash
docker compose up -d --no-build
docker compose ps
```

三个服务状态均应为 `running`，并且 `agentscope`、`web-ui` 的健康检查应通过。
升级已有部署时执行上述 `docker compose up -d --build`，Compose 会移除后端的宿主机
端口映射且保留数据卷；也请删除云安全组或防火墙中旧的 `8001` 放行规则。

## 6. 部署后检查

先在服务器本机检查：

```bash
# Web UI 应返回 HTML
curl -I http://127.0.0.1:8000
# 如果修改过 WEB_UI_PORT，请把上面的 8000 换成实际端口。

# 经 Web UI Nginx 代理的 API 存活探针应返回 204
curl -i http://127.0.0.1:8000/api/auth/health
# 如果修改过 WEB_UI_PORT，请替换上面的 8000。
```

如果本机正常、用户电脑访问失败，通常是云服务器安全组或系统防火墙没有放行
Web UI 端口。以内网用户网段为例：

```bash
sudo ufw allow from <用户网段> to any port 8000 proto tcp
```

后端 API 和 Redis 只通过 Compose 内部网络访问，不需要开放宿主机端口。

## 7. 用户首次访问

1. 运维人员确认服务器 IP 或 DNS 已指向部署服务器。
2. 在浏览器打开 `http://<服务器 IP 或域名>:8000`。
3. 使用 `.env` 中配置的用户名和密码登录。
4. 前端通过当前站点的 `/api/` 路径访问后端，无需填写 API 地址。

用户只需要访问一个地址：

```text
Web UI 和 API = http(s)://<服务器地址>:<WEB_UI_PORT>
API 路径      = /api/*（由 Web UI Nginx 转发到后端）
```

使用 HTTPS 时，反向代理只需为这个域名配置证书。浏览器的 API 请求与页面同源，
不需要额外开放后端端口，也不会产生跨域或混合内容请求。

## 8. 使用域名和反向代理

Compose 内的 Web UI Nginx 已将 `/api/` 代理到后端。生产环境若需域名和 HTTPS，
外部 Nginx 或 Traefik 只需代理到 Web UI 的宿主机端口：

```text
https://agent.example.com -> 127.0.0.1:8000
```

Nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name agent.example.com;

    # 此处配置证书
    # ssl_certificate ...;
    # ssl_certificate_key ...;

    client_max_body_size 500m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

用户打开 `https://agent.example.com` 后登录即可。外部代理把所有请求转到 Web UI；
容器内的 Nginx 再将 `/api/` 请求转给后端，并处理流式响应和较大的上传。

## 9. 常用运维命令

```bash
# 查看状态
docker compose ps

# 查看最近日志
docker compose logs --tail=200 agentscope web-ui redis

# 持续查看后端日志
docker compose logs -f agentscope

# 重启服务
docker compose restart

# 停止服务，但保留数据卷
docker compose down
```

不要执行 `docker compose down -v`，否则会删除 Redis、工作区、文件和 Qdrant
数据卷。

## 10. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 浏览器打不开 `:8000` | 检查 `web-ui` 状态、服务器端口映射、安全组和防火墙 |
| 页面能打开，但 API 请求失败 | 检查 `http://127.0.0.1:8000/api/auth/health`、`web-ui` 日志及 Compose 网络 |
| API 返回 503 或服务未就绪 | 查看 `docker compose logs agentscope redis`，确认 Redis 和模型配置正常 |
| 用户被分到错误的数据空间 | 检查 `AGENTSCOPE_AUTH_USERS`，确保每个账号使用唯一且稳定的 `user_id` |
| 服务器本机正常，外部访问失败 | 检查云安全组、UFW/iptables、公司网络和 DNS |

## 11. 生产环境安全检查

- 使用 HTTPS，并通过 Web UI 的同源 `/api/` 代理访问后端。
- 替换默认登录密码和 `AGENTSCOPE_JWT_SECRET`，不要把真实值提交到 Git。
- 当前 JWT 是轻量账号隔离方案；如需管理员后台、密码找回、撤销 token、权限角色或抵御恶意攻击，再接入完整账号体系或公司 SSO。
- 将 `AGENTSCOPE_DOWNLOAD_SECRET` 替换成随机长字符串。
- 设置 Redis 密码，并确认 Redis 端口没有映射到公网。
- 后端 API 不发布宿主机端口，只允许 Compose 内部网络和 Web UI 代理访问。
- 定期备份 Docker 数据卷：`redis-data`、`agentscope-workspaces`、
  `agentscope-blobs` 和 `qdrant-data`。
- 在网页「凭证」页面配置 `longxin_AI`，由后端保存模型 API Key。请勿将 Key 提交到 Git 或写入前端代码。
