if __name__ == '__main__':
    try:
        from app.desktop import main
        main()
    except Exception:
        import sys
        import traceback
        from pathlib import Path
        root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        (root / 'logs').mkdir(exist_ok=True)
        (root / 'logs' / 'desktop-bootstrap.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
