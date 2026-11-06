# ChatGPT SSH MCP

在 ChatGPT 网页里用自然语言操作自己的 Linux 服务器。本机通过 OpenSSH 执行命令，OpenAI 的安全隧道负责连接网页和本机。SSH 用户、地址、端口、密钥位置和跳板机沿用 OpenSSH 配置。

```text
ChatGPT 网页 → OpenAI 安全隧道 → 本机 SSH → Linux 服务器
```

| 网页工具 | 用途 |
| --- | --- |
| `check_ssh_connection` | 验证 SSH 和远端脚本能否运行 |
| `run_ssh_command` | 执行单条命令或多行 Bash 脚本，指定工作目录 |
| `get_ssh_job` | 查看长任务状态、退出码和最近 32 KiB 日志 |
| `get_ssh_image` | 取回不超过 2 MiB 的远端 PNG 或 JPEG |

命令拥有 SSH 登录账号的权限，能读写文件、安装账号可用的软件、运行实验和删除数据。请把插件留在自己的受信工作区，默认使用普通 SSH 账号。仅在受信的私有隧道中按下面的方式添加插件。 [OpenAI 隧道访问范围](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access)

## 1. 配置 SSH

本机需要 OpenSSH、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和官方 [tunnel-client](https://github.com/openai/tunnel-client/releases/latest)。下面使用 PowerShell 7。远端需要 Linux、Bash 和 Python 3.9 或更新版本。

```powershell
git clone https://github.com/mingsp/chatgpt-ssh-mcp.git
cd chatgpt-ssh-mcp
```

把 [示例 SSH 配置](examples/ssh_config)里的条目加到本机 `~/.ssh/config`。按服务器实际情况填写 `HostName`、`User`、`Port` 和 `IdentityFile`。使用密钥登录，必要时先把有密码短语的密钥加载到 `ssh-agent`。

```powershell
ssh research-box
# 核对服务器指纹后登录，完成后退出，再验证非交互登录。
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes research-box 'id -un; command -v bash; python3 --version'
```

## 2. 安装远端脚本

```powershell
ssh research-box 'umask 077 && mkdir -p .local/share/chatgpt-ssh-mcp'
scp ./remote_runner.py research-box:.local/share/chatgpt-ssh-mcp/remote_runner.py
uv run --script ./ssh_mcp.py --host research-box --check
```

最后一条命令应返回 `SSH_OK`。服务器的 Python 如果装在 Conda 等环境中，可以在命令后加 `--remote-python /opt/conda/bin/python`。后面注册隧道时也要带上相同的参数。

| 参数 | 说明 |
| --- | --- |
| `--host` | SSH 主机别名或主机名，必填 |
| `--ssh-config` | 可选的本机 OpenSSH 配置文件路径。省略时使用默认配置 |
| `--remote-python` | 远端 Python 命令或绝对路径，默认 `python3` |
| `--remote-runner` | 远端脚本的绝对路径或相对登录目录的路径 |
| `--default-cwd` | 默认远端工作目录，省略时使用登录用户的家目录 |

## 3. 启动 OpenAI 安全隧道

1. 在 [OpenAI 隧道管理页](https://platform.openai.com/settings/organization/tunnels) 创建隧道，关联要使用插件的 ChatGPT 工作区。
2. 在 [API 密钥页](https://platform.openai.com/settings/organization/api-keys) 创建该组织的受限运行密钥，启用 **Tunnels → Read + Use**。
3. 把 `tunnel-client` 放到本机 `PATH`，或在下列命令中使用它的实际路径。按提示输入隧道编号。

```powershell
$tunnelId = Read-Host 'Tunnel ID'
$uvPath = (Get-Command uv -CommandType Application).Source.Replace('\', '/')
$bridgePath = (Resolve-Path ./ssh_mcp.py).Path.Replace('\', '/')
$bridgeCommand = '"{0}" run --script "{1}" --host research-box' -f $uvPath, $bridgePath
tunnel-client init --sample sample_mcp_stdio_local --profile chatgpt-ssh-mcp --tunnel-id $tunnelId --mcp-command $bridgeCommand
pwsh -File ./Start-Tunnel.ps1
```

启动时在 PowerShell 的隐藏输入提示处粘贴运行密钥。保持窗口运行。可以在另一终端访问 `http://127.0.0.1:18743/readyz`，正常时会返回 `ready`。端口被占用时，用 `-HealthPort` 选择另一个本机端口。 [OpenAI 安全隧道说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

在 macOS 或 Linux 上，用同一条 `tunnel-client init` 命令注册本机的 `uv` 和脚本绝对路径。通过本机密钥管理工具将运行密钥传入 `CONTROL_PLANE_API_KEY` 环境变量，再运行 `tunnel-client run --profile chatgpt-ssh-mcp`。

## 4. 在 ChatGPT 网页添加插件

1. 打开 [ChatGPT 插件](https://chatgpt.com/plugins)，点 **添加 → 添加自定义 MCP 服务器**。
2. 名称填 `SSH Bridge`，连接方式选 **隧道**，选择刚创建的隧道。此脚本没有单独的登录页面。仅在工作区和隧道都限制为受信用户的前提下，选择 **无需身份验证**。
3. 创建并安装。新开网页聊天，输入 `@` 选中 `SSH Bridge`，发送「用 SSH Bridge 检查连接，把工具结果原样返回」。成功结果为 `SSH_OK`。 [自定义插件官方说明](https://developers.openai.com/api/docs/guides/custom-mcp-server)

下一步可以让它执行 `pwd; id -un`，或者让它自行编写脚本生成 PNG，再取回图片。ChatGPT 可能会请你确认命令执行。更新工具后，在插件详情页刷新工具列表。

## 排查

- **隧道找不到**。核对隧道是否关联当前 ChatGPT 工作区，以及账号是否有使用权限。
- **本机检查失败**。先跑第一步的非交互 SSH 命令，再核对远端 Python 和脚本路径。
- **任务还在运行**。用返回的任务编号继续查日志。关闭网页不影响已启动的远端任务，后续查询需要本机隧道在线。
- **日志太长**。让 ChatGPT 用远端命令读具体文件或提取关键行。工具只返回日志末尾，完整日志存在远端用户的状态目录，默认 `~/.local/state/chatgpt-ssh-mcp/jobs/`。命令参数和日志可能包含敏感信息。

项目代码使用 [MIT 许可证](LICENSE)。
