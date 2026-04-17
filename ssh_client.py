#!/usr/bin/env python3
"""
SSH Client - 客户端命令行工具
与后台 Daemon 通信，执行 SSH 命令
"""

import socket
import json
import sys
import os
import platform
import argparse
import getpass
from pathlib import Path
from typing import Optional

# 配置
APP_NAME = 'ssh_daemon'
if platform.system() == 'Windows':
    PID_FILE = Path(os.environ.get('TEMP', 'C:/Windows/Temp')) / 'ssh_daemon.pid'
    SOCKET_PATH = Path(os.environ.get('TEMP', 'C:/Windows/Temp')) / 'ssh_daemon.sock'
    DAEMON_PORT = 9876
else:
    PID_FILE = Path('/tmp/ssh_daemon.pid')
    SOCKET_PATH = Path('/tmp/ssh_daemon.sock')
    DAEMON_PORT = 9876

CONFIG_DIR = Path.home() / '.ssh_daemon'
SESSIONS_FILE = CONFIG_DIR / 'sessions.json'


def safe_getpass(prompt: str) -> str:
    """安全的密码输入，兼容 Windows"""
    if platform.system() == 'Windows':
        print(prompt, end='', flush=True)
        import msvcrt
        password = ''
        while True:
            ch = msvcrt.getch()
            if ch in [b'\r', b'\n']:
                print()
                break
            elif ch == b'\x03':  # Ctrl+C
                raise KeyboardInterrupt
            elif ch == b'\x08':  # Backspace
                if password:
                    password = password[:-1]
                    print('\b \b', end='', flush=True)
            else:
                password += ch.decode('utf-8', errors='ignore')
                print('*', end='', flush=True)
        return password
    else:
        return getpass.getpass(prompt)


class DaemonClient:
    """Daemon 客户端"""

    def __init__(self):
        self.connected = False

    def _is_daemon_running(self) -> bool:
        """检查 Daemon 是否运行"""
        if not PID_FILE.exists():
            return False

        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())

            if platform.system() == 'Windows':
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(1, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
            else:
                os.kill(pid, 0)
                return True
        except:
            return False

        return False

    def _send_request(self, request: dict) -> dict:
        """发送请求到 Daemon"""
        if not self._is_daemon_running():
            return {'success': False, 'error': 'Daemon 未运行，请先启动: python ssh_daemon_server.py start'}

        try:
            sock = socket.socket(socket.AF_UNIX if platform.system() != 'Windows' else socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)

            if platform.system() == 'Windows':
                sock.connect(('127.0.0.1', DAEMON_PORT))
            else:
                sock.connect(str(SOCKET_PATH))

            sock.sendall(json.dumps(request).encode('utf-8') + b'\n')

            # 接收响应
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in chunk:
                    break

            sock.close()
            return json.loads(data.decode('utf-8'))
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def connect_session(self, name: str) -> bool:
        """连接会话"""
        response = self._send_request({'action': 'connect', 'name': name})
        return response.get('success', False)

    def disconnect_session(self, name: str) -> bool:
        """断开会话"""
        response = self._send_request({'action': 'disconnect', 'name': name})
        return response.get('success', False)

    def execute(self, name: str, command: str, timeout: int = 60):
        """执行命令"""
        return self._send_request({
            'action': 'execute',
            'name': name,
            'command': command,
            'timeout': timeout
        })

    def list_sessions(self) -> list:
        """列出会话"""
        response = self._send_request({'action': 'list'})
        return response.get('sessions', [])


class SessionManager:
    """本地会话配置管理"""

    def __init__(self):
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_sessions(self) -> dict:
        if not SESSIONS_FILE.exists():
            return {}
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_sessions(self, sessions: dict):
        with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, indent=2, ensure_ascii=False)

    def create_session(self, name: str, host: str, port: int, user: str,
                       password: Optional[str] = None, key_file: Optional[str] = None) -> bool:
        """创建会话配置"""
        import keyring as kr

        sessions = self._load_sessions()

        if name in sessions:
            print(f"[错误] 会话 '{name}' 已存在")
            return False

        use_key = key_file is not None and os.path.exists(key_file)

        session = {
            'name': name,
            'host': host,
            'port': port,
            'user': user,
            'use_key': use_key,
            'key_file': key_file if use_key else None,
            'created_at': __import__('datetime').datetime.now().isoformat()
        }

        sessions[name] = session
        self._save_sessions(sessions)

        # 保存密码到密钥环
        if password:
            try:
                service = f"{APP_NAME}_{name}"
                kr.set_password(service, 'password', password)
            except Exception as e:
                print(f"[警告] 保存密码失败: {e}")

        print(f"[成功] 会话 '{name}' 已创建")
        return True

    def delete_session(self, name: str) -> bool:
        """删除会话配置"""
        import keyring as kr

        sessions = self._load_sessions()
        if name not in sessions:
            print(f"[错误] 会话 '{name}' 不存在")
            return False

        del sessions[name]
        self._save_sessions(sessions)

        # 删除密码
        try:
            service = f"{APP_NAME}_{name}"
            kr.delete_password(service, 'password')
        except:
            pass

        print(f"[成功] 会话 '{name}' 已删除")
        return True

    def list_local_sessions(self) -> list:
        """列出本地会话配置"""
        sessions = self._load_sessions()
        return list(sessions.values())

    def session_exists(self, name: str) -> bool:
        """检查会话是否存在"""
        sessions = self._load_sessions()
        return name in sessions


def main():
    parser = argparse.ArgumentParser(description='SSH Client - 与 Daemon 通信的客户端工具')
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # session 命令
    session_parser = subparsers.add_parser('session', help='会话管理')
    session_subparsers = session_parser.add_subparsers(dest='session_action')

    # session create
    create_parser = session_subparsers.add_parser('create', help='创建会话')
    create_parser.add_argument('name', help='会话名称')
    create_parser.add_argument('--host', '-H', required=True, help='主机地址')
    create_parser.add_argument('--port', '-p', type=int, default=22, help='端口')
    create_parser.add_argument('--user', '-u', required=True, help='用户名')
    create_parser.add_argument('--password', '-P', help='密码（不建议命令行传入）')
    create_parser.add_argument('--key', '-k', help='私钥文件路径')

    # session delete
    delete_parser = session_subparsers.add_parser('delete', help='删除会话')
    delete_parser.add_argument('name', help='会话名称')

    # session list
    session_subparsers.add_parser('list', help='列出所有会话配置')

    # daemon 命令
    daemon_parser = subparsers.add_parser('daemon', help='Daemon 管理')
    daemon_subparsers = daemon_parser.add_subparsers(dest='daemon_action')
    daemon_subparsers.add_parser('start', help='启动 Daemon')
    daemon_subparsers.add_parser('stop', help='停止 Daemon')
    daemon_subparsers.add_parser('status', help='查看 Daemon 状态')

    # connect 命令
    connect_parser = subparsers.add_parser('connect', help='连接到会话（保持长连接）')
    connect_parser.add_argument('name', help='会话名称')

    # disconnect 命令
    disconnect_parser = subparsers.add_parser('disconnect', help='断开会话')
    disconnect_parser.add_argument('name', help='会话名称')

    # exec 命令
    exec_parser = subparsers.add_parser('exec', help='执行命令')
    exec_parser.add_argument('--session', '-s', help='会话名称')
    exec_parser.add_argument('--timeout', '-t', type=int, default=60, help='超时时间')
    exec_parser.add_argument('cmd', nargs='+', help='要执行的命令')

    # status 命令
    subparsers.add_parser('status', help='查看所有会话状态')

    args = parser.parse_args()

    session_manager = SessionManager()
    client = DaemonClient()

    try:
        if args.command == 'session':
            if args.session_action == 'create':
                password = args.password
                if not password and not args.key:
                    password = safe_getpass(f"请输入密码: ")
                session_manager.create_session(
                    args.name, args.host, args.port, args.user,
                    password, args.key
                )

            elif args.session_action == 'delete':
                session_manager.delete_session(args.name)

            elif args.session_action == 'list':
                sessions = session_manager.list_local_sessions()
                print("\n[本地会话配置]")
                print("-" * 70)
                print(f"{'名称':<15} {'主机':<25} {'用户':<15} {'认证方式':<10}")
                print("-" * 70)
                for s in sessions:
                    auth = "密钥" if s.get('use_key') else "密码"
                    host = f"{s['host']}:{s['port']}"
                    print(f"{s['name']:<15} {host:<25} {s['user']:<15} {auth:<10}")
                print("-" * 70)

            else:
                session_parser.print_help()

        elif args.command == 'daemon':
            if args.daemon_action == 'start':
                import subprocess
                import sys
                # 在后台启动 Daemon
                if platform.system() == 'Windows':
                    subprocess.Popen([sys.executable, 'ssh_daemon_server.py', 'start'],
                                     creationflags=subprocess.CREATE_NEW_CONSOLE)
                else:
                    subprocess.Popen([sys.executable, 'ssh_daemon_server.py', 'start'],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                print("[Client] Daemon 启动中...")

            elif args.daemon_action == 'stop':
                if client._is_daemon_running():
                    # 发送停止命令
                    response = client._send_request({'action': 'stop'})
                    if response.get('success'):
                        print("[Client] Daemon 已停止")
                    else:
                        print(f"[Client] 停止失败: {response.get('error')}")
                else:
                    print("[Client] Daemon 未运行")

            elif args.daemon_action == 'status':
                if client._is_daemon_running():
                    response = client._send_request({'action': 'status'})
                    if response.get('success'):
                        print(f"[Client] Daemon 正在运行 (PID: {response.get('pid')})")
                    else:
                        print("[Client] Daemon 正在运行")
                else:
                    print("[Client] Daemon 未运行")

            else:
                daemon_parser.print_help()

        elif args.command == 'connect':
            if not session_manager.session_exists(args.name):
                print(f"[错误] 会话 '{args.name}' 不存在")
                sys.exit(1)

            print(f"[Client] 正在连接会话 '{args.name}'...")
            if client.connect_session(args.name):
                print(f"[Client] 会话 '{args.name}' 已连接并保持长连接")
                print("[Client] 您现在可以使用 'exec' 命令执行操作，连接会一直保持")
            else:
                print(f"[Client] 连接失败")

        elif args.command == 'disconnect':
            print(f"[Client] 正在断开会话 '{args.name}'...")
            if client.disconnect_session(args.name):
                print(f"[Client] 会话 '{args.name}' 已断开")
            else:
                print(f"[Client] 断开失败或会话未连接")

        elif args.command == 'exec':
            session_name = args.session
            if not session_name:
                # 如果没有指定会话，检查是否有默认会话
                sessions = session_manager.list_local_sessions()
                if len(sessions) == 1:
                    session_name = sessions[0]['name']
                    print(f"[Client] 使用默认会话: {session_name}")
                else:
                    print("[错误] 请指定会话名称 (--session)")
                    sys.exit(1)

            if not session_manager.session_exists(session_name):
                print(f"[错误] 会话 '{session_name}' 不存在")
                sys.exit(1)

            cmd = ' '.join(args.cmd)
            print(f"[执行] {cmd}")
            print("-" * 50)

            response = client.execute(session_name, cmd, args.timeout)

            if response.get('success') or 'exit_code' in response:
                stdout = response.get('stdout', '')
                stderr = response.get('stderr', '')
                exit_code = response.get('exit_code', -1)

                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr, file=sys.stderr)

                print("-" * 50)
                print(f"[退出码] {exit_code}")
            else:
                print(f"[错误] {response.get('error', '未知错误')}")

        elif args.command == 'status':
            # Daemon 状态
            if client._is_daemon_running():
                print("[Daemon 状态] 运行中")
            else:
                print("[Daemon 状态] 未运行")

            # 会话状态
            sessions = client.list_sessions()
            print("\n[会话连接状态]")
            print("-" * 70)
            print(f"{'名称':<15} {'主机':<25} {'用户':<15} {'连接状态':<10}")
            print("-" * 70)

            local_sessions = {s['name']: s for s in session_manager.list_local_sessions()}
            for s in sessions:
                local = local_sessions.get(s['name'], {})
                host = f"{s['host']}:{s['port']}"
                status = "已连接" if s.get('connected') else "未连接"
                print(f"{s['name']:<15} {host:<25} {s['user']:<15} {status:<10}")

            # 显示本地配置但 Daemon 不知道的会话
            for name, local in local_sessions.items():
                if not any(s['name'] == name for s in sessions):
                    host = f"{local['host']}:{local['port']}"
                    print(f"{name:<15} {host:<25} {local['user']:<15} {'未连接':<10}")

            print("-" * 70)

        else:
            parser.print_help()
            print("\n[使用示例]")
            print("  # 启动 Daemon")
            print("  python ssh_client.py daemon start")
            print("")
            print("  # 创建会话")
            print("  python ssh_client.py session create mac --host 192.168.16.131 --user kukucai")
            print("")
            print("  # 连接会话（保持长连接）")
            print("  python ssh_client.py connect mac")
            print("")
            print("  # 执行命令（使用已保持的连接）")
            print("  python ssh_client.py exec --session mac 'ls -la'")
            print("")
            print("  # 查看状态")
            print("  python ssh_client.py status")
            print("")
            print("  # 停止 Daemon")
            print("  python ssh_client.py daemon stop")

    except KeyboardInterrupt:
        print("\n[Client] 操作已取消")


if __name__ == '__main__':
    main()
