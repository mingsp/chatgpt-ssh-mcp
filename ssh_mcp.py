# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.28,<2"]
# ///

import argparse
import base64
import json
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations


def ssh_command(settings):
    executable = shutil.which("ssh")
    if not executable:
        raise RuntimeError("Install OpenSSH and make ssh available on PATH.")
    if settings.host.startswith("-") or any(char.isspace() for char in settings.host):
        raise ValueError("Use an OpenSSH host alias or a hostname.")
    command = [executable, "-T"]
    if settings.ssh_config:
        command += ["-F", str(settings.ssh_config.expanduser().resolve(strict=True))]
    command += [
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ForwardAgent=no",
        "-o", "ForwardX11=no",
        "-o", "ClearAllForwardings=yes",
        settings.host,
        shlex.join([settings.remote_python, "-I", settings.remote_runner]),
    ]
    return command


def make_request(ssh_args, operation, **values):
    payload = json.dumps({"operation": operation, **values})
    retries = 1 if operation == "run" else 2
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                ssh_args, input=payload, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=56 if operation == "run" else 20,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("The SSH request timed out.") from error
        if result.returncode != 255 or attempt == retries:
            break
        time.sleep(1)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"SSH exited with code {result.returncode}.")
    try:
        reply = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("The remote runner did not return JSON. Check its path and SSH login output.") from error
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply["result"]


def make_server(ssh_args, default_cwd):
    server = FastMCP(
        "SSH Bridge",
        instructions="Use run_ssh_command to run Bash commands on the configured Linux host. "
        "Choose a remote working directory when needed. Jobs that outlast the initial wait "
        "keep running remotely. Use get_ssh_job to read their output and get_ssh_image "
        "to retrieve saved PNG or JPEG images.",
    )
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
    command_action = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

    @server.tool(annotations=read_only)
    def check_ssh_connection() -> str:
        """Verify that the configured SSH host can run the remote helper."""
        return make_request(ssh_args, "check")

    @server.tool(annotations=command_action)
    def run_ssh_command(command: str, cwd: str | None = None, wait_seconds: int = 15) -> dict:
        """Run a Bash command or multiline script on the remote host.

        Commands run as the configured SSH user. The default directory is the remote
        home or the configured default. Up to 45 seconds can be spent waiting for output.
        Use get_ssh_job with the returned ID if the command is still running.
        """
        job_id = uuid.uuid4().hex
        try:
            return make_request(
                ssh_args, "run", command=command, cwd=cwd or default_cwd,
                wait_seconds=wait_seconds, job_id=job_id,
            )
        except RuntimeError as error:
            raise RuntimeError(f"{error} Check job {job_id} before submitting again.") from error

    @server.tool(annotations=read_only)
    def get_ssh_job(job_id: str) -> dict:
        """Return the remote job state, exit code if finished, and the last 32 KiB of output."""
        return make_request(ssh_args, "status", job_id=job_id)

    @server.tool(annotations=read_only)
    def get_ssh_image(path: str) -> Image:
        """Return a PNG or JPEG from the remote host, up to 2 MiB. Use a remote absolute path."""
        result = make_request(ssh_args, "image", path=path)
        return Image(data=base64.b64decode(result["data"], validate=True), format=result["format"])

    return server


def main():
    parser = argparse.ArgumentParser(description="Serve SSH tools over MCP stdio.")
    parser.add_argument("--host", required=True, help="OpenSSH Host alias or hostname")
    parser.add_argument("--ssh-config", type=Path, help="Optional local OpenSSH config file")
    parser.add_argument("--remote-python", default="python3", help="Remote Python command or absolute path")
    parser.add_argument("--remote-runner", default=".local/share/chatgpt-ssh-mcp/remote_runner.py")
    parser.add_argument("--default-cwd", default="~", help="Default remote working directory")
    parser.add_argument("--check", action="store_true", help="Check SSH and exit instead of serving MCP")
    settings = parser.parse_args()
    try:
        command = ssh_command(settings)
        if settings.check:
            print(make_request(command, "check"))
            return
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    make_server(command, settings.default_cwd).run(transport="stdio")


if __name__ == "__main__":
    main()
