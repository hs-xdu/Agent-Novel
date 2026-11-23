import os
import socket

APP_ID = 'novel-agent'
APP_NAME = '拾光 · 小说写作助手'
DEFAULT_PORT = 18765


def preview_port() -> int:
    try:
        port = int(os.getenv('NOVEL_PORT', str(DEFAULT_PORT)))
    except ValueError as exc:
        raise ValueError('NOVEL_PORT 必须是整数端口号') from exc
    if not 1 <= port <= 65535:
        raise ValueError('NOVEL_PORT 必须在 1 到 65535 之间')
    return port


def ensure_available(port: int):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise ValueError(f'写作应用端口 {port} 已被占用，请修改 NOVEL_PORT；该地址可能是其他项目。') from exc
