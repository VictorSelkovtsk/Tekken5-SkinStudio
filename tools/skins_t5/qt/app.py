from __future__ import annotations

import datetime
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt5.QtCore import (QLibraryInfo, QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, QTranslator,
                          pyqtSignal)
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                             QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                             QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSlider, QStyle,
                             QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import i18n, original
from ..i18n import _t, tr
from ..studio import Studio
from . import theme
from .viewport import Viewport, np_to_qimage

VERSION = '1.0.0'
AUTHOR = 'VictorSelkovtsk'
KINDS = (('t5', 'Tekken 5'), ('t4', 'Tekken 4'), ('taghd', 'Tag HD'), ('xps', 'XPS'))
VIEWS = ('Textura', 'Cores por osso', 'Peso de um osso', 'Física do jogo')


def home_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


class Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, Signals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:
            self.signals.failed.emit('%s\n\n%s' % (exc, traceback.format_exc()))
        else:
            self.signals.done.emit(result)


def bone_color(i):
    h = (i * 137.508) % 360 / 60
    s, l = .62, (.5 if i % 2 else .62)
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs(h % 2 - 1))
    m = l - c / 2
    r, g, b = ((c, x, 0) if h < 1 else (x, c, 0) if h < 2 else (0, c, x) if h < 3 else
               (0, x, c) if h < 4 else (x, 0, c) if h < 5 else (c, 0, x))
    return np.array([r + m, g + m, b + m], np.float32)


RAMP = np.array([[.05, .05, .35], [.12, .62, .84], [.18, .75, .29], [.9, .82, .23], [.88, .25, .16]], np.float32)


class SettingsDialog(QDialog):
    def __init__(self, window, first_run=False):
        super().__init__(window)
        self.window = window
        cfg = window.studio.config
        self.setWindowTitle(_t('Configuração inicial') if first_run else _t('Pastas e jogo'))
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        if first_run:
            intro = QLabel(_t('<b>Bem-vindo ao Tekken 5 Skin Studio.</b><br>Para começar, indique a sua ISO original do '
                              '<b>Tekken 5 de PS2 (USA 1.00, SLUS-21059)</b>. A ISO nunca é alterada: os mods vão para uma ISO nova.'))
            intro.setWordWrap(True)
            lay.addWidget(intro)
        row = QHBoxLayout()
        lbl = _t('Idioma')
        row.addWidget(QLabel(lbl if lbl == 'Language' else lbl + ' / Language'))
        self.lang = QComboBox()
        for code, name in i18n.languages().items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(i18n.language())))
        row.addWidget(self.lang)
        row.addStretch(1)
        lay.addLayout(row)
        grid = QGridLayout()
        self.fields = {}
        rows = (('iso', _t('ISO original do Tekken 5'), 'iso'), ('t4', _t('Exports do Tekken 4'), 'folder'),
                ('taghd', _t('Modelos .kmd do Tag Tournament HD PS3'), 'folder'),
                ('blender', _t('Blender 2.79 · executável'), 'exe'))
        for r, (key, label, kind) in enumerate(rows):
            edit = QLineEdit(str(cfg.get(key, '') or ''))
            if key == 'blender':
                edit.setPlaceholderText(_t('Automático: Blender 2.79 deste projeto'))
            button = QPushButton(_t('Procurar…'))
            button.clicked.connect(lambda _, e=edit, k=kind: self._browse(e, k))
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(edit, r, 1)
            grid.addWidget(button, r, 2)
            self.fields[key] = edit
        lay.addLayout(grid)
        note = QLabel(_t('Destino compatível: Tekken 5 PS2 USA · SLUS-21059 1.00.'))
        note.setObjectName('Hint')
        lay.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t('Salvar'))
        bb.button(QDialogButtonBox.Cancel).setText(_t('Cancelar'))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        credit = QLabel('Tekken 5 Skin Studio %s · %s · GPL-3.0' % (VERSION, AUTHOR))
        credit.setObjectName('Hint')
        lay.addWidget(credit)

    def _browse(self, edit, kind):
        start = edit.text() or ''
        if kind == 'folder':
            path = QFileDialog.getExistingDirectory(self, _t('Escolha a pasta'), start)
        elif kind == 'iso':
            path, _ = QFileDialog.getOpenFileName(self, _t('ISO original do Tekken 5'), start, 'ISO (*.iso)')
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Blender 2.79', start, 'blender.exe (blender.exe)')
        if path:
            edit.setText(os.path.normpath(path))

    def _ok(self):
        data = {k: e.text().strip() for k, e in self.fields.items()}
        try:
            self.window.studio.api('/api/config', data)
        except ValueError as error:
            self.status.setStyleSheet('color:#e0a050')
            self.status.setText(tr(str(error)))
            return
        self.new_lang = self.lang.currentData()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, studio: Studio):
        super().__init__()
        self.studio = studio
        self.setWindowTitle('Tekken 5 Skin Studio %s' % VERSION)
        self.resize(1500, 900)
        self.settings = QSettings('T5SkinStudio', 'desktop')
        self.pool = QThreadPool.globalInstance()
        self.state: dict = {}
        self.preview: dict | None = None
        self.meshes: list[dict] = []
        self.bones: list[dict] = []
        self.material_cfg: dict = {}
        self.mapping: dict = {}
        self.t5_textures: dict = {}
        self.editing: dict | None = None
        self.blender_project = None
        self.current_path = ''
        self.kind = 't5'
        self.images: dict = {}
        self.focus_bone = None
        self.clip = None
        self.clip_t = 0.0
        self.playing = False
        self.busy = False
        self.last_tick = time.perf_counter()
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self.job_timer = QTimer(self)
        self.job_timer.timeout.connect(self._poll_job)
        QTimer.singleShot(50, self._startup)

    def _build_ui(self):
        self.view = Viewport(self)
        self.view.statsChanged.connect(lambda s: self.stats.setText(s))
        self.view.togglePlay.connect(self._toggle_play)
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(4, 2, 4, 2)
        self.btn_play = QPushButton()
        self.btn_play.setFixedWidth(36)
        self.icon_play = self.style().standardIcon(QStyle.SP_MediaPlay)
        self.icon_pause = self.style().standardIcon(QStyle.SP_MediaPause)
        self.btn_play.setIcon(self.icon_play)
        self.btn_play.clicked.connect(self._toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._scrub)
        self.lbl_time = QLabel('0.00 / 0.00 s')
        self.lbl_time.setMinimumWidth(110)
        self.speed = QComboBox()
        self.speed.addItems(['0.1×', '0.25×', '0.5×', '1×', '2×'])
        self.speed.setCurrentIndex(3)
        self.chk_loop = QCheckBox(_t('Loop'))
        self.chk_loop.setChecked(True)
        self.chk_root = QCheckBox(_t('Mover raiz'))
        self.chk_root.setToolTip(_t('Desloca o personagem pelo chão como no jogo'))
        self.chk_root.toggled.connect(lambda _: self._reload_clip())
        for w in (self.btn_play, self.slider, self.lbl_time, self.speed, self.chk_loop, self.chk_root):
            hb.addWidget(w)
        center = QWidget()
        vb = QVBoxLayout(center)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)
        self.path_label = QLabel('—')
        self.path_label.setObjectName('PathLabel')
        vb.addWidget(self.path_label)
        vb.addWidget(self.view, 1)
        vb.addWidget(bar)
        self.setCentralWidget(center)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.cmb_kind = QComboBox()
        for code, name in KINDS:
            self.cmb_kind.addItem(name, code)
        self.cmb_kind.currentIndexChanged.connect(self._kind_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_t('Buscar skin ou ID do recurso…'))
        self.search.textChanged.connect(lambda _: self._fill_library())
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.setIconSize(QSize(48, 48))
        self.library.itemClicked.connect(self._library_clicked)
        btn_open = QPushButton(_t('Abrir modelo…'))
        btn_open.clicked.connect(self._open_file)
        lv.addWidget(self.cmb_kind)
        lv.addWidget(self.search)
        lv.addWidget(self.library, 1)
        lv.addWidget(btn_open)
        dock = QDockWidget(_t('Fontes'), self)
        dock.setObjectName('sources')
        dock.setWidget(left)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_animations(), _t('Animações'))
        self.tabs.addTab(self._tab_install(), _t('Personagem e slot'))
        self.tabs.addTab(self._tab_rig(), _t('Ossos e proporções'))
        self.tabs.addTab(self._tab_materials(), _t('Materiais'))
        self.tabs.addTab(self._tab_blender(), _t('Blender'))
        self.tabs.addTab(self._tab_mods(), _t('Mods da ISO'))
        dock = QDockWidget(_t('Detalhes'), self)
        dock.setObjectName('details')
        dock.setWidget(self.tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        dock = QDockWidget(_t('Saída'), self)
        dock.setObjectName('log')
        dock.setWidget(self.log_view)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [120], Qt.Vertical)

        tb = QToolBar('main')
        tb.setObjectName('main')
        self.addToolBar(tb)
        tb.addWidget(QLabel(' ' + _t('Visualização') + ': '))
        self.cmb_view = QComboBox()
        self.cmb_view.addItems([_t(v) for v in VIEWS])
        self.cmb_view.currentIndexChanged.connect(lambda _: self._paint())
        tb.addWidget(self.cmb_view)
        self.cmb_focus = QComboBox()
        self.cmb_focus.setMinimumWidth(170)
        self.cmb_focus.setToolTip(_t('Osso exibido'))
        self.cmb_focus.currentIndexChanged.connect(self._focus_changed)
        self.focus_action = tb.addWidget(self.cmb_focus)
        self.focus_action.setVisible(False)
        tb.addSeparator()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([_t(m) for m in Viewport.MODES])
        self.cmb_mode.currentIndexChanged.connect(lambda i: (setattr(self.view, 'mode', i), self.view.update()))
        tb.addWidget(self.cmb_mode)
        for text, attr, key in (('Wireframe', 'wireframe', 'W'), ('Ossos', 'show_bones', 'B'), ('Grade', 'show_grid', 'G')):
            act = QAction(_t(text), self, checkable=True)
            act.setChecked(getattr(self.view, attr))
            act.setToolTip('%s (%s)' % (_t(text), key))
            act.toggled.connect(lambda v, a=attr: (setattr(self.view, a, v), self.view.update()))
            tb.addAction(act)
        tb.addSeparator()
        for text, yaw in (('Frente', 0), ('Lado', 90), ('Costas', 180)):
            tb.addAction(_t(text), lambda y=yaw: self.view.set_view(y, 5))
        tb.addAction(_t('Enquadrar'), self.view.frame)

        mb = self.menuBar()
        m = mb.addMenu(_t('&Arquivo'))
        m.addAction(_t('Pastas e jogo…'), lambda: self._settings())
        m.addAction(_t('Abrir modelo…'), self._open_file)
        m.addAction(_t('Abrir pasta do Studio'), lambda: os.startfile(str(self.studio.home)))
        m.addSeparator()
        m.addAction(_t('Gerar ISO com mods'), self._build_iso)
        m.addAction(_t('Salvar imagem do viewport…'), self._save_screenshot)
        m.addSeparator()
        m.addAction(_t('Sair'), self.close)
        m = mb.addMenu('&Language' if i18n.language() == 'en' else _t('&Idioma') + ' (Language)')
        grp = QActionGroup(self)
        for code, name in i18n.languages().items():
            a = m.addAction(name, lambda c=code: self._set_language(c))
            a.setCheckable(True)
            a.setChecked(code == i18n.language())
            grp.addAction(a)
        m = mb.addMenu(_t('A&juda'))
        m.addAction(_t('Sobre o Tekken 5 Skin Studio'), self._about)

        self.stats = QLabel()
        self.job_label = QLabel(_t('Pronto para importar'))
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        self.statusBar().addWidget(self.job_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.stats)

    def _tab_animations(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        self.anim_filter = QLineEdit()
        self.anim_filter.setPlaceholderText(_t('Filtrar (ex.: 120, 1.5s)…'))
        self.anim_filter.textChanged.connect(self._filter_anims)
        self.anim_list = QTreeWidget()
        self.anim_list.setHeaderLabels([_t('Animação'), _t('Duração'), _t('Quadros')])
        self.anim_list.setColumnWidth(0, 150)
        self.anim_list.itemClicked.connect(self._anim_clicked)
        lay.addWidget(self.anim_filter)
        lay.addWidget(self.anim_list)
        hint = QLabel(_t('Animações do jogo tocadas no esqueleto da roupa base. Dedos e rosto ficam em repouso.'))
        hint.setObjectName('Hint')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _tab_install(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.cmb_char = QComboBox()
        self.cmb_char.currentIndexChanged.connect(lambda _: self._char_changed())
        self.cmb_base = QComboBox()
        self.cmb_base.currentIndexChanged.connect(lambda _: self._base_changed())
        form.addRow(_t('Personagem de destino'), self.cmb_char)
        form.addRow(_t('Roupa base / esqueleto'), self.cmb_base)
        lay.addLayout(form)
        self.mode_box = QWidget()
        ml = QVBoxLayout(self.mode_box)
        ml.setContentsMargins(0, 0, 0, 0)
        self.rb_replace = QRadioButton(_t('Substituir roupa') + ' — ' + _t('Usa o slot da roupa base selecionada.'))
        self.rb_add = QRadioButton(_t('Criar novo slot') + ' — ' + _t('Preserva as roupas existentes. Até 5 trajes.'))
        self.rb_replace.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_replace)
        grp.addButton(self.rb_add)
        self.rb_replace.toggled.connect(lambda _: self._slot_info())
        ml.addWidget(self.rb_replace)
        ml.addWidget(self.rb_add)
        lay.addWidget(self.mode_box)
        self.slot_info = QLabel()
        self.slot_info.setObjectName('Hint')
        self.slot_info.setWordWrap(True)
        lay.addWidget(self.slot_info)
        self.t5_note = QLabel(_t('Roupa original do Tekken 5. Troque as texturas na aba Materiais: o mod substitui só as texturas desta roupa e mantém modelo, esqueleto e física.'))
        self.t5_note.setWordWrap(True)
        self.t5_note.setObjectName('Hint')
        lay.addWidget(self.t5_note)
        form2 = QFormLayout()
        self.mod_name = QLineEdit()
        self.mod_name.setPlaceholderText(_t('Ex.: Julia · roupa clássica do T4'))
        form2.addRow(_t('Nome do mod'), self.mod_name)
        lay.addLayout(form2)
        self.edit_banner = QLabel()
        self.edit_banner.setWordWrap(True)
        self.edit_banner.setStyleSheet('color:#e2c48c')
        lay.addWidget(self.edit_banner)
        row = QHBoxLayout()
        self.btn_convert = QPushButton(_t('Converter e adicionar aos mods'))
        self.btn_convert.setDefault(True)
        self.btn_convert.clicked.connect(self._convert)
        self.btn_cancel_edit = QPushButton(_t('Cancelar edição'))
        self.btn_cancel_edit.clicked.connect(self._cancel_edit)
        row.addWidget(self.btn_convert)
        row.addWidget(self.btn_cancel_edit)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _tab_rig(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        grid = QGridLayout()
        self.sp_scale = self._spin(0.0001, 100000, 1, 3)
        self.sp_yaw = self._spin(-360, 360, 0, 1)
        self.sp_y = self._spin(-100000, 100000, 1127, 1)
        self.sp_z = self._spin(-100000, 100000, 0, 1)
        for c, (label, sp) in enumerate(((_t('Escala'), self.sp_scale), (_t('Rotação Y (°)'), self.sp_yaw),
                                         (_t('Posição Y'), self.sp_y), (_t('Posição Z'), self.sp_z))):
            grid.addWidget(QLabel(label), 0, c)
            grid.addWidget(sp, 1, c)
        lay.addLayout(grid)
        self.chk_retarget = QCheckBox(_t('Adaptar a pose de repouso aos ossos de destino'))
        self.chk_hair = QCheckBox(_t('Reaproveitar cadeia auxiliar de cabelo (XPS)'))
        lay.addWidget(self.chk_retarget)
        lay.addWidget(self.chk_hair)
        row = QHBoxLayout()
        b1 = QPushButton(_t('Atualizar prévia'))
        b1.clicked.connect(self._update_preview)
        b2 = QPushButton(_t('Refazer automático'))
        b2.clicked.connect(lambda: (self.mapping.clear(), self._update_preview()))
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        test = QHBoxLayout()
        test.addWidget(QLabel(_t('Teste de pesos')))
        self.cmb_pose = QComboBox()
        self.cmb_pose.currentIndexChanged.connect(lambda _: self._pose_test())
        self.pose_angle = QSlider(Qt.Horizontal)
        self.pose_angle.setRange(-70, 70)
        self.pose_angle.valueChanged.connect(lambda _: self._pose_test())
        self.lbl_angle = QLabel('0°')
        test.addWidget(self.cmb_pose, 1)
        test.addWidget(self.pose_angle, 1)
        test.addWidget(self.lbl_angle)
        lay.addLayout(test)
        self.bone_search = QLineEdit()
        self.bone_search.setPlaceholderText(_t('Buscar osso, destino ou motivo…'))
        self.bone_search.textChanged.connect(lambda _: self._fill_bones())
        self.chk_review = QCheckBox(_t('Mostrar apenas associações para revisar'))
        self.chk_review.toggled.connect(lambda _: self._fill_bones())
        lay.addWidget(self.bone_search)
        lay.addWidget(self.chk_review)
        self.mapping_summary = QLabel()
        self.mapping_summary.setObjectName('Hint')
        lay.addWidget(self.mapping_summary)
        self.bone_tree = QTreeWidget()
        self.bone_tree.setHeaderLabels([_t('Osso da fonte'), _t('Destino'), _t('Motivo')])
        self.bone_tree.setColumnWidth(0, 170)
        self.bone_tree.setColumnWidth(1, 170)
        self.bone_tree.setRootIsDecorated(False)
        self.bone_tree.itemDoubleClicked.connect(self._remap)
        lay.addWidget(self.bone_tree, 1)
        hint = QLabel(_t('Duplo clique numa linha para escolher outro osso de destino.'))
        hint.setObjectName('Hint')
        lay.addWidget(hint)
        return w

    def _spin(self, low, high, value, decimals):
        sp = QDoubleSpinBox()
        sp.setRange(low, high)
        sp.setDecimals(decimals)
        sp.setValue(value)
        return sp

    def _tab_materials(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        self.mat_hint = QLabel()
        self.mat_hint.setWordWrap(True)
        self.mat_hint.setObjectName('Hint')
        lay.addWidget(self.mat_hint)
        self.mat_tree = QTreeWidget()
        self.mat_tree.setHeaderLabels([_t('Material'), _t('Situação')])
        self.mat_tree.setIconSize(QSize(64, 64))
        self.mat_tree.setColumnWidth(0, 260)
        self.mat_tree.setRootIsDecorated(False)
        self.mat_tree.itemChanged.connect(self._material_toggled)
        self.mat_tree.itemDoubleClicked.connect(lambda it, _: self._swap_material(it))
        self.mat_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mat_tree.customContextMenuRequested.connect(self._material_menu)
        lay.addWidget(self.mat_tree, 1)
        row = QHBoxLayout()
        b1 = QPushButton(_t('Trocar textura…'))
        b1.clicked.connect(lambda: self._swap_material(self.mat_tree.currentItem()))
        self.btn_original = QPushButton(_t('Original'))
        self.btn_original.clicked.connect(lambda: self._restore_material(self.mat_tree.currentItem()))
        self.btn_color = QPushButton(_t('Cor…'))
        self.btn_color.clicked.connect(lambda: self._material_color(self.mat_tree.currentItem()))
        self.btn_alpha = QPushButton(_t('Alpha da textura'))
        self.btn_alpha.clicked.connect(lambda: self._material_alpha(self.mat_tree.currentItem()))
        for b in (b1, self.btn_original, self.btn_color, self.btn_alpha):
            row.addWidget(b)
        lay.addLayout(row)
        return w

    def _tab_blender(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(_t('Abre a skin já adaptada ao esqueleto T5, com texturas e pesos, no Blender 2.79. Edite a malha, UVs ou pesos. Preserve os ossos e a pose de repouso.'))
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        self.btn_edit_blender = QPushButton(_t('Editar no Blender'))
        self.btn_edit_blender.clicked.connect(self._blender_edit)
        self.btn_reload_blender = QPushButton(_t('Recarregar edição'))
        self.btn_reload_blender.clicked.connect(self._blender_reload)
        self.btn_reopen_blender = QPushButton(_t('Reabrir edição'))
        self.btn_reopen_blender.clicked.connect(self._blender_open)
        for b in (self.btn_edit_blender, self.btn_reload_blender, self.btn_reopen_blender):
            row.addWidget(b)
        lay.addLayout(row)
        self.blender_status = QLabel(_t('Carregue uma skin para começar.'))
        self.blender_status.setWordWrap(True)
        self.blender_status.setObjectName('Hint')
        lay.addWidget(self.blender_status)
        hint = QLabel(_t('No Blender, salve com Ctrl+S ou use “Salvar para o Studio” na aba T5 Skin Studio. Depois clique em Recarregar edição aqui, confira a prévia e converta o mod normalmente. Os arquivos de origem são preservados.'))
        hint.setWordWrap(True)
        hint.setObjectName('Hint')
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _tab_mods(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        hint = QLabel(_t('Ative as skins que devem entrar na próxima construção.'))
        hint.setObjectName('Hint')
        lay.addWidget(hint)
        self.mod_tree = QTreeWidget()
        self.mod_tree.setHeaderLabels([_t('Mod'), _t('Detalhes')])
        self.mod_tree.setColumnWidth(0, 200)
        self.mod_tree.setRootIsDecorated(False)
        self.mod_tree.itemChanged.connect(self._mod_toggled)
        self.mod_tree.itemDoubleClicked.connect(lambda it, _: self._open_mod(it))
        lay.addWidget(self.mod_tree, 1)
        row = QHBoxLayout()
        b1 = QPushButton(_t('Editar'))
        b1.clicked.connect(lambda: self._open_mod(self.mod_tree.currentItem()))
        b2 = QPushButton(_t('Excluir…'))
        b2.clicked.connect(lambda: self._delete_mod(self.mod_tree.currentItem()))
        b3 = QPushButton(_t('Abrir pasta'))
        b3.clicked.connect(lambda: os.startfile(str(self.studio.home / 'mods')) if (self.studio.home / 'mods').is_dir() else None)
        for b in (b1, b2, b3):
            row.addWidget(b)
        lay.addLayout(row)
        form = QFormLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText(_t('Automático: pasta builds do Studio'))
        form.addRow(_t('Destino da nova ISO'), self.output)
        lay.addLayout(form)
        self.btn_build = QPushButton(_t('Gerar ISO com mods'))
        self.btn_build.setDefault(True)
        self.btn_build.clicked.connect(self._build_iso)
        lay.addWidget(self.btn_build)
        return w

    def log(self, text):
        self.log_view.appendPlainText(text)

    def error(self, message):
        text = tr(str(message).split('\n\n')[0])
        self.log(_t('ERRO: ') + text)
        QMessageBox.critical(self, 'Tekken 5 Skin Studio', text)

    def run(self, fn, done, message=''):
        if self.busy:
            QMessageBox.information(self, 'Tekken 5 Skin Studio', _t('Aguarde a operação atual terminar'))
            return
        self.busy = True
        if message:
            self.job_label.setText(_t(message))
            self.log('▶ ' + _t(message))
        self.progress.show()
        self.setCursor(Qt.BusyCursor)
        task = Task(lambda: self._locked(fn))

        def finish(result=None, failure=None):
            self.busy = False
            self.progress.setVisible(self.job_timer.isActive())
            self.unsetCursor()
            if failure is not None:
                self.error(failure)
            else:
                try:
                    done(result)
                except Exception as exc:
                    self.error('%s\n\n%s' % (exc, traceback.format_exc()))
        task.signals.done.connect(lambda r: finish(r))
        task.signals.failed.connect(lambda e: finish(failure=e))
        self._tasks = getattr(self, '_tasks', []) + [task]
        self.pool.start(task)

    def _locked(self, fn):
        with self.studio.lock:
            return fn()

    def api(self, route, data=None):
        with self.studio.lock:
            return self.studio.api(route, data or {})

    def file_path(self, url):
        if not url:
            return None
        if url.startswith('/file/'):
            return self.studio.files.get(url[6:])
        return url

    def image(self, path):
        if not path:
            return None
        key = (str(path), Path(path).stat().st_mtime_ns if Path(path).is_file() else 0)
        if key not in self.images:
            try:
                with Image.open(path) as im:
                    self.images[key] = np.asarray(im.convert('RGBA'), np.uint8).copy()
            except OSError:
                self.images[key] = None
        return self.images[key]

    def _startup(self):
        try:
            self.state = self.api('/api/init')
        except Exception as exc:
            self.error(exc)
            return
        self.blender_project = self.state.get('blender_project')
        self._fill_characters()
        self._fill_library()
        self._fill_mods()
        self._update_controls()
        if self.state.get('error'):
            self.log(tr(self.state['error']))
            self._settings(first_run=not self.studio.config.get('iso'))

    def _settings(self, first_run=False):
        dlg = SettingsDialog(self, first_run)
        if dlg.exec_() != QDialog.Accepted:
            return
        if getattr(dlg, 'new_lang', None) and dlg.new_lang != i18n.language():
            self._set_language(dlg.new_lang)
            return
        self._startup()

    def _set_language(self, code):
        try:
            self.api('/api/lang', {'lang': code})
        except ValueError as exc:
            self.error(exc)
            return
        set_language(self.studio.home, code)
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('state', self.saveState())
        w = MainWindow(self.studio)
        QApplication.instance().main_window = w
        w.show()
        self.close()

    def _about(self):
        QMessageBox.about(self, _t('Sobre o Tekken 5 Skin Studio'),
                          '<h3>Tekken 5 Skin Studio %s</h3><p>%s</p><p>%s: <b>%s</b> · GPL-3.0</p><p>%s</p>' % (
                              VERSION, _t('Ferramenta para trocar e importar roupas no Tekken 5 de PS2 (USA 1.00, SLUS-21059).'),
                              _t('Autor'), AUTHOR,
                              _t('O decodificador de animações é uma adaptação do TKMovesets, de Kiloutre (GPL-3.0). Ferramenta de fãs, sem vínculo com a Bandai Namco. Nenhum arquivo do jogo acompanha o programa.')))

    def _fill_characters(self):
        old = self.cmb_char.currentData()
        self.cmb_char.blockSignals(True)
        self.cmb_char.clear()
        for c in self.state.get('characters', []):
            self.cmb_char.addItem(c['name'], c['id'])
        i = self.cmb_char.findData(old if old is not None else 10)
        self.cmb_char.setCurrentIndex(max(0, i))
        self.cmb_char.blockSignals(False)
        self._fill_bases()

    def _fill_bases(self, keep=None):
        c = self._character()
        self.cmb_base.blockSignals(True)
        self.cmb_base.clear()
        for s in (c['slots'] if c else []):
            self.cmb_base.addItem('%s · %s %d' % (s['label'], _t('recurso'), s['resource']), s['index'])
        if keep is not None:
            self.cmb_base.setCurrentIndex(max(0, self.cmb_base.findData(keep)))
        self.cmb_base.blockSignals(False)
        self._slot_info()

    def _select_slot(self, cid, base):
        self.cmb_char.blockSignals(True)
        self.cmb_char.setCurrentIndex(max(0, self.cmb_char.findData(cid)))
        self.cmb_char.blockSignals(False)
        self._fill_bases(keep=base)

    def _character(self):
        cid = self.cmb_char.currentData()
        return next((c for c in self.state.get('characters', []) if c['id'] == cid), None)

    def _kind_changed(self):
        self.kind = self.cmb_kind.currentData()
        self._fill_library()

    def _fill_library(self):
        text = self.search.text().lower()
        self.library.clear()
        if self.kind == 't5':
            for c in self.state.get('characters', []):
                parent = None
                for s in c['slots']:
                    label = '%s · %s' % (c['name'], s['label'])
                    if text and text not in label.lower():
                        continue
                    if parent is None:
                        parent = QTreeWidgetItem([c['name']])
                        self.library.addTopLevelItem(parent)
                    it = QTreeWidgetItem([s['label'] + '  ·  ' + _t('recurso') + ' %d' % s['resource']])
                    it.setData(0, Qt.UserRole, ('t5', s['index']))
                    parent.addChild(it)
                if parent is not None:
                    parent.setExpanded(bool(text))
            return
        if self.kind == 'xps':
            it = QTreeWidgetItem([_t('Abra um .xps, .mesh ou .mesh.ascii pelo botão abaixo.')])
            it.setFlags(Qt.NoItemFlags)
            self.library.addTopLevelItem(it)
        for item in self.state.get('library', []):
            if item['kind'] != self.kind or (text and text not in item['name'].lower()):
                continue
            it = QTreeWidgetItem([item['name']])
            it.setData(0, Qt.UserRole, ('path', item['path']))
            thumb = self.file_path(item.get('thumbnail'))
            if thumb:
                it.setIcon(0, QIcon(QPixmap(thumb).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.library.addTopLevelItem(it)

    def _library_clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == 't5':
            self.load_original(data[1])
        else:
            self.load_source(data[1])

    def _open_file(self):
        flt = _t('Modelos e exports') + ' (*.json *.kmd *.xps *.mesh *.ascii);;' + _t('Todos') + ' (*.*)'
        path, _ = QFileDialog.getOpenFileName(self, _t('Escolher arquivo'), '', flt)
        if path:
            self.load_source(path)

    def request(self):
        return dict(base_index=self.cmb_base.currentData(), character=self.cmb_char.currentData(),
                    settings=dict(scale=self.sp_scale.value(), yaw=self.sp_yaw.value(),
                                  offset=[0, self.sp_y.value(), self.sp_z.value()],
                                  retarget=self.chk_retarget.isChecked(), reuse_hair=self.chk_hair.isChecked(),
                                  mapping={str(k): v for k, v in self.mapping.items()}, materials=self.material_cfg))

    def load_original(self, base, textures=None, mod=None):
        textures = dict(textures or {})

        def work():
            if mod is not None:
                return self.studio.api('/api/mod/open', {'id': mod['id']})
            return self.studio.api('/api/t5/costume', {'base_index': base, 'textures': textures})

        def done(data):
            self.editing = data.get('mod')
            self.t5_textures = dict(data.get('textures') or textures)
            self.material_cfg, self.mapping, self.blender_project = {}, {}, None
            self.current_path = 't5:%d' % data['base_index']
            if data.get('character') is not None or self.editing:
                cid = self.editing['character'] if self.editing else data['character']
                self._select_slot(cid, data['base_index'])
            self.show_preview(data, reset=True)
            self.mod_name.setText(self.editing['name'] if self.editing else _t('Texturas · {0}', data['name']))
            self.job_label.setText(_t('Roupa original carregada. Troque texturas na aba Materiais ou toque uma animação do jogo.'))
        self.run(work, done, 'Lendo a roupa original…')

    def load_source(self, path, mod=None):
        low = path.lower()
        xps = low.endswith(('.xps', '.mesh', '.ascii'))
        edit = low.endswith('.t5skin.json')
        if mod is None:
            self.material_cfg, self.mapping = {}, {}
            self.sp_scale.setValue(1000 if xps else 1)
            self.sp_y.setValue(0 if xps or edit else 1127)
            self.sp_z.setValue(0)
            self.sp_yaw.setValue(0)
            self.chk_hair.setChecked(False)
            self.chk_retarget.setChecked(not xps and not edit and not low.endswith('scene.json'))
        req = dict(self.request(), path=path)

        def work():
            if mod is not None:
                return self.studio.api('/api/mod/open', {'id': mod['id']})
            return self.studio.api('/api/source', req)

        def done(data):
            self.editing = data.get('mod')
            self.blender_project = None
            self.t5_textures = {}
            if data.get('kind') == 't5edit' or self.editing:
                base = data['base_index']
                cid = self.editing['character'] if self.editing else next(
                    (c['id'] for c in self.state['characters'] if any(s['index'] == base for s in c['slots'])), None)
                self._select_slot(cid, base)
            if self.editing:
                (self.rb_add if self.editing['mode'] == 'add' else self.rb_replace).setChecked(True)
            self.current_path = path
            self.show_preview(data, reset=True)
            self.mod_name.setText(self.editing['name'] if self.editing else data['name'])
            self.job_label.setText(_t('Modelo carregado. Revise ossos e materiais.'))
        if mod is not None:
            s = mod.get('settings', {})
            self.material_cfg = dict(s.get('materials', {}))
            self.mapping = {int(k): v for k, v in s.get('mapping', {}).items()}
            self.sp_scale.setValue(s.get('scale', 1))
            self.sp_yaw.setValue(s.get('yaw', 0))
            off = s.get('offset', [0, 0, 0])
            self.sp_y.setValue(off[1])
            self.sp_z.setValue(off[2])
            self.chk_retarget.setChecked(bool(s.get('retarget')))
            self.chk_hair.setChecked(bool(s.get('reuse_hair')))
        self.run(work, done, 'Lendo modelo, texturas e esqueleto…')

    def _update_preview(self):
        if not self.preview:
            return
        if self.is_t5():
            base = self.preview['base_index']
            textures = dict(self.t5_textures)
            self.run(lambda: self.studio.api('/api/t5/costume', {'base_index': base, 'textures': textures}),
                     lambda d: self.show_preview(d, reset=False), 'Atualizando a prévia…')
            return
        req = self.request()
        self.run(lambda: self.studio.api('/api/preview', req), lambda d: self.show_preview(d, reset=False),
                 'Atualizando a prévia…')

    def is_t5(self):
        return bool(self.preview) and self.preview.get('kind') == 't5'

    def show_preview(self, data, reset=False):
        self.stop()
        self.preview = data
        self.bones = data['target_bones']
        self.rest = np.array([b['position'] for b in self.bones], np.float32)
        mats = {m['key']: m for m in data['materials']}
        self.meshes, parts, images = [], [], {}
        for i, m in enumerate(data['meshes']):
            pos = np.asarray(m['positions'], np.float32).reshape(-1, 3)
            mesh = dict(key=i, pos=pos, nrm=np.asarray(m['normals'], np.float32).reshape(-1, 3),
                        uv=np.asarray(m['uv'], np.float32).reshape(-1, 2),
                        faces=np.asarray(m['faces'], np.int64).reshape(-1, 3),
                        weights=np.asarray(m['weights'], np.float32).reshape(-1, 4),
                        indices=np.asarray(m['indices'], np.int64).reshape(-1, 4),
                        sources=np.asarray(m['sources'], np.int64).reshape(-1, 4), material=m['material'])
            self.meshes.append(mesh)
            mat = mats.get(m['material'], {})
            color = QColor(mat.get('color', '#ffffff'))
            parts.append(dict(key=i, faces=mesh['faces'], face_mats=np.zeros(len(mesh['faces']), np.int64),
                              mat_tex=[m['material']], uv=mesh['uv'], opaque=mat.get('alpha') == 'opaque',
                              tint=(color.redF(), color.greenF(), color.blueF(), 1.0)))
            if m['material'] not in images:
                img = self.image(self.file_path(mat.get('url')))
                if img is not None:
                    images[m['material']] = img
        self.view.set_scene(parts, images, reframe=reset)
        name = data.get('name') or ''
        self.path_label.setText('%s  ·  %s' % (name, _t('{0} TRIÂNGULOS · {1} OSSOS', '{:,}'.format(data['triangles']).replace(',', '.'), len(self.bones))))
        self.cmb_focus.blockSignals(True)
        self.cmb_focus.clear()
        self.cmb_pose.blockSignals(True)
        self.cmb_pose.clear()
        for b in self.bones:
            label = tr(b['name']) + (' · ' + _t('física') if b.get('physics') else '')
            self.cmb_focus.addItem(label, b['id'])
            self.cmb_pose.addItem(label, b['id'])
        self.cmb_pose.setCurrentIndex(min(8, self.cmb_pose.count() - 1))
        self.cmb_focus.blockSignals(False)
        self.cmb_pose.blockSignals(False)
        self.pose_angle.blockSignals(True)
        self.pose_angle.setValue(0)
        self.pose_angle.blockSignals(False)
        self.lbl_angle.setText('0°')
        for w in data.get('warnings', []):
            self.log('⚠ ' + tr(w))
        self._pose_rest()
        self._paint()
        self._fill_bones()
        self._fill_materials()
        self._update_controls()
        self._load_banks()

    def _skin(self, transforms):
        frame, lines = {}, None
        for m in self.meshes:
            R = transforms[m['indices']][..., :9].reshape(-1, 4, 3, 3)
            T = transforms[m['indices']][..., 9:]
            w = m['weights'][..., None]
            p = (np.einsum('vkij,vj->vki', R, m['pos']) + T) * w
            n = np.einsum('vkij,vj->vki', R, m['nrm']) * w
            total = np.maximum(m['weights'].sum(1, keepdims=True), 1e-6)
            frame[m['key']] = ((p.sum(1) / total).astype(np.float32), n.sum(1).astype(np.float32))
        posed = np.einsum('bij,bj->bi', transforms[:, :9].reshape(-1, 3, 3), self.rest) + transforms[:, 9:]
        self.view.set_pose(frame, self._bone_lines(posed))

    def _bone_lines(self, positions):
        rows = []
        for b in self.bones:
            p = b['parent']
            if 0 <= p < len(self.bones):
                col = (1.0, .55, .2, 1.0) if b.get('physics') else (.95, .8, .3, 1.0)
                rows.append((*positions[p], *col))
                rows.append((*positions[b['id']], *col))
        return np.asarray(rows, np.float32) if rows else None

    def _identity(self):
        t = np.zeros((len(self.bones), 12), np.float32)
        t[:, [0, 4, 8]] = 1
        return t

    def _pose_rest(self):
        if self.meshes:
            self._skin(self._identity())

    def _pose_test(self):
        if not self.meshes:
            return
        self.stop()
        idx = self.cmb_pose.currentData()
        angle = np.radians(self.pose_angle.value())
        self.lbl_angle.setText('%d°' % self.pose_angle.value())
        if idx is None:
            return
        affected = {idx}
        for _ in self.bones:
            for b in self.bones:
                if b['parent'] in affected:
                    affected.add(b['id'])
        c, s = np.cos(angle), np.sin(angle)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)
        pivot = self.rest[idx]
        t = self._identity()
        for b in affected:
            t[b, :9] = R.ravel()
            t[b, 9:] = pivot - R @ pivot
        self._skin(t)

    def _focus_changed(self, _):
        self.focus_bone = self.cmb_focus.currentData()
        if self.cmb_view.currentIndex() == 2:
            self._paint()

    def _paint(self):
        mode = self.cmb_view.currentIndex()
        self.focus_action.setVisible(mode == 2)
        if not self.meshes or mode == 0:
            self.view.set_colors({}, False)
            return
        physics = np.array([bool(b.get('physics')) for b in self.bones])
        colors_tab = np.array([bone_color(i) for i in range(len(self.bones))], np.float32)
        focus = self.focus_bone if self.focus_bone is not None else 0
        out = {}
        for m in self.meshes:
            w, idx = m['weights'], np.clip(m['indices'], 0, len(self.bones) - 1)
            total = np.maximum(w.sum(1), 1e-6)
            best = idx[np.arange(len(w)), w.argmax(1)]
            top = w.max(1)
            if mode == 1:
                col = colors_tab[best] * (.55 + .45 * top / total)[:, None]
            elif mode == 2:
                amount = (w * (idx == focus)).sum(1) / total
                x = np.clip(amount, 0, 1) * 4
                i = np.minimum(3, np.floor(x).astype(int))
                f = (x - i)[:, None]
                col = RAMP[i] + (RAMP[i + 1] - RAMP[i]) * f
                col[amount <= 0] = (.16, .16, .2)
            else:
                dyn = (w * physics[idx]).sum(1) / total
                dbone = np.where(physics[idx], w, 0).argmax(1)
                tone = np.where(dyn[:, None] > 0, colors_tab[idx[np.arange(len(w)), dbone]], np.array([1, .55, .2], np.float32))
                col = .4 + (tone - .4) * dyn[:, None]
            out[m['key']] = col.astype(np.float32)
        self.view.set_colors(out, True)

    def _anim_base(self):
        if self.is_t5():
            return self.preview['base_index']
        return self.cmb_base.currentData()

    def _load_banks(self):
        base = self._anim_base()
        if base is None or getattr(self, '_banks_base', None) == base:
            return
        if self.busy:
            QTimer.singleShot(200, self._load_banks)
            return
        self._banks_base = base
        self.anim_list.clear()
        self.clip = None

        def done(banks):
            for b in banks:
                top = QTreeWidgetItem(['%s (%d)' % (tr(b['name']), len(b['clips']))])
                for i, frames in enumerate(b['clips']):
                    it = QTreeWidgetItem(['#%03d' % i, '%.2fs' % (frames / 60), str(frames)])
                    it.setData(0, Qt.UserRole, (b['bank'], i))
                    top.addChild(it)
                self.anim_list.addTopLevelItem(top)
        self.run(lambda: original.banks(self.studio.game(), base), done)

    def _filter_anims(self, text):
        text = text.lower().strip()
        for i in range(self.anim_list.topLevelItemCount()):
            top = self.anim_list.topLevelItem(i)
            for j in range(top.childCount()):
                it = top.child(j)
                it.setHidden(bool(text) and text not in (it.text(0) + ' ' + it.text(1)).lower())

    def _anim_clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data:
            self._clip_key = data
            self._reload_clip(play=True)

    def _reload_clip(self, play=False):
        key = getattr(self, '_clip_key', None)
        if key is None or not self.meshes:
            return
        base, root = self._anim_base(), self.chk_root.isChecked()
        playing = play or self.playing

        def done(data):
            if data.shape[1] != len(self.bones):
                self.error(_t('Esqueleto diferente da roupa base'))
                return
            self.clip = data
            self.clip_t = 0.0 if play else self.clip_t
            self.playing = playing
            self.btn_play.setIcon(self.icon_pause if self.playing else self.icon_play)
            self._show_frame()
        self.run(lambda: original.clip_skin(self.studio.game(), base, key[0], key[1], root), done)

    def _toggle_play(self):
        if self.clip is None:
            return
        self.playing = not self.playing
        self.btn_play.setIcon(self.icon_pause if self.playing else self.icon_play)

    def stop(self):
        self.playing = False
        self.btn_play.setIcon(self.icon_play)

    def _scrub(self, value):
        if self.clip is None:
            return
        self.playing = False
        self.btn_play.setIcon(self.icon_play)
        self.clip_t = value / 1000 * (len(self.clip) - 1) / 60
        self._show_frame()

    def _tick(self):
        now = time.perf_counter()
        dt, self.last_tick = now - self.last_tick, now
        if not self.playing or self.clip is None:
            return
        speed = float(self.speed.currentText().rstrip('×'))
        duration = (len(self.clip) - 1) / 60
        self.clip_t += dt * speed
        if self.clip_t > duration:
            if self.chk_loop.isChecked():
                self.clip_t %= max(duration, 1e-6)
            else:
                self.clip_t = duration
                self.stop()
        self._show_frame()

    def _show_frame(self):
        if self.clip is None:
            return
        frame = min(len(self.clip) - 1, int(round(self.clip_t * 60)))
        self._skin(self.clip[frame])
        duration = (len(self.clip) - 1) / 60
        self.lbl_time.setText('%.2f / %.2f s  ·  %s' % (self.clip_t, duration, _t('quadro {0}/{1}', frame + 1, len(self.clip))))
        if not self.slider.isSliderDown():
            self.slider.setValue(int(self.clip_t / max(duration, 1e-6) * 1000))

    def _fill_bones(self):
        self.bone_tree.clear()
        if not self.preview:
            return
        names = {b['id']: tr(b['name']) for b in self.bones}
        text = self.bone_search.text().lower()
        review = dynamic = 0
        for b in self.preview['source_bones']:
            target = self.mapping.get(b['id'], b['target'])
            manual = b['id'] in self.mapping
            if b.get('confidence') == 'revisar' and not manual:
                review += 1
            if self.bones[target].get('physics') if 0 <= target < len(self.bones) else False:
                dynamic += 1
            reason = _t('Associação manual') if manual else tr(b.get('reason') or _t('Perfil da fonte'))
            row = ['%d · %s' % (b['id'], tr(b['name'])), names.get(target, str(target)), reason]
            if text and text not in ' '.join(row).lower():
                continue
            if self.chk_review.isChecked() and (manual or b.get('confidence') != 'revisar'):
                continue
            it = QTreeWidgetItem(row)
            it.setData(0, Qt.UserRole, b['id'])
            if b.get('confidence') == 'revisar' and not manual:
                it.setForeground(2, QColor('#e8b04b'))
            self.bone_tree.addTopLevelItem(it)
        self.mapping_summary.setText(_t('{0} ossos · {1} associações para revisar · {2} manuais', len(self.preview['source_bones']), review, len(self.mapping))
                                     + (' · ' + _t('{0} em ossos de física do jogo', dynamic) if dynamic else ''))

    def _remap(self, item, _col):
        if self.is_t5():
            return
        source = item.data(0, Qt.UserRole)
        labels = ['%s' % tr(b['name']) + (' · ' + _t('física') if b.get('physics') else '') for b in self.bones]
        current = self.mapping.get(source, next(b['target'] for b in self.preview['source_bones'] if b['id'] == source))
        choice, ok = QInputDialog.getItem(self, _t('Destino de') + ' ' + item.text(0), _t('Osso de destino'), labels,
                                          max(0, current), False)
        if ok:
            self.mapping[source] = labels.index(choice)
            self._update_preview()

    def _fill_materials(self):
        self.mat_tree.blockSignals(True)
        self.mat_tree.clear()
        t5 = self.is_t5()
        self.btn_color.setVisible(not t5)
        self.btn_alpha.setVisible(not t5)
        self.mat_hint.setText(_t('Escolha a imagem nova de cada textura. A prévia já mostra como ela fica no PS2: no tamanho original e reduzida à paleta da textura (16 ou 256 cores).') if t5
                              else _t('Textura difusa, cor padrão e canal alpha. Os shaders PBR do XPS não são reproduzidos pelo PS2.'))
        for m in (self.preview or {}).get('materials', []):
            if t5:
                n = m.get('native') or {}
                status = (_t('{0} cores', n['colors']) if n.get('colors') else _t('cor direta'))
                if self.t5_textures.get(m['key']):
                    status += ' · ' + _t('trocada')
            else:
                cfg = self.material_cfg.get(m['key'], {})
                status = ' · '.join(x for x in (
                    _t('Textura alterada ✓') if cfg.get('texture') else '',
                    cfg.get('color', m.get('color', '#ffffff')),
                    _t('Opaco') if cfg.get('alpha', m.get('alpha')) == 'opaque' else _t('Alpha da textura')) if x)
            it = QTreeWidgetItem([m['name'], status])
            it.setData(0, Qt.UserRole, m['key'])
            path = self.file_path(m.get('url'))
            if path:
                it.setIcon(0, QIcon(QPixmap(path).scaled(64, 64, Qt.KeepAspectRatio, Qt.FastTransformation)))
            if not t5:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if self.material_cfg.get(m['key'], {}).get('enabled', True) else Qt.Unchecked)
            if t5 and self.t5_textures.get(m['key']):
                it.setForeground(1, QColor('#e8b04b'))
            self.mat_tree.addTopLevelItem(it)
        self.mat_tree.blockSignals(False)

    def _material_cfg(self, key):
        m = next((x for x in self.preview['materials'] if x['key'] == key), {})
        return self.material_cfg.setdefault(key, dict(enabled=True, color=m.get('color', '#ffffff'), alpha=m.get('alpha', 'opaque')))

    def _material_toggled(self, item, _col):
        if self.is_t5() or item is None:
            return
        self._material_cfg(item.data(0, Qt.UserRole))['enabled'] = item.checkState(0) == Qt.Checked

    def _material_menu(self, pos):
        item = self.mat_tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction(_t('Trocar textura…'), lambda: self._swap_material(item))
        menu.addAction(_t('Original'), lambda: self._restore_material(item))
        if not self.is_t5():
            menu.addAction(_t('Cor…'), lambda: self._material_color(item))
            menu.addAction(_t('Alpha da textura'), lambda: self._material_alpha(item))
        menu.exec_(self.mat_tree.mapToGlobal(pos))

    def _swap_material(self, item):
        if item is None or not self.preview:
            return
        path, _ = QFileDialog.getOpenFileName(self, _t('Nova textura'), '', _t('Texturas') + ' (*.png *.dds *.tga *.jpg *.jpeg *.bmp)')
        if not path:
            return
        key = item.data(0, Qt.UserRole)
        if self.is_t5():
            self.t5_textures[key] = path
        else:
            self._material_cfg(key)['texture'] = path
        self._update_preview()

    def _restore_material(self, item):
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if self.is_t5():
            self.t5_textures.pop(key, None)
        else:
            self._material_cfg(key).pop('texture', None)
        self._update_preview()

    def _material_color(self, item):
        if item is None:
            return
        cfg = self._material_cfg(item.data(0, Qt.UserRole))
        color = QColorDialog.getColor(QColor(cfg.get('color', '#ffffff')), self)
        if color.isValid():
            cfg['color'] = color.name()
            self._update_preview()

    def _material_alpha(self, item):
        if item is None:
            return
        cfg = self._material_cfg(item.data(0, Qt.UserRole))
        cfg['alpha'] = 'texture' if cfg.get('alpha') == 'opaque' else 'opaque'
        self._update_preview()

    def _char_changed(self):
        self._fill_bases()
        self._base_changed()

    def _base_changed(self):
        self._slot_info()
        if self.preview and not self.is_t5():
            self.mapping.clear()
            self.blender_project = None
            self._update_preview()

    def _slot_info(self):
        c = self._character()
        if not c:
            return
        added = sum(m['enabled'] and m['mode'] == 'add' and m['character'] == c['id'] and m['id'] != (self.editing or {}).get('id')
                    for m in self.studio.config.get('mods', []))
        count = len(c['slots']) + added
        self.rb_add.setEnabled(c['can_add'] and count < 5)
        if not self.rb_add.isEnabled() and self.rb_add.isChecked():
            self.rb_replace.setChecked(True)
        adding = self.rb_add.isChecked()
        controls = {3: '1P: □ · 2P: ×/○ · 3P: △', 4: '1P: □ · 2P: × · 3P: △ · 4P: ○', 5: '1P: □ · 2P: × · 3P: Start · 4P: △ · 5P: ○'}
        self.slot_info.setText(_t('{0}: {1} de 5 roupas.', c['name'], count) + ' ' +
                               (_t('O novo slot também libera os trajes extras originais deste personagem.') if adding
                                else _t('A roupa base será substituída somente na ISO gerada.')) + ' ' + controls.get(count + 1 if adding else count, ''))

    def _update_controls(self):
        t5 = self.is_t5()
        has = bool(self.preview)
        self.mode_box.setVisible(not t5)
        self.slot_info.setVisible(not t5)
        self.t5_note.setVisible(t5)
        self.cmb_char.setEnabled(not t5)
        self.cmb_base.setEnabled(not t5)
        self.tabs.setTabEnabled(2, has and not t5)
        self.tabs.setTabEnabled(4, has and not t5)
        if self.editing:
            self.btn_convert.setText(_t('Salvar alterações no mod'))
            self.edit_banner.setText(_t('Editando “{0}”.', self.editing['name']))
        else:
            self.btn_convert.setText(_t('Salvar texturas como mod') if t5 else _t('Converter e adicionar aos mods'))
            self.edit_banner.setText('')
        self.btn_cancel_edit.setVisible(bool(self.editing))
        self.btn_convert.setEnabled(has and not self.job_timer.isActive())
        self.btn_edit_blender.setEnabled(has and not t5)
        self.btn_reload_blender.setEnabled(bool(self.blender_project))
        self.btn_reopen_blender.setEnabled(bool(self.blender_project))
        if self.blender_project:
            self.blender_status.setText(_t('Aberto no Blender:') + ' ' + str(self.blender_project.get('blend', '')))
        self.btn_build.setEnabled(any(m['enabled'] for m in self.studio.config.get('mods', [])) and not self.job_timer.isActive())

    def _cancel_edit(self):
        self.editing = None
        self._update_controls()
        self._slot_info()
        self.job_label.setText(_t('Edição cancelada. O mod não foi alterado.'))

    def _convert(self):
        if not self.preview:
            return
        try:
            if self.is_t5():
                job = self.api('/api/t5/save', {'name': self.mod_name.text(), 'textures': self.t5_textures,
                                                'edit': (self.editing or {}).get('id')})
            else:
                job = self.api('/api/convert', dict(self.request(), mode='add' if self.rb_add.isChecked() else 'replace',
                                                     name=self.mod_name.text(), edit=(self.editing or {}).get('id')))
        except ValueError as exc:
            self.error(exc)
            return
        self._start_job(job)

    def _start_job(self, job):
        self.progress.show()
        self.job_label.setText(tr(job.get('message', '')))
        self.job_timer.start(500)
        self._update_controls()

    def _poll_job(self):
        try:
            job = self.api('/api/job')
        except Exception:
            return
        self.job_label.setText(tr(job.get('message', '')))
        if job['state'] == 'running':
            return
        self.job_timer.stop()
        self.progress.hide()
        if job.get('error'):
            self.error(job['error'])
        else:
            self._job_done(job.get('result') or {})
        self.state = self.api('/api/init')
        self._fill_mods()
        self._slot_info()
        self._update_controls()

    def _job_done(self, result):
        if result.get('blender_project'):
            self.blender_project = result['blender_project']
            self.job_label.setText(_t('Blender pronto. Salve a edição e recarregue aqui.'))
        elif result.get('kind') == 'textures':
            updated = result.get('updated')
            self.editing = None
            self.job_label.setText(_t('Mod de texturas atualizado. Gere uma nova ISO para levar ao jogo.') if updated
                                   else _t('Mod de texturas criado. Ele já está ativo; gere a ISO para testar.'))
        elif result.get('report', {}).get('memory_budget'):
            r = result['report']
            if result.get('updated'):
                self.editing = None
            self.job_label.setText((_t('Mod “{0}” atualizado:', result['name']) if result.get('updated') else _t('Skin convertida:'))
                                   + ' ' + _t('{0} de {1} de memória', self._bytes(r['bytes']), self._bytes(r['memory_budget'])))
        elif result.get('output'):
            self.job_label.setText(_t('ISO gerada e verificada. Pronta para testar no PCSX2.'))
            self.log('✔ ' + result['output'])
        self.log('✔ ' + self.job_label.text())

    @staticmethod
    def _bytes(value):
        return ('%.2f MB' % (value / 1048576)).replace('.', ',') if value >= 1048576 else ('%.1f KB' % (value / 1024)).replace('.', ',')

    def _fill_mods(self):
        self.mod_tree.blockSignals(True)
        self.mod_tree.clear()
        for m in self.studio.config.get('mods', []):
            c = next((x for x in self.state.get('characters', []) if x['id'] == m['character']), None)
            slot = (c and next((s['label'] for s in c['slots'] if s['index'] == m['base_index']), '')) or ''
            if m.get('kind') == 'textures':
                detail = '%s · %s · %d %s · %s' % (c['name'] if c else m['character'], _t('Texturas da roupa {0}', slot),
                                                   m['report'].get('textures', 0), _t('texturas'), self._bytes(m['report']['bytes']))
            else:
                detail = '%s · %s · %s · %s' % (c['name'] if c else m['character'],
                                                _t('Novo slot') if m['mode'] == 'add' else _t('Substitui {0}', slot),
                                                _t('{0} triângulos', '{:,}'.format(m['report'].get('triangles', 0)).replace(',', '.')),
                                                self._bytes(m['report']['bytes']))
            it = QTreeWidgetItem([m['name'], detail])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if m['enabled'] else Qt.Unchecked)
            it.setData(0, Qt.UserRole, m['id'])
            if self.editing and self.editing.get('id') == m['id']:
                it.setForeground(0, QColor('#e2c48c'))
            self.mod_tree.addTopLevelItem(it)
        if not self.studio.config.get('mods'):
            it = QTreeWidgetItem([_t('Sua primeira skin aparece aqui depois da conversão.')])
            it.setFlags(Qt.NoItemFlags)
            self.mod_tree.addTopLevelItem(it)
        self.mod_tree.blockSignals(False)
        self._update_controls()

    def _mod(self, item):
        mid = item.data(0, Qt.UserRole) if item is not None else None
        return next((m for m in self.studio.config.get('mods', []) if m['id'] == mid), None)

    def _mod_toggled(self, item, _col):
        mod = self._mod(item)
        if mod is None:
            return
        try:
            self.api('/api/toggle', {'id': mod['id'], 'enabled': item.checkState(0) == Qt.Checked})
        except ValueError as exc:
            self.error(exc)
        self._fill_mods()
        self._slot_info()

    def _open_mod(self, item):
        mod = self._mod(item)
        if mod is None:
            return
        if mod.get('kind') == 'textures':
            self.load_original(mod['base_index'], mod=mod)
        else:
            self.load_source(mod['source'], mod=mod)

    def _delete_mod(self, item):
        mod = self._mod(item)
        if mod is None:
            return
        try:
            plan = self.api('/api/mod/delete-info', {'id': mod['id']})
        except ValueError as exc:
            self.error(exc)
            return
        text = (_t('Excluir mod?') + '\n\n' + plan['name'] + '\n' + plan['folder'] + '\n\n' +
                _t('Move a pasta deste mod para mods/.lixeira e remove sua entrada da lista. Para recuperar, mova a pasta de volta para mods e abra o Studio de novo: o mod volta desligado. Modelos de origem, projetos Blender, cache e ISOs já geradas são preservados.'))
        if QMessageBox.question(self, _t('Excluir mod'), text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            result = self.api('/api/mod/delete', {'id': mod['id'], 'stamp': plan['stamp'], 'confirmed': True})
        except ValueError as exc:
            self.error(exc)
            return
        if self.editing and self.editing.get('id') == mod['id']:
            self.editing = None
        self.log('✔ ' + (tr(result['warning']) if result.get('warning') else _t('Mod movido para a lixeira: {0}', result.get('trash'))))
        self._fill_mods()
        self._slot_info()

    def _build_iso(self):
        try:
            job = self.api('/api/build', {'output': self.output.text().strip()})
        except ValueError as exc:
            self.error(exc)
            return
        self._start_job(job)

    def _blender_edit(self):
        try:
            job = self.api('/api/blender/edit', self.request())
        except ValueError as exc:
            self.error(exc)
            return
        self._start_job(job)

    def _blender_open(self):
        try:
            self.blender_project = self.api('/api/blender/open')
        except ValueError as exc:
            self.error(exc)
        self._update_controls()

    def _blender_reload(self):
        if not self.blender_project:
            return
        output = self.blender_project['output']

        def done(data):
            self.material_cfg, self.mapping = {}, {}
            self.sp_scale.setValue(1)
            self.sp_yaw.setValue(0)
            self.sp_y.setValue(0)
            self.sp_z.setValue(0)
            self.chk_retarget.setChecked(False)
            base = data['base_index']
            cid = next((c['id'] for c in self.state['characters'] if any(s['index'] == base for s in c['slots'])), None)
            self._select_slot(cid, base)
            self.current_path = data.get('path', '')
            self.show_preview(data, reset=True)
            if not self.editing:
                self.mod_name.setText(data['name'])
            self.job_label.setText(_t('Edição recarregada. Confira a prévia e salve as alterações no mod.') if self.editing
                                   else _t('Edição recarregada. Confira a prévia e converta o mod.'))
        self.run(lambda: self.studio.api('/api/blender/reload', {'output': output}), done)

    def _save_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, _t('Salvar imagem'), str(self.studio.home / 'viewport.png'), 'PNG (*.png)')
        if path:
            self.view.grab_image().save(path)
            self.log('✔ ' + path)

    def closeEvent(self, event):
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('state', self.saveState())
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_restored', False):
            self._restored = True
            g = self.settings.value('geometry')
            if g is not None:
                self.restoreGeometry(g)
            s = self.settings.value('state')
            if s is not None:
                self.restoreState(s)


_qt_translators: list = []


def set_language(home, code):
    i18n.set_language(home, code)
    app = QApplication.instance()
    for t in _qt_translators:
        app.removeTranslator(t)
    _qt_translators.clear()
    lang = i18n.language()
    path = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    for name in dict.fromkeys(('qtbase_' + lang, 'qt_' + lang)):
        t = QTranslator(app)
        if t.load(name, path):
            app.installTranslator(t)
            _qt_translators.append(t)


def native_cli(argv):
    import argparse
    import json
    from ..native import export_reference
    from ..game import Archive
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--base', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if not 0 <= args.base < 79:
        raise ValueError('Base T5 inválida')
    config = json.loads(Path(args.config).read_text(encoding='utf8'))
    print(export_reference(Archive(config['iso']).read(240 + 11 * args.base), args.output))


def main():
    if '--native' in sys.argv:
        argv = [a for a in sys.argv[1:] if a != '--native']
        return native_cli(argv)
    if getattr(sys, 'frozen', False):
        os.environ['T5SKIN_EXE'] = sys.executable
    QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    app = QApplication(sys.argv)
    app.setApplicationName('Tekken 5 Skin Studio')
    home = home_dir()
    if '--home' in sys.argv:
        home = Path(sys.argv[sys.argv.index('--home') + 1]).resolve()
    studio = Studio(home)
    set_language(home, studio.config.get('lang'))
    theme.apply(app)
    w = MainWindow(studio)
    app.main_window = w
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
