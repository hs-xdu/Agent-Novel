STYLE = '''
QMainWindow, QDialog { background: #f3f5f7; color: #243446; }
QListWidget { background: white; border: 1px solid #d6dfe7; border-radius: 6px; outline: none; }
QListWidget::item { padding: 10px 8px; border-radius: 4px; }
QListWidget::item:selected { background: #e1f0ed; color: #164b43; }
QTabBar::tab { padding: 8px 14px; background: #edf2f4; color: #526577; border: none; }
QTabBar::tab:selected { background: white; color: #21665f; border-bottom: 2px solid #28776e; }
QLabel { color: #33465a; background: transparent; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #163f45; }
QLabel#pageTitle { font-size: 23px; font-weight: 600; color: #1c3045; }
QLabel#muted { color: #64748b; font-size: 12px; }
QListWidget#navigation { background: #163b42; color: #bed1d5; border: none; border-radius: 12px; padding: 12px 6px; outline: none; }
QListWidget#navigation::item { padding: 16px 14px; border-radius: 8px; margin: 4px 2px; }
QListWidget#navigation::item:selected { background: #28565d; color: white; font-weight: 600; }
QListWidget#navigation::item:hover { background: #234a52; }
QFrame#panel, QTabWidget::pane { background: white; border: 1px solid #e1e6ed; border-radius: 10px; }
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox { background: white; color: #25364a; border: 1px solid #d6dfe7; border-radius: 6px; padding: 8px; selection-background-color: #d4e9e5; selection-color: #163b42; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #438d86; }
QPlainTextEdit { font-size: 14px; padding: 14px; }
QPlainTextEdit[readOnly="true"] { background: #f8fafb; color: #64748b; }
QPushButton { background: white; color: #34465a; border: 1px solid #d6dfe7; border-radius: 6px; padding: 9px 16px; min-height: 18px; }
QPushButton:hover { background: #edf5f3; border-color: #79a69e; }
QPushButton[primary="true"] { background: #28776e; color: white; border: 1px solid #28776e; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #21665f; }
QPushButton:disabled { color: #9ba8b4; background: #e9eef2; border-color: #e1e6ed; }
QGroupBox { border: 1px solid #e1e6ed; border-radius: 7px; margin-top: 12px; padding-top: 14px; font-weight: 500; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QSplitter::handle { background: transparent; width: 14px; height: 14px; }
QStatusBar { background: #e9eff1; color: #627484; border-top: 1px solid #dde5e9; padding: 5px; }
'''
