import sys
import os
import traceback
from datetime import datetime
from pathlib import Path

def main():
    sys.excepthook = report_exception
    from PySide6.QtWidgets import QApplication
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from app.packaging_smoke import run
        return run(Path(sys.argv[2]))
    from app.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    return app.exec()


def report_exception(exc_type, exc_value, exc_traceback):
    message = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'MowerAnnotator' / 'logs'
    try:
        base.mkdir(parents=True, exist_ok=True)
        log = base / ('error-' + datetime.now().strftime('%Y%m%d') + '.log')
        with log.open('a', encoding='utf-8') as stream:
            stream.write(message + '\n')
        detail = f'详情已写入：{log}'
    except OSError:
        detail = '诊断日志写入失败，请检查用户目录权限。'
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app:
            QMessageBox.critical(None, '标注工具异常', f'{exc_value}\n\n{detail}')
            return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f'{exc_value}\n\n{detail}', '标注工具启动失败', 0x10)
    except Exception:
        sys.__stderr__.write(message)


if __name__ == '__main__':
    raise SystemExit(main())
