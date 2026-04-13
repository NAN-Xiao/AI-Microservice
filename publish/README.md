# deploy/publish.sh 使用说明

## 认证方式（二选一）

### 方式 1：账号密码（需安装 sshpass）

```bash
# 安装 sshpass（Linux 服务器或 WSL 中执行）
sudo yum install -y sshpass        # Rocky Linux / CentOS
sudo apt install -y sshpass        # Ubuntu / Debian
brew install hudochenkov/sshpass/sshpass  # macOS

# 交互输入密码（执行后提示输入）
bash publish.sh

# 非交互（环境变量传密码，适合 CI）
REMOTE_PASS="yourpassword" bash publish.sh
```

### 方式 2：SSH Key 免密（推荐，一次配置永久使用）

```bash
ssh-keygen -t rsa -b 4096          # 生成密钥（已有可跳过）
ssh-copy-id root@10.1.6.76         # 推送公钥
ssh root@10.1.6.76                 # 验证能直接登录即可
bash publish.sh                    # 直接运行，无需密码
```

> 脚本会自动检测：优先用 sshpass（密码），其次检测 SSH Key，两者都不可用时给出提示。

---

## 用法

```bash
# 在 WSL / Git Bash / Linux 中执行

# 发布全部服务
bash publish.sh

# 只发布 gateway（Java，会本地 mvn 打包）
bash publish.sh gateway

# 只发布 Python 服务
bash publish.sh ui_builder
bash publish.sh video_analyze

# 发布多个指定服务
bash publish.sh ui_builder video_analyze

# 发布全部 + 自动重启（发布后在服务器 restart）
RESTART=true bash publish.sh

# 完整示例（密码 + 指定用户 + 自动重启）
REMOTE_USER=root REMOTE_PASS="mypass" RESTART=true bash publish.sh gateway
```

---

## 各服务发布逻辑

| 服务 | 本地操作 | 传输方式 | 远程操作 |
|------|----------|----------|----------|
| `gateway` | `mvn clean package -DskipTests` | `scp` jar + start.sh + docs/ | 可选重启 |
| `ui_builder` | 无需构建 | `rsync`（排除 venv / \_\_pycache\_\_ / logs） | `pip install` + 可选重启 |
| `video_analyze` | 无需构建 | `rsync`（排除 venv / \_\_pycache\_\_ / logs） | `pip install` + 可选重启 |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REMOTE_USER` | `root` | SSH 登录用户名 |
| `REMOTE_PASS` | 空（交互输入）| SSH 密码，设置后跳过交互提示 |
| `RESTART` | `false` | 发布后是否自动重启服务 |

---

## 服务器目录结构（脚本自动创建）

```
/opt/ai-microservice/
├── gateway/
│   ├── gateway-1.0.0.jar
│   ├── start.sh
│   ├── logs/
│   └── docs/gateway-routes-example.json
├── ui_builder/
│   ├── app.py
│   ├── start.sh
│   ├── venv/          ← 首次发布自动创建
│   └── logs/
└── video_analyze/
    ├── app.py
    ├── start.sh
    ├── venv/          ← 首次发布自动创建
    └── logs/
```
