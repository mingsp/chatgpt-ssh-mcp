import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


JOBS = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'chatgpt-ssh-mcp/jobs'
IMAGE_LIMIT = 2 * 1024 * 1024
LOG_LIMIT = 32 * 1024


def status(job):
    log = job / 'output.log'
    if log.exists():
        with log.open('rb') as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - LOG_LIMIT))
            output = stream.read(LOG_LIMIT).decode('utf-8', errors='replace')
    else:
        size, output = 0, ''
    result = {'job_id': job.name, 'output': output, 'truncated': size > LOG_LIMIT}
    if (job / 'exit').exists():
        return {**result, 'state': 'finished', 'exit_code': int((job / 'exit').read_text())}
    try:
        pid = int((job / 'pid').read_text())
        arguments = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        running = len(arguments) > 2 and arguments[-2] == job.name.encode('ascii')
    except FileNotFoundError:
        if not (job / 'pid').exists() and time.time() - job.stat().st_mtime < 45:
            running = True
        else:
            running = False
    except ProcessLookupError:
        running = False
    return {**result, 'state': 'running' if running else 'interrupted'}


def worker(job):
    payload = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    env = os.environ.copy()
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '/usr/local/bin:/usr/bin:/bin')
    with (job / 'output.log').open('ab') as log:
        try:
            result = subprocess.run(
                ['/bin/bash', '-c', payload['command']], cwd=payload['cwd'], env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
            exit_code = result.returncode
        except OSError as error:
            log.write(f'{error}\n'.encode())
            exit_code = 126
    (job / 'exit.tmp').write_text(str(exit_code), encoding='ascii')
    (job / 'exit.tmp').replace(job / 'exit')


def dispatch(payload):
    operation = payload['operation']
    if operation == 'check':
        return 'SSH_OK'
    if operation == 'run':
        if not payload['command'].strip():
            raise ValueError('Provide a shell command.')
        cwd = Path(payload['cwd']).expanduser()
        if not cwd.is_dir():
            raise ValueError(f'Working directory does not exist: {cwd}')
        wait = max(0, min(45, int(payload['wait_seconds'])))
        JOBS.mkdir(mode=0o700, parents=True, exist_ok=True)
        job = job_path(payload['job_id'])
        try:
            job.mkdir(mode=0o700)
        except FileExistsError:
            return status(job)
        (job / 'request.json').write_text(json.dumps({**payload, 'cwd': str(cwd)}), encoding='utf-8')
        with (job / 'output.log').open('wb') as log:
            process = subprocess.Popen(
                [sys.executable, '-I', __file__, '--job', job.name],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (job / 'pid').write_text(str(process.pid), encoding='ascii')
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
        return status(job)
    if operation == 'status':
        return status(job_path(payload['job_id']))
    if operation == 'image':
        path = Path(payload['path']).expanduser()
        if not path.is_file():
            raise ValueError('Expected a regular image file.')
        with path.open('rb') as stream:
            data = stream.read(IMAGE_LIMIT + 1)
        if len(data) > IMAGE_LIMIT:
            raise ValueError('Image exceeds 2 MiB. Generate a smaller preview first.')
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            kind = 'png'
        elif data.startswith(b'\xff\xd8\xff'):
            kind = 'jpeg'
        else:
            raise ValueError('Expected a PNG or JPEG image.')
        return {'format': kind, 'data': base64.b64encode(data).decode('ascii')}
    raise ValueError('Unknown operation.')


def job_path(job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Invalid job ID.')
    return JOBS / job_id


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == '--job':
        worker(job_path(sys.argv[2]))
        return
    try:
        reply = {'result': dispatch(json.loads(sys.stdin.buffer.read(2 * 1024 * 1024)))}
    except (KeyError, OSError, ValueError) as error:
        reply = {'error': str(error)}
    print(json.dumps(reply, ensure_ascii=True))


if __name__ == '__main__':
    main()
