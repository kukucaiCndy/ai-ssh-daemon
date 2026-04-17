#!/usr/bin/env python3
"""
SSH Daemon Server - 后台守护进程
保持 SSH 长连接，通过 Socket 接收客户端命令
"""

import socket
import json
import threading
import os
import sys
import time
import signal
import platform
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

import paramiko
import keyring

# 配置
APP_NAME = 'ssh_daemon'
if platform.system() == 'Windows':
    PID_FILE = Path(os.environ.get('TEMP', 'C:/Windows/Temp')) / 'ssh_daemon.pid'
    SOCKET_PATH = Path(os.environ.get('TEMP', 'C:/Windows/Temp')) / 'ssh_daemon.sock'
else:
    PID_FILE = Path('/tmp/ssh_daemon.pid')
    SOCKET_PATH = Path('/tmp/ssh_daemon.sock')

CONFIG_DIR = Path.home() / '.ssh_daemon'
SESSIONS_FILE = CONFIG_DIR / 'sessions.json'


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
    """凭证管理器"""

    @staticmethod
    def _get_service_name(session_name: str) -> str:
        return f"{APP_NAME}_{session_name}"

    @classmethod
    def get_password(cls, session_name: str) -> Optional[str]:
        try:
            service = cls._get_service_name(session_name)
            return keyring.get_password(service, 'password')
        except Exception:
            return None


class SSHConnection:
    """SSH 连接包装器 - 保持长连接"""

    def __init__(self, session_config: SessionConfig, password: Optional[str] = None):
        self.config = session_config
        self.password = password
        self.client: Optional[paramiko.SSHClient] = None
        self.connected = False
        self.last_activity = datetime.now()
        self.lock = threading.Lock()

    def connect(self) -> bool:
        """建立连接"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': self.config.host,
                'port': self.config.port,
                'username': self.config.user,
            }

            if self.password:
                connect_kwargs['password'] = self.password
            elif self.config.key_file and os.path.exists(self.config.key_file):
                connect_kwargs['key_filename'] = self.config.key_file

            self.client.connect(**connect_kwargs)
            self.connected = True
            self.last_activity = datetime.now()
            print(f"[Daemon] 会话 '{self.config.name}' 已连接到 {self.config.host}:{self.config.port}")
            return True
        except Exception as e:
            print(f"[Daemon] 连接失败: {e}")
            return False

    def execute(self, command: str, timeout: int = 60):
        """执行命令"""
        with self.lock:
            if not self.connected or not self.client:
                # 尝试重新连接
                if not self.connect():
                    return -1, "", "连接失败"

            try:
                self.last_activity = datetime.now()
                stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
                exit_code = stdout.channel.recv_exit_status()

                stdout_data = stdout.read().decode('utf-8', errors='ignore')
                stderr_data = stderr.read().decode('utf-8', errors='ignore')

                return exit_code, stdout_data, stderr_data
            except Exception as e:
                self.connected = False
                return -1, "", str(e)

    def close(self):
        """关闭连接"""
        with self.lock:
            if self.client:
                try:
                    self.client.close()
                except:
                    pass
                self.client = None
            self.connected = False
            print(f"[Daemon] 会话 '{self.config.name}' 已断开")

    def is_alive(self) -> bool:
        """检查连接是否活跃"""
        if not self.connected or not self.client:
            return False
        try:
            # 发送一个简单命令测试连接
            transport = self.client.get_transport()
            if transport and transport.is_active():
                return True
            return False
        except:
            return False


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self._ensure_config_dir()
        self.connections: Dict[str, SSHConnection] = {}
        self.connections_lock = threading.Lock()

    def _ensure_config_dir(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_sessions(self) -> Dict[str, dict]:
        if not SESSIONS_FILE.exists():
            return {}
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def get_session_config(self, name: str) -> Optional[SessionConfig]:
        sessions = self._load_sessions()
        if name not in sessions:
            return None
        return SessionConfig.from_dict(sessions[name])

    def connect_session(self, name: str) -> bool:
        """连接会话"""
        session_config = self.get_session_config(name)
        if not session_config:
            return False

        with self.connections_lock:
            # 如果已连接，直接返回
            if name in self.connections and self.connections[name].is_alive():
                return True

            # 获取密码
            password = CredentialManager.get_password(name)

            # 创建新连接
            conn = SSHConnection(session_config, password)
            if conn.connect():
                self.connections[name] = conn
                return True
            return False

    def disconnect_session(self, name: str) -> bool:
        """断开会话"""
        with self.connections_lock:
            if name in self.connections:
                self.connections[name].close()
                del self.connections[name]
                return True
            return False

    def execute(self, name: str, command: str, timeout: int = 60):
        """在会话中执行命令"""
        with self.connections_lock:
            if name not in self.connections:
                # 自动连接
                if not self.connect_session(name):
                    return -1, "", "会话未连接且自动连接失败"

            conn = self.connections.get(name)
            if not conn:
                return -1, "", "会话不存在"

        return conn.execute(command, timeout)

    def list_sessions(self) -> List[dict]:
        """列出所有会话状态"""
        sessions = self._load_sessions()
        result = []
        for name, data in sessions.items():
            with self.connections_lock:
                is_connected = name in self.connections and self.connections[name].is_alive()
            result.append({
                'name': name,
                'host': data['host'],
                'port': data['port'],
                'user': data['user'],
                'connected': is_connected
            })
        return result

    def cleanup_inactive(self, max_idle_seconds: int = 300):
        """清理不活跃的连接"""
        with self.connections_lock:
            now = datetime.now()
            to_remove = []
            for name, conn in self.connections.items():
                idle_time = (now - conn.last_activity).total_seconds()
                if idle_time > max_idle_seconds or not conn.is_alive():
                    to_remove.append(name)

            for name in to_remove:
                self.connections[name].close()
                del self.connections[name]
                print(f"[Daemon] 清理不活跃会话: {name}")


class DaemonServer:
    """Daemon 服务器"""

    def __init__(self):
        self.session_manager = SessionManager()
        self.running = False
        self.socket = None
        self.cleanup_thread = None

    def start(self):
        """启动 Daemon"""
        # 检查是否已在运行
        if self._is_running():
            print("[Daemon] 已经在运行中")
            return False

        # 清理旧的 socket 文件
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except:
                pass

        # 创建 socket
        self.socket = socket.socket(socket.AF_UNIX if platform.system() != 'Windows' else socket.AF_INET, socket.SOCK_STREAM)

        if platform.system() == 'Windows':
            # Windows 使用 TCP socket
            self.socket.bind(('127.0.0.1', 9876))
        else:
            # Unix 使用 Unix socket
            self.socket.bind(str(SOCKET_PATH))

        self.socket.listen(5)
        self.socket.settimeout(1.0)  # 1秒超时，用于检查停止信号

        # 写入 PID 文件
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        self.running = True
        print(f"[Daemon] 已启动 (PID: {os.getpid()})")

        # 启动清理线程
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

        # 主循环
        try:
            while self.running:
                try:
                    conn, addr = self.socket.accept()
                    client_thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[Daemon] 接受连接错误: {e}")
        except KeyboardInterrupt:
            print("\n[Daemon] 收到停止信号")
        finally:
            self.stop()

        return True

    def stop(self):
        """停止 Daemon"""
        self.running = False

        if self.socket:
            try:
                self.socket.close()
            except:
                pass

        # 断开所有 SSH 连接
        for name in list(self.session_manager.connections.keys()):
            self.session_manager.disconnect_session(name)

        # 删除 PID 文件
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except:
                pass

        # 删除 socket 文件
        if platform.system() != 'Windows' and SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except:
                pass

        print("[Daemon] 已停止")

    def _is_running(self) -> bool:
        """检查 Daemon 是否已在运行"""
        if not PID_FILE.exists():
            return False

        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())

            # 检查进程是否存在
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
            # 进程不存在，清理 PID 文件
            try:
                PID_FILE.unlink()
            except:
                pass
            return False

        return False

    def _cleanup_loop(self):
        """定期清理不活跃的连接"""
        while self.running:
            time.sleep(60)  # 每分钟检查一次
            if self.running:
                self.session_manager.cleanup_inactive()

    def _handle_client(self, conn: socket.socket):
        """处理客户端请求"""
        try:
            conn.settimeout(30)

            # 接收数据
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in chunk:
                    break

            if not data:
                return

            # 解析请求
            request = json.loads(data.decode('utf-8'))
            action = request.get('action')
            response = {'success': False, 'error': '未知操作'}

            if action == 'connect':
                name = request.get('name')
                success = self.session_manager.connect_session(name)
                response = {'success': success}

            elif action == 'disconnect':
                name = request.get('name')
                success = self.session_manager.disconnect_session(name)
                response = {'success': success}

            elif action == 'execute':
                name = request.get('name')
                command = request.get('command')
                timeout = request.get('timeout', 60)
                exit_code, stdout, stderr = self.session_manager.execute(name, command, timeout)
                response = {
                    'success': exit_code == 0,
                    'exit_code': exit_code,
                    'stdout': stdout,
                    'stderr': stderr
                }

            elif action == 'list':
                sessions = self.session_manager.list_sessions()
                response = {'success': True, 'sessions': sessions}

            elif action == 'status':
                response = {
                    'success': True,
                    'running': True,
                    'pid': os.getpid()
                }

            elif action == 'stop':
                response = {'success': True}
                conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
                conn.close()
                self.stop()
                return

            # 发送响应
            conn.sendall(json.dumps(response).encode('utf-8') + b'\n')

        except json.JSONDecodeError as e:
            error_response = json.dumps({'success': False, 'error': f'JSON解析错误: {e}'})
            conn.sendall(error_response.encode('utf-8') + b'\n')
        except Exception as e:
            error_response = json.dumps({'success': False, 'error': str(e)})
            conn.sendall(error_response.encode('utf-8') + b'\n')
        finally:
            conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='SSH Daemon Server')
    parser.add_argument('action', choices=['start', 'stop', 'status'], help='操作')
    args = parser.parse_args()

    daemon = DaemonServer()

    if args.action == 'start':
        daemon.start()
    elif args.action == 'stop':
        if daemon._is_running():
            # 发送停止命令
            try:
                sock = socket.socket(socket.AF_UNIX if platform.system() != 'Windows' else socket.AF_INET, socket.SOCK_STREAM)
                if platform.system() == 'Windows':
                    sock.connect(('127.0.0.1', 9876))
                else:
                    sock.connect(str(SOCKET_PATH))
                sock.sendall(json.dumps({'action': 'stop'}).encode('utf-8') + b'\n')
                sock.close()
                print("[Client] 已发送停止命令")
            except Exception as e:
                print(f"[Client] 发送停止命令失败: {e}")
        else:
            print("[Client] Daemon 未运行")
    elif args.action == 'status':
        if daemon._is_running():
            print("[Client] Daemon 正在运行")
        else:
            print("[Client] Daemon 未运行")


if __name__ == '__main__':
    main()
