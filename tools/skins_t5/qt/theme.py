from PyQt5.QtGui import QColor, QFont, QPalette

BG = '#1e1e20'
PANEL = '#252527'
RAISED = '#2d2d30'
BORDER = '#3c3c40'
TEXT = '#d6d6d6'
MUTED = '#8c8c92'
ACCENT = '#3d8ee6'
SELECT = '#264f78'

STYLE = f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-family: 'Segoe UI'; font-size: 9pt; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {RAISED}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 2px; }}
QMenu::item {{ padding: 4px 26px 4px 22px; }}
QMenu::item:selected {{ background: {SELECT}; }}
QMenu::item:disabled {{ color: #5d5d62; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 3px 6px; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; spacing: 2px; padding: 2px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; padding: 3px 8px; }}
QToolButton:hover {{ background: {RAISED}; border-color: {BORDER}; }}
QToolButton:checked {{ background: {SELECT}; border-color: {ACCENT}; }}
QStatusBar {{ background: {ACCENT}; color: white; }}
QStatusBar QLabel {{ color: white; padding: 0 6px; }}
QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; top: -1px; background: {PANEL}; }}
QTabBar::tab {{ background: {BG}; color: {MUTED}; border: 1px solid {BORDER}; border-bottom: none;
               padding: 5px 14px; margin-right: 1px; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; border-top: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QTabBar::tab:disabled {{ color: #55555a; background: #1e1e20; }}
QTreeView, QListView, QTableView, QPlainTextEdit, QTextEdit {{
    background: {PANEL}; alternate-background-color: #29292b; border: 1px solid {BORDER};
    selection-background-color: {SELECT}; selection-color: white; }}
QTreeView::item, QListView::item {{ padding: 2px 0; }}
QTreeView::item:hover, QListView::item:hover {{ background: #2f2f33; }}
QTreeView::item:selected, QListView::item:selected {{ background: {SELECT}; }}
QHeaderView::section {{ background: {RAISED}; color: {MUTED}; border: none; border-right: 1px solid {BORDER};
                        border-bottom: 1px solid {BORDER}; padding: 3px 6px; }}
QLineEdit, QSpinBox, QComboBox {{ background: {BG}; border: 1px solid {BORDER}; padding: 3px 5px;
                                  selection-background-color: {SELECT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER}; selection-background-color: {SELECT}; }}
QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; padding: 4px 14px; min-height: 18px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {SELECT}; }}
QPushButton:default {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton:disabled {{ color: #5d5d62; border-color: #333336; }}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QGroupBox {{ border: 1px solid {BORDER}; margin-top: 10px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {MUTED}; }}
QScrollBar:vertical {{ background: {BG}; width: 11px; margin: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 11px; margin: 0; }}
QScrollBar::handle {{ background: #47474c; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #5a5a60; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QProgressBar {{ background: #2a6fbf; border: none; color: white; text-align: center; max-height: 14px; }}
QProgressBar::chunk {{ background: #9cc7f5; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 3px; }}
QLabel#PathLabel {{ color: {MUTED}; padding: 4px 6px; background: {PANEL}; border: 1px solid {BORDER}; border-bottom: none; }}
QLabel#Hint {{ color: {MUTED}; }}
"""


def apply(app):
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, PANEL),
                        (QPalette.AlternateBase, '#29292b'), (QPalette.Text, TEXT), (QPalette.Button, RAISED),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, SELECT), (QPalette.HighlightedText, '#ffffff'),
                        (QPalette.ToolTipBase, RAISED), (QPalette.ToolTipText, TEXT), (QPalette.Link, ACCENT)):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor('#5d5d62'))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor('#5d5d62'))
    app.setPalette(palette)
    app.setFont(QFont('Segoe UI', 9))
    app.setStyleSheet(STYLE)
