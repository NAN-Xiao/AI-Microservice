#!/bin/bash
# 配置本机到服务器的 SSH 免密登录（只需运行一次）
# 用法: bash setup_ssh.sh

REMOTE_HOST="10.1.6.76"
REMOTE_USER="root"

# 1. 生成密钥（已有则跳过）
if [ ! -f ~/.ssh/id_rsa ]; then
    echo "生成 SSH 密钥..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
else
    echo "SSH 密钥已存在，跳过生成"
fi

# 2. 推送公钥到服务器（此步需要输入一次密码）
echo ""
echo "推送公钥到 ${REMOTE_USER}@${REMOTE_HOST}，请输入密码..."
ssh-copy-id -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa.pub "${REMOTE_USER}@${REMOTE_HOST}"

# 3. 验证
echo ""
if ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo 免密登录成功"; then
    echo "✅ 配置完成！之后运行 bash publish.sh 无需再输密码"
else
    echo "❌ 验证失败，请检查密码或服务器 SSH 配置"
    exit 1
fi
