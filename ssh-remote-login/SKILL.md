---
name: "ssh-remote-login"
description: "Use AI SSH Daemon tool to connect to remote computers and execute commands. Invoke when user needs to SSH login to remote server, execute remote commands, or manage SSH sessions through the ai-ssh-daemon tool."
---

# SSH Remote Login Skill

This skill guides AI to use the ai-ssh-daemon tool for SSH remote operations.

## Prerequisites

The ai-ssh-daemon tool must be installed and available:
- Repository: https://github.com/kukucaiCndy/ai-ssh-daemon
- Requires: Python 3.7+, paramiko, keyring

## Workflow

### 1. Check Daemon Status

First, check if the daemon is running:
```bash
python ssh_client.py daemon status
```

If not running, start it:
```bash
python ssh_daemon_server.py start
```

### 2. Create Session (One-time Setup)

Create a session for the remote host:
```bash
python ssh_client.py session create <session_name> --host <hostname> --user <username> [--port 22]
```

Example:
```bash
python ssh_client.py session create mac --host 192.168.16.131 --user kukucai
```

The tool will prompt for password and save it securely to system keyring.

### 3. Connect Session

Establish long-lived connection:
```bash
python ssh_client.py connect <session_name>
```

Example:
```bash
python ssh_client.py connect mac
```

### 4. Execute Commands

Execute commands using the persistent connection:
```bash
python ssh_client.py exec --session <session_name> "<command>"
```

Example:
```bash
python ssh_client.py exec --session mac "whoami && pwd"
python ssh_client.py exec --session mac "ls -la"
python ssh_client.py exec --session mac "docker ps"
```

### 5. Check Status

View all sessions and their connection status:
```bash
python ssh_client.py status
```

### 6. Cleanup

When done, disconnect and stop daemon:
```bash
python ssh_client.py disconnect <session_name>
python ssh_client.py daemon stop
```

## Common Commands Reference

| Task | Command |
|------|---------|
| Start daemon | `python ssh_daemon_server.py start` |
| Stop daemon | `python ssh_client.py daemon stop` |
| Create session | `python ssh_client.py session create <name> --host <host> --user <user>` |
| Delete session | `python ssh_client.py session delete <name>` |
| List sessions | `python ssh_client.py session list` |
| Connect | `python ssh_client.py connect <name>` |
| Disconnect | `python ssh_client.py disconnect <name>` |
| Execute command | `python ssh_client.py exec --session <name> "<cmd>"` |
| View status | `python ssh_client.py status` |

## Best Practices

1. **Always check daemon status** before operations
2. **Create session once**, reuse for multiple commands
3. **Connect once**, execute multiple commands without re-authentication
4. **Use meaningful session names** (e.g., "mac", "ubuntu-server", "prod-web")
5. **Stop daemon when done** to release resources

## Troubleshooting

### Daemon not responding
```bash
# Check if daemon is running
python ssh_client.py daemon status

# Restart if needed
python ssh_client.py daemon stop
python ssh_daemon_server.py start
```

### Connection failed
```bash
# Reconnect session
python ssh_client.py disconnect <session_name>
python ssh_client.py connect <session_name>
```

### Password issues
```bash
# Delete and recreate session
python ssh_client.py session delete <session_name>
python ssh_client.py session create <session_name> --host <host> --user <user>
```

## Example: Complete Workflow

```bash
# 1. Start daemon
python ssh_daemon_server.py start

# 2. Create session (one-time)
python ssh_client.py session create myserver --host 192.168.1.100 --user admin

# 3. Connect
python ssh_client.py connect myserver

# 4. Execute multiple commands (same connection)
python ssh_client.py exec --session myserver "whoami"
python ssh_client.py exec --session myserver "df -h"
python ssh_client.py exec --session myserver "docker ps"
python ssh_client.py exec --session myserver "cat /var/log/syslog | tail -20"

# 5. Check status
python ssh_client.py status

# 6. Cleanup
python ssh_client.py disconnect myserver
python ssh_client.py daemon stop
```

## Notes

- Passwords are stored securely in system keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service)
- Connections remain active until manually disconnected or daemon stopped
- Multiple sessions can be active simultaneously
- Each session maintains its own independent SSH connection
