"""跨 CMD / PowerShell 初始化配置，保留已有的非空配置。"""
from pathlib import Path


def initialize_env(root: Path) -> bool:
    destination = root / '.env'
    template = root / '.env.example'
    if destination.exists() and destination.stat().st_size > 0:
        return False
    content = template.read_bytes()
    if not content.strip():
        raise ValueError('配置模板为空，未修改 .env')
    if destination.exists():
        # 重新打开后检查，避免覆盖初始化期间已写入的内容。
        with destination.open('r+b') as handle:
            if handle.read(1):
                return False
            handle.write(content)
    else:
        try:
            with destination.open('xb') as handle:
                handle.write(content)
        except FileExistsError:
            return False
    return True


if __name__ == '__main__':
    changed = initialize_env(Path(__file__).resolve().parents[1])
    print('Created .env from template. Fill in API key and model locally.' if changed
          else 'Existing non-empty .env preserved.')
