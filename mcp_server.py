#!/usr/bin/env python3
"""
MCP (Model Context Protocol) 服务接口
为 AI 提供 SSH 操作能力
"""

import json
import sys
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# 导入 SSH Daemon 客户端
from ssh_daemon import send_command, SSHConfig


class SSHMCPService:
    """MCP 服务 - 为 AI 提供 SSH 操作接口"""
    
    def __init__(self):
        self.name = "ssh-service"
        self.version = "1.0.0"
    
    def handle_request(self, request: Dict) -> Dict:
        """处理 MCP 请求"""
        method = request.get('method', '')
        params = request.get('params', {})
        
        handlers = {
            'initialize': self._handle_initialize,
            'tools/list': self._handle_list_tools,
            'tools/call': self._handle_call_tool,
            'connections/list': self._handle_list_connections,
            'connections/status': self._handle_connection_status,
            'execute': self._handle_execute,
            'execute_all': self._handle_execute_all,
            'upload': self._handle_upload,
            'download': self._handle_download,
        }
        
        handler = handlers.get(method, self._handle_unknown)
        return handler(params)
    
    def _handle_initialize(self, params: Dict) -> Dict:
        """初始化服务"""
        return {
            'status': 'success',
            'service': self.name,
            'version': self.version,
            'capabilities': {
                'tools': True,
                'multiple_connections': True,
                'file_transfer': True,
            }
        }
    
    def _handle_list_tools(self, params: Dict) -> Dict:
        """列出可用工具"""
        tools = [
            {
                'name': 'ssh_execute',
                'description': '在远程服务器上执行命令',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'connection': {
                            'type': 'string',
                            'description': '连接名称，默认为 default'
                        },
                        'command': {
                            'type': 'string',
                            'description': '要执行的命令'
                        },
                        'timeout': {
                            'type': 'integer',
                            'description': '超时时间（秒），默认60'
                        }
                    },
                    'required': ['command']
                }
            },
            {
                'name': 'ssh_execute_all',
                'description': '在所有连接上执行命令',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {
                            'type': 'string',
                            'description': '要执行的命令'
                        },
                        'timeout': {
                            'type': 'integer',
                            'description': '超时时间（秒），默认60'
                        }
                    },
                    'required': ['command']
                }
            },
            {
                'name': 'ssh_status',
                'description': '获取 SSH 连接状态',
                'parameters': {
                    'type': 'object',
                    'properties': {}
                }
            },
            {
                'name': 'ssh_list_connections',
                'description': '列出所有 SSH 连接',
                'parameters': {
                    'type': 'object',
                    'properties': {}
                }
            },
            {
                'name': 'ssh_add_connection',
                'description': '添加新的 SSH 连接',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'name': {
                            'type': 'string',
                            'description': '连接名称'
                        },
                        'host': {
                            'type': 'string',
                            'description': '主机地址'
                        },
                        'port': {
                            'type': 'integer',
                            'description': '端口，默认22'
                        },
                        'username': {
                            'type': 'string',
                            'description': '用户名'
                        },
                        'password': {
                            'type': 'string',
                            'description': '密码（可选）'
                        },
                        'key_file': {
                            'type': 'string',
                            'description': '私钥文件路径（可选）'
                        }
                    },
                    'required': ['name', 'host', 'username']
                }
            },
            {
                'name': 'ssh_remove_connection',
                'description': '移除 SSH 连接',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'name': {
                            'type': 'string',
                            'description': '连接名称'
                        }
                    },
                    'required': ['name']
                }
            }
        ]
        
        return {
            'status': 'success',
            'tools': tools
        }
    
    def _handle_call_tool(self, params: Dict) -> Dict:
        """调用工具"""
        tool_name = params.get('name', '')
        tool_params = params.get('parameters', {})
        
        if tool_name == 'ssh_execute':
            return self._execute_command(
                tool_params.get('connection', 'default'),
                tool_params.get('command', ''),
                tool_params.get('timeout', 60)
            )
        elif tool_name == 'ssh_execute_all':
            return self._execute_all(
                tool_params.get('command', ''),
                tool_params.get('timeout', 60)
            )
        elif tool_name == 'ssh_status':
            return self._get_status()
        elif tool_name == 'ssh_list_connections':
            return self._list_connections()
        elif tool_name == 'ssh_add_connection':
            return self._add_connection(tool_params)
        elif tool_name == 'ssh_remove_connection':
            return self._remove_connection(tool_params.get('name', ''))
        else:
            return {
                'status': 'error',
                'message': f'未知工具: {tool_name}'
            }
    
    def _execute_command(self, connection: str, command: str, timeout: int) -> Dict:
        """执行命令"""
        response = send_command({
            'action': 'execute',
            'connection': connection,
            'command': command,
            'timeout': timeout
        })
        
        if response['status'] == 'success':
            result = response['result']
            return {
                'status': 'success',
                'content': [
                    {
                        'type': 'text',
                        'text': f"命令: {result['command']}\n"
                                f"退出码: {result['exit_code']}\n"
                                f"执行时间: {result['execution_time']:.2f}秒\n\n"
                                f"输出:\n{result['stdout']}"
                    }
                ],
                'isError': result['exit_code'] != 0
            }
        else:
            return {
                'status': 'error',
                'content': [
                    {
                        'type': 'text',
                        'text': f"执行失败: {response.get('message', 'Unknown error')}"
                    }
                ],
                'isError': True
            }
    
    def _execute_all(self, command: str, timeout: int) -> Dict:
        """在所有连接上执行命令"""
        # 先获取所有连接
        list_response = send_command({'action': 'list'})
        if list_response['status'] != 'success':
            return {
                'status': 'error',
                'message': list_response.get('message', 'Failed to list connections')
            }
        
        connections = list_response.get('connections', [])
        results = []
        
        for conn_name in connections:
            response = send_command({
                'action': 'execute',
                'connection': conn_name,
                'command': command,
                'timeout': timeout
            })
            
            if response['status'] == 'success':
                result = response['result']
                results.append({
                    'connection': conn_name,
                    'exit_code': result['exit_code'],
                    'stdout': result['stdout'],
                    'stderr': result['stderr']
                })
            else:
                results.append({
                    'connection': conn_name,
                    'error': response.get('message', 'Unknown error')
                })
        
        return {
            'status': 'success',
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps(results, indent=2)
                }
            ]
        }
    
    def _get_status(self) -> Dict:
        """获取状态"""
        response = send_command({'action': 'status'})
        
        if response['status'] == 'success':
            connections = response['connections']
            text = "SSH 连接状态:\n\n"
            
            for name, status in connections.items():
                text += f"[{name}]\n"
                text += f"  主机: {status['host']}:{status['port']}\n"
                text += f"  用户: {status['username']}\n"
                text += f"  状态: {'✓ 已连接' if status['is_connected'] else '✗ 未连接'}\n"
                text += f"  空闲: {status['idle_time']:.1f}秒\n"
                text += f"  历史命令: {status['command_count']}\n\n"
            
            return {
                'status': 'success',
                'content': [
                    {
                        'type': 'text',
                        'text': text
                    }
                ]
            }
        else:
            return {
                'status': 'error',
                'message': response.get('message', 'Failed to get status')
            }
    
    def _list_connections(self) -> Dict:
        """列出连接"""
        response = send_command({'action': 'list'})
        
        if response['status'] == 'success':
            connections = response['connections']
            return {
                'status': 'success',
                'content': [
                    {
                        'type': 'text',
                        'text': f"共有 {len(connections)} 个连接:\n" + 
                               "\n".join([f"  - {name}" for name in connections])
                    }
                ]
            }
        else:
            return {
                'status': 'error',
                'message': response.get('message', 'Failed to list connections')
            }
    
    def _add_connection(self, params: Dict) -> Dict:
        """添加连接"""
        config = {
            'name': params.get('name'),
            'host': params.get('host'),
            'port': params.get('port', 22),
            'username': params.get('username'),
            'password': params.get('password'),
            'key_file': params.get('key_file')
        }
        
        response = send_command({
            'action': 'add',
            'config': config
        })
        
        if response['status'] == 'success':
            return {
                'status': 'success',
                'content': [
                    {
                        'type': 'text',
                        'text': f"连接已添加: {response['name']}"
                    }
                ]
            }
        else:
            return {
                'status': 'error',
                'message': response.get('message', 'Failed to add connection')
            }
    
    def _remove_connection(self, name: str) -> Dict:
        """移除连接"""
        response = send_command({
            'action': 'remove',
            'name': name
        })
        
        if response['status'] == 'success':
            return {
                'status': 'success',
                'content': [
                    {
                        'type': 'text',
                        'text': f"连接已移除: {name}"
                    }
                ]
            }
        else:
            return {
                'status': 'error',
                'message': response.get('message', 'Failed to remove connection')
            }
    
    def _handle_list_connections(self, params: Dict) -> Dict:
        """处理列出连接请求"""
        return self._list_connections()
    
    def _handle_connection_status(self, params: Dict) -> Dict:
        """处理连接状态请求"""
        return self._get_status()
    
    def _handle_execute(self, params: Dict) -> Dict:
        """处理执行请求"""
        return self._execute_command(
            params.get('connection', 'default'),
            params.get('command', ''),
            params.get('timeout', 60)
        )
    
    def _handle_execute_all(self, params: Dict) -> Dict:
        """处理在所有连接上执行请求"""
        return self._execute_all(
            params.get('command', ''),
            params.get('timeout', 60)
        )
    
    def _handle_upload(self, params: Dict) -> Dict:
        """处理文件上传"""
        # TODO: 实现文件上传
        return {
            'status': 'error',
            'message': 'File upload not implemented yet'
        }
    
    def _handle_download(self, params: Dict) -> Dict:
        """处理文件下载"""
        # TODO: 实现文件下载
        return {
            'status': 'error',
            'message': 'File download not implemented yet'
        }
    
    def _handle_unknown(self, params: Dict) -> Dict:
        """处理未知请求"""
        return {
            'status': 'error',
            'message': 'Unknown method'
        }


def main():
    """MCP 服务主入口"""
    service = SSHMCPService()
    
    print("SSH MCP Service started", file=sys.stderr)
    
    while True:
        try:
            # 读取请求
            line = input()
            if not line:
                continue
            
            request = json.loads(line)
            response = service.handle_request(request)
            
            # 输出响应
            print(json.dumps(response), flush=True)
            
        except json.JSONDecodeError as e:
            print(json.dumps({
                'status': 'error',
                'message': f'Invalid JSON: {e}'
            }), flush=True)
        except EOFError:
            break
        except Exception as e:
            print(json.dumps({
                'status': 'error',
                'message': str(e)
            }), flush=True)


if __name__ == '__main__':
    main()
