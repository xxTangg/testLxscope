#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' '[ERROR] 内网内置版不在用户任务中安装系统字体；请联系管理员预装已授权的本地字体。' >&2
exit 1
