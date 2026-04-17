#!/usr/bin/env python3
"""
SSH Daemon - 通用 SSH 客户端
支持 CLI 命令执行、交互式会话、Session 管理和凭证存储
"""

import argparse
import paramiko
import sys
import os
import json
import keyring
import getpass
import platform
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime


def safe_getpass(prompt: str) -> str:
    """安全的密码输入，兼容 Windows"""
    if platform.system() == 'Windows':
        # Windows 下使用普通 input，但隐藏输入
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

# 配置目录
CONFIG_DIR = Path.home() / '.ssh_daemon'
SESSIONS_FILE = CONFIG_DIR / 'sessions.json'
APP_NAME = 'ssh_daemon'


@dataclass
class SessionConfig:
    """会话配置"""
    name: str
    host: str
    port: int
    user: str
    use_key: bool = False
    key_file: Optional[str] = None
    created_at: str = None
    last_used: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'SessionConfig':
        return cls(**data)


class CredentialManager:
    """凭证管理器 - 使用系统密钥环"""

    @staticmethod
    def _get_service_name(session_name: str) -> str:
        return f"{APP_NAME}_{session_name}"

    @classmethod
    def save_password(cls, session_name: str, password: str) -> bool:
        """保存密码到系统密钥环"""
        try:
            service = cls._get_service_name(session_name)
            keyring.set_password(service, 'password', password)
            return True
        except Exception as e:
            print(f"[错误] 保存密码失败: {e}")
            return False

    @classmethod
    def get_password(cls, session_name: str) -> Optional[str]:
        """从系统密钥环获取密码"""
        try:
            service = cls._get_service_name(session_name)
            return keyring.get_password(service, 'password')
        except Exception:
            return None

    @classmethod
    def delete_password(cls, session_name: str) -> bool:
        """删除保存的密码"""
        try:
            service = cls._get_service_name(session_name)
            keyring.delete_password(service, 'password')
            return True
        except Exception:
            return False

    @classmethod
    def list_credentials(cls) -> List[str]:
        """列出所有保存的凭证（会话名称列表）"""
        try:
            # keyring 没有直接列出所有凭证的方法
            # 我们通过读取会话配置文件来间接获取
            session_manager = SessionManager()
            sessions = session_manager.list_sessions()
            return [s.name for s in sessions]
        except Exception:
            return []


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_sessions(self) -> Dict[str, dict]:
        """加载所有会话配置"""
        if not SESSIONS_FILE.exists():
            return {}
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_sessions(self, sessions: Dict[str, dict]):
        """保存所有会话配置"""
        with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, indent=2, ensure_ascii=False)

    def create_session(self, name: str, host: str, port: int, user: str,
                       password: Optional[str] = None, key_file: Optional[str] = None) -> bool:
        """创建新会话"""
        sessions = self._load_sessions()

        if name in sessions:
            print(f"[错误] 会话 '{name}' 已存在")
            return False

        use_key = key_file is not None and os.path.exists(key_file)

        session = SessionConfig(
            name=name,
            host=host,
            port=port,
            user=user,
            use_key=use_key,
            key_file=key_file if use_key else None
        )

        sessions[name] = session.to_dict()
        self._save_sessions(sessions)

        # 保存密码到密钥环
        if password:
            CredentialManager.save_password(name, password)

        print(f"[成功] 会话 '{name}' 已创建")
        return True

    def get_session(self, name: str) -> Optional[SessionConfig]:
        """获取会话配置"""
        sessions = self._load_sessions()
        if name not in sessions:
            return None
        return SessionConfig.from_dict(sessions[name])

    def update_session(self, name: str, **kwargs) -> bool:
        """更新会话配置"""
        sessions = self._load_sessions()
        if name not in sessions:
            print(f"[错误] 会话 '{name}' 不存在")
            return False

        sessions[name].update(kwargs)
        sessions[name]['last_used'] = datetime.now().isoformat()
        self._save_sessions(sessions)
        return True

    def delete_session(self, name: str) -> bool:
        """删除会话"""
        sessions = self._load_sessions()
        if name not in sessions:
            print(f"[错误] 会话 '{name}' 不存在")
            return False

        del sessions[name]
        self._save_sessions(sessions)

        # 同时删除保存的密码
        CredentialManager.delete_password(name)

        print(f"[成功] 会话 '{name}' 已删除")
        return True

    def list_sessions(self) -> List[SessionConfig]:
        """列出所有会话"""
        sessions = self._load_sessions()
        return [SessionConfig.from_dict(data) for data in sessions.values()]

    def session_exists(self, name: str) -> bool:
        """检查会话是否存在"""
        sessions = self._load_sessions()
        return name in sessions


class SimpleSSHClient:
    """简单的 SSH 客户端"""

    def __init__(self, host: str, user: str, password: Optional[str] = None,
                 key_file: Optional[str] = None, port: int = 22):
        self.host = host
        self.user = user
        self.password = password
        self.key_file = key_file
        self.port = port
        self.client = None

    def connect(self) -> bool:
        """建立连接"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.user,
            }

            if self.password:
                connect_kwargs['password'] = self.password
            elif self.key_file and os.path.exists(self.key_file):
                connect_kwargs['key_filename'] = self.key_file

            self.client.connect(**connect_kwargs)
            print(f"[SSH] 已连接到 {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[SSH] 连接失败: {e}")
            return False

    def execute(self, command: str, timeout: int = 60):
        """执行命令"""
        if not self.client:
            if not self.connect():
                return -1, "", "连接失败"

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()

            stdout_data = stdout.read().decode('utf-8', errors='ignore')
            stderr_data = stderr.read().decode('utf-8', errors='ignore')

            return exit_code, stdout_data, stderr_data
        except Exception as e:
            return -1, "", str(e)

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()
            print(f"[SSH] 已断开连接")


class SSHSession:
    """SSH 会话包装器 - 保持长连接"""

    def __init__(self, session_config: SessionConfig, password: Optional[str] = None):
        self.config = session_config
        self.password = password
        self.client: Optional[SimpleSSHClient] = None
        self.connected = False

    def connect(self) -> bool:
        """建立连接"""
        self.client = SimpleSSHClient(
            host=self.config.host,
            user=self.config.user,
            password=self.password,
            key_file=self.config.key_file,
            port=self.config.port
        )
        self.connected = self.client.connect()
        return self.connected

    def execute(self, command: str, timeout: int = 60):
        """执行命令"""
        if not self.connected or not self.client:
            print("[错误] 会话未连接")
            return -1, "", "会话未连接"
        return self.client.execute(command, timeout)

    def close(self):
        """关闭会话"""
        if self.client:
            self.client.close()
            self.connected = False


class SSHDaemon:
    """SSH Daemon 主类"""

    def __init__(self):
        self.session_manager = SessionManager()
        self.active_sessions: Dict[str, SSHSession] = {}
        self.current_session: Optional[str] = None

    def create_session(self, name: str, host: str, port: int, user: str,
                       password: Optional[str] = None, key_file: Optional[str] = None) -> bool:
        """创建会话"""
        # 如果没有提供密码，交互式询问
        if not password and not key_file:
            password = safe_getpass(f"请输入 {user}@{host} 的密码: ")

        return self.session_manager.create_session(name, host, port, user, password, key_file)

    def connect_session(self, name: str) -> bool:
        """连接到指定会话"""
        session_config = self.session_manager.get_session(name)
        if not session_config:
            print(f"[错误] 会话 '{name}' 不存在")
            return False

        # 获取保存的密码
        password = CredentialManager.get_password(name)

        # 如果没有保存密码，询问
        if not password and not session_config.use_key:
            password = safe_getpass(f"请输入 {session_config.user}@{session_config.host} 的密码: ")
            # 询问是否保存密码
            save = input("是否保存密码? (y/n): ").lower().strip()
            if save == 'y':
                CredentialManager.save_password(name, password)
                print("[信息] 密码已保存到系统密钥环")

        ssh_session = SSHSession(session_config, password)

        if ssh_session.connect():
            self.active_sessions[name] = ssh_session
            self.current_session = name
            self.session_manager.update_session(name, last_used=datetime.now().isoformat())
            print(f"[成功] 已连接到会话 '{name}'")
            return True
        else:
            print(f"[错误] 无法连接到会话 '{name}'")
            return False

    def disconnect_session(self, name: Optional[str] = None):
        """断开会话"""
        if name is None:
            name = self.current_session

        if name and name in self.active_sessions:
            self.active_sessions[name].close()
            del self.active_sessions[name]
            print(f"[信息] 会话 '{name}' 已断开")

            if self.current_session == name:
                self.current_session = None

    def execute(self, command: str, session_name: Optional[str] = None, timeout: int = 60):
        """在指定会话中执行命令"""
        if session_name is None:
            session_name = self.current_session

        if not session_name:
            print("[错误] 没有指定会话，请先连接或使用 --session 指定")
            return -1, "", "未指定会话"

        if session_name not in self.active_sessions:
            print(f"[错误] 会话 '{session_name}' 未连接，正在尝试连接...")
            if not self.connect_session(session_name):
                return -1, "", "连接失败"

        session = self.active_sessions[session_name]
        return session.execute(command, timeout)

    def switch_session(self, name: str) -> bool:
        """切换到指定会话"""
        if name not in self.active_sessions:
            print(f"[错误] 会话 '{name}' 未连接")
            return False

        self.current_session = name
        print(f"[信息] 已切换到会话 '{name}'")
        return True

    def list_active_sessions(self):
        """列出所有活动会话"""
        print("\n[活动会话列表]")
        print("-" * 60)
        for name, session in self.active_sessions.items():
            current = " (当前)" if name == self.current_session else ""
            print(f"  {name}{current}")
            print(f"    主机: {session.config.user}@{session.config.host}:{session.config.port}")
            print(f"    状态: {'已连接' if session.connected else '已断开'}")
        print("-" * 60)

    def list_all_sessions(self):
        """列出所有配置的会话"""
        sessions = self.session_manager.list_sessions()
        print("\n[会话配置列表]")
        print("-" * 80)
        print(f"{'名称':<15} {'主机':<25} {'用户':<15} {'认证方式':<10} {'状态':<10}")
        print("-" * 80)

        for s in sessions:
            has_password = CredentialManager.get_password(s.name) is not None
            auth = "密钥" if s.use_key else ("密码" if has_password else "未设置")
            active = "活动中" if s.name in self.active_sessions else "未连接"
            host = f"{s.host}:{s.port}"
            print(f"{s.name:<15} {host:<25} {s.user:<15} {auth:<10} {active:<10}")

        print("-" * 80)

    def delete_session(self, name: str) -> bool:
        """删除会话配置"""
        # 如果会话处于活动状态，先断开
        if name in self.active_sessions:
            self.disconnect_session(name)

        return self.session_manager.delete_session(name)

    def cleanup(self):
        """清理所有活动会话"""
        for name in list(self.active_sessions.keys()):
            self.disconnect_session(name)


def main():
    parser = argparse.ArgumentParser(description='SSH Daemon - 通用 SSH 客户端')
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

    # session connect
    connect_parser = session_subparsers.add_parser('connect', help='连接会话')
    connect_parser.add_argument('name', help='会话名称')

    # session disconnect
    disconnect_parser = session_subparsers.add_parser('disconnect', help='断开会话')
    disconnect_parser.add_argument('name', nargs='?', help='会话名称（默认当前会话）')

    # session switch
    switch_parser = session_subparsers.add_parser('switch', help='切换当前会话')
    switch_parser.add_argument('name', help='会话名称')

    # session list
    session_subparsers.add_parser('list', help='列出所有会话配置')

    # session active
    session_subparsers.add_parser('active', help='列出活动会话')

    # session delete
    delete_parser = session_subparsers.add_parser('delete', help='删除会话')
    delete_parser.add_argument('name', help='会话名称')

    # credential 命令
    cred_parser = subparsers.add_parser('credential', help='凭证管理')
    cred_subparsers = cred_parser.add_subparsers(dest='cred_action')

    # credential list
    cred_subparsers.add_parser('list', help='列出所有凭证')

    # credential delete
    cred_delete_parser = cred_subparsers.add_parser('delete', help='删除凭证')
    cred_delete_parser.add_argument('session_name', help='会话名称')

    # exec 命令
    exec_parser = subparsers.add_parser('exec', help='执行命令')
    exec_parser.add_argument('--session', '-s', help='会话名称（默认当前会话）')
    exec_parser.add_argument('--timeout', '-t', type=int, default=60, help='超时时间')
    exec_parser.add_argument('cmd', nargs='+', help='要执行的命令')

    # interactive 命令
    interactive_parser = subparsers.add_parser('interactive', help='交互模式')
    interactive_parser.add_argument('--session', '-s', help='会话名称（默认当前会话）')

    args = parser.parse_args()

    daemon = SSHDaemon()

    try:
        if args.command == 'session':
            if args.session_action == 'create':
                password = args.password
                if not password and not args.key:
                    password = safe_getpass(f"请输入密码: ")
                daemon.create_session(
                    args.name, args.host, args.port, args.user,
                    password, args.key
                )

            elif args.session_action == 'connect':
                daemon.connect_session(args.name)

            elif args.session_action == 'disconnect':
                daemon.disconnect_session(args.name)

            elif args.session_action == 'switch':
                daemon.switch_session(args.name)

            elif args.session_action == 'list':
                daemon.list_all_sessions()

            elif args.session_action == 'active':
                daemon.list_active_sessions()

            elif args.session_action == 'delete':
                daemon.delete_session(args.name)

            else:
                session_parser.print_help()

        elif args.command == 'credential':
            if args.cred_action == 'list':
                sessions = daemon.session_manager.list_sessions()
                print("\n[凭证列表]")
                print("-" * 60)
                for s in sessions:
                    has_cred = CredentialManager.get_password(s.name) is not None
                    status = "已保存" if has_cred else "未保存"
                    print(f"  {s.name}: {status}")
                print("-" * 60)

            elif args.cred_action == 'delete':
                if CredentialManager.delete_password(args.session_name):
                    print(f"[成功] 已删除会话 '{args.session_name}' 的凭证")
                else:
                    print(f"[错误] 删除凭证失败")

            else:
                cred_parser.print_help()

        elif args.command == 'exec':
            session_name = args.session
            if not session_name:
                # 如果没有指定会话，检查是否有默认会话
                sessions = daemon.session_manager.list_sessions()
                if len(sessions) == 1:
                    session_name = sessions[0].name
                    print(f"[信息] 使用默认会话: {session_name}")
                elif daemon.current_session:
                    session_name = daemon.current_session
                else:
                    print("[错误] 请指定会话名称 (--session)")
                    sys.exit(1)

            # 确保会话已连接
            if session_name not in daemon.active_sessions:
                if not daemon.connect_session(session_name):
                    sys.exit(1)

            cmd = ' '.join(args.cmd)
            print(f"[执行] {cmd}")
            print("-" * 50)

            exit_code, stdout, stderr = daemon.execute(cmd, session_name, args.timeout)

            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)

            print("-" * 50)
            print(f"[退出码] {exit_code}")

        elif args.command == 'interactive':
            session_name = args.session
            if not session_name:
                sessions = daemon.session_manager.list_sessions()
                if len(sessions) == 1:
                    session_name = sessions[0].name
                    print(f"[信息] 使用默认会话: {session_name}")
                elif daemon.current_session:
                    session_name = daemon.current_session
                else:
                    print("[错误] 请指定会话名称 (--session)")
                    sys.exit(1)

            # 确保会话已连接
            if session_name not in daemon.active_sessions:
                if not daemon.connect_session(session_name):
                    sys.exit(1)

            session = daemon.active_sessions[session_name]
            config = session.config

            print(f"\n进入交互模式 [会话: {session_name}]")
            print(f"主机: {config.user}@{config.host}:{config.port}")
            print("输入命令执行（输入 exit 退出）")
            print("-" * 50)

            while True:
                try:
                    cmd = input(f"[{config.user}@{config.host}]$ ")
                    if cmd.lower() in ['exit', 'quit', 'q']:
                        break
                    if not cmd.strip():
                        continue

                    exit_code, stdout, stderr = daemon.execute(cmd, session_name)

                    if stdout:
                        print(stdout)
                    if stderr:
                        print(stderr, file=sys.stderr)
                except KeyboardInterrupt:
                    print()
                    continue
                except EOFError:
                    break

        else:
            # 如果没有子命令，显示帮助
            parser.print_help()
            print("\n[使用示例]")
            print("  # 创建会话")
            print("  python ssh_daemon.py session create mac --host 192.168.16.131 --user kukucai")
            print("")
            print("  # 连接会话")
            print("  python ssh_daemon.py session connect mac")
            print("")
            print("  # 执行命令")
            print("  python ssh_daemon.py exec --session mac 'ls -la'")
            print("")
            print("  # 交互模式")
            print("  python ssh_daemon.py interactive --session mac")
            print("")
            print("  # 列出所有会话")
            print("  python ssh_daemon.py session list")

    except KeyboardInterrupt:
        print("\n[信息] 操作已取消")
    finally:
        daemon.cleanup()


if __name__ == '__main__':
    main()
