#!/bin/bash
# 推送到 GitHub 脚本

# 配置
REPO_URL="https://github.com/kukucaiCndy/ai-ssh-daemon.git"

# 初始化 git（如果还没有）
if [ ! -d ".git" ]; then
    git init
fi

# 添加所有文件
git add .

# 提交
git commit -m "Initial commit: AI SSH Daemon with long-lived connections

Features:
- SSH long-lived connection daemon
- Session management with credential storage
- Cross-platform support (Windows/macOS/Linux)
- Secure password storage using system keyring
- Client-server architecture via socket communication

Components:
- ssh_daemon_server.py: Background daemon
- ssh_client.py: CLI client tool
- requirements.txt: Dependencies
- README.md: Documentation"

# 添加远程仓库（如果不存在）
git remote remove origin 2>/dev/null
git remote add origin $REPO_URL

# 推送到 GitHub
git branch -M main
git push -u origin main

echo "Done! Repository pushed to $REPO_URL"
