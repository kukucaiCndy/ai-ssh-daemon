# AI SSH Daemon

一个专为 AI 设计的 SSH 长连接守护进程，支持会话管理、凭证安全存储和后台保持连接。

## 特性

- 🔒 **安全凭证存储** - 使用系统密钥环（Windows Credential Manager / macOS Keychain / Linux Secret Service）存储密码
- 🔄 **长连接保持** - 后台 Daemon 保持 SSH 连接，避免频繁连接断开
- 🚀 **快速响应** - 复用已有连接，命令执行无需重新认证
- 📦 **会话管理** - 支持多个 SSH 会话，可随时切换
- 🖥️ **跨平台** - 支持 Windows、macOS、Linux

## 架构

```
┌─────────────────┐     Socket/Named Pipe     ┌──────────────────┐
│   ssh_client    │  ◄──────────────────────►  │  ssh_daemon_server│
│   (客户端)       │                           │   (后台守护进程)   │
└─────────────────┘                           └──────────────────┘
                                                        │
                                                        │ SSH Protocol
                                                        ▼
                                               ┌──────────────────┐
                                               │   Remote Server  │
                                               │   (远程服务器)    │
                                               └──────────────────┘
```

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/kukucaiCndy/ai-ssh-daemon.git
cd ai-ssh-daemon
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖：
- `paramiko>=3.0.0` - SSH 协议实现
- `keyring>=24.0.0` - 系统密钥环访问

## 快速开始

### 1. 启动 Daemon

```bash
python ssh_daemon_server.py start
```

Daemon 将在后台运行，保持 SSH 长连接。

### 2. 创建会话

```bash
python ssh_client.py session create myserver --host 192.168.1.100 --user admin
```

输入密码后，凭证会自动保存到系统密钥环。

### 3. 连接会话

```bash
python ssh_client.py connect myserver
```

连接会一直保持，直到手动断开或 Daemon 停止。

### 4. 执行命令

```bash
python ssh_client.py exec --session myserver "ls -la"
python ssh_client.py exec --session myserver "pwd"
python ssh_client.py exec --session myserver "whoami"
```

所有命令复用同一个 SSH 连接！

### 5. 查看状态

```bash
python ssh_client.py status
```

### 6. 停止 Daemon

```bash
python ssh_client.py daemon stop
```

## 命令参考

### 会话管理

```bash
# 创建会话
python ssh_client.py session create <name> --host <host> --user <user> [--port 22] [--key <key_file>]

# 删除会话
python ssh_client.py session delete <name>

# 列出所有会话
python ssh_client.py session list
```

### 连接管理

```bash
# 连接会话（保持长连接）
python ssh_client.py connect <name>

# 断开会话
python ssh_client.py disconnect <name>

# 查看所有会话状态
python ssh_client.py status
```

### 命令执行

```bash
# 执行命令
python ssh_client.py exec --session <name> "<command>" [--timeout 60]

# 示例
python ssh_client.py exec --session myserver "ls -la"
python ssh_client.py exec --session myserver "cat /etc/os-release"
```

### Daemon 管理

```bash
# 启动 Daemon
python ssh_daemon_server.py start

# 停止 Daemon
python ssh_client.py daemon stop

# 查看 Daemon 状态
python ssh_client.py daemon status
```

## 配置存储

- **会话配置**: `~/.ssh_daemon/sessions.json`
- **密码**: 存储在系统密钥环中（不在配置文件中）
- **PID 文件**: `/tmp/ssh_daemon.pid` (Linux/macOS) 或 `%TEMP%/ssh_daemon.pid` (Windows)
- **Socket**: `/tmp/ssh_daemon.sock` (Linux/macOS) 或 TCP 127.0.0.1:9876 (Windows)

## 使用场景

### AI 自动化操作

```python
# 通过客户端 API 与 Daemon 通信
import subprocess

# 执行远程命令
result = subprocess.run(
    ['python', 'ssh_client.py', 'exec', '--session', 'myserver', 'df -h'],
    capture_output=True,
    text=True
)
print(result.stdout)
```

### CI/CD 集成

```yaml
# .github/workflows/deploy.yml
- name: Deploy to Server
  run: |
    python ssh_daemon_server.py start
    python ssh_client.py session create prod --host $HOST --user $USER
    python ssh_client.py connect prod
    python ssh_client.py exec --session prod "cd /app && git pull && docker-compose up -d"
    python ssh_client.py daemon stop
```

## 安全说明

1. **密码存储**: 所有密码通过系统密钥环保存，不会以明文形式存储在配置文件中
2. **主机密钥**: 首次连接时会自动接受主机密钥，生产环境建议预先配置 known_hosts
3. **网络通信**: 客户端与 Daemon 通过本地 Socket/TCP 通信，不经过网络

## 故障排除

### Daemon 无法启动

```bash
# 检查端口是否被占用
netstat -an | grep 9876

# 手动清理 PID 文件
rm /tmp/ssh_daemon.pid  # Linux/macOS
del %TEMP%\ssh_daemon.pid  # Windows
```

### 连接失败

```bash
# 检查 Daemon 状态
python ssh_client.py daemon status

# 查看会话配置
python ssh_client.py session list

# 重新连接
python ssh_client.py disconnect <name>
python ssh_client.py connect <name>
```

### 密码问题

```bash
# 删除保存的密码
python ssh_client.py credential delete <session_name>

# 或手动清理系统密钥环中的 ssh_daemon_* 条目
```

## 平台支持

| 平台 | 状态 | 说明 |
|------|------|------|
| Windows | ✅ 支持 | 使用 TCP Socket + Windows Credential Manager |
| macOS | ✅ 支持 | 使用 Unix Socket + macOS Keychain |
| Linux | ✅ 支持 | 使用 Unix Socket + Secret Service |

## 开发

### 项目结构

```
.
├── ssh_daemon_server.py  # 后台守护进程
├── ssh_client.py         # 客户端命令行工具
├── requirements.txt      # 依赖
└── README.md            # 本文档
```

### 扩展开发

可以通过 Socket 直接与 Daemon 通信：

```python
import socket
import json

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('127.0.0.1', 9876))

request = {
    'action': 'execute',
    'name': 'myserver',
    'command': 'ls -la',
    'timeout': 60
}

sock.sendall(json.dumps(request).encode() + b'\n')
response = json.loads(sock.recv(4096).decode())
print(response)
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
