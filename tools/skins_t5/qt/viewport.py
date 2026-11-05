from __future__ import annotations

import math

import numpy as np
from ..i18n import _t
from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import (QImage, QMatrix4x4, QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                         QOpenGLTexture, QOpenGLVersionProfile, QSurfaceFormat, QVector3D)
from PyQt5.QtWidgets import QOpenGLWidget

GL_LINES, GL_TRIANGLES = 1, 4
GL_DEPTH_TEST, GL_BLEND, GL_CULL_FACE = 0x0B71, 0x0BE2, 0x0B44
GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT = 0x4000, 0x0100
GL_FLOAT, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA = 0x1406, 0x0302, 0x0303
GL_FRONT_AND_BACK, GL_LINE, GL_FILL = 0x0408, 0x1B01, 0x1B02
GL_POLYGON_OFFSET_FILL, GL_LEQUAL, GL_MULTISAMPLE = 0x8037, 0x0203, 0x809D

MESH_VS = """
#version 120
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec2 a_uv;
attribute vec3 a_col;
uniform mat4 u_mvp;
varying vec3 v_nrm;
varying vec2 v_uv;
varying vec3 v_pos;
varying vec3 v_col;
void main() {
    v_nrm = a_nrm;
    v_uv = a_uv;
    v_col = a_col;
    v_pos = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

MESH_FS = """
#version 120
uniform sampler2D u_tex;
uniform int u_mode;
uniform int u_has_tex;
uniform vec3 u_eye;
uniform float u_cutoff;
uniform vec4 u_tint;
uniform int u_inspect;
uniform int u_opaque;
varying vec3 v_nrm;
varying vec2 v_uv;
varying vec3 v_pos;
varying vec3 v_col;
void main() {
    vec3 n = v_nrm;
    if (dot(n, n) < 1e-4) n = cross(dFdx(v_pos), dFdy(v_pos));
    n = normalize(n);
    vec3 view = normalize(u_eye - v_pos);
    if (dot(n, view) < 0.0) n = -n;
    vec4 base = vec4(0.70, 0.70, 0.72, 1.0);
    if (u_mode == 0 && u_has_tex == 1) base = texture2D(u_tex, v_uv);
    if (u_opaque == 0 && base.a < u_cutoff) discard;
    if (u_inspect == 1) { base = vec4(v_col, 1.0); }
    if (u_mode == 2) { gl_FragColor = vec4(n * 0.5 + 0.5, 1.0); return; }
    if (u_mode == 3) { vec2 f = fract(v_uv); gl_FragColor = vec4(f.x, f.y, 0.25, 1.0); return; }
    vec3 key = normalize(vec3(0.35, 0.75, 0.55));
    float light = 0.38 + 0.42 * max(dot(n, key), 0.0) + 0.30 * max(dot(n, view), 0.0);
    vec3 tint = u_inspect == 1 ? vec3(1.0) : u_tint.rgb;
    gl_FragColor = vec4(base.rgb * light * tint, u_tint.a);
}
"""

LINE_VS = """
#version 120
attribute vec3 a_pos;
attribute vec4 a_col;
uniform mat4 u_mvp;
varying vec4 v_col;
void main() { v_col = a_col; gl_Position = u_mvp * vec4(a_pos, 1.0); }
"""

LINE_FS = """
#version 120
uniform vec4 u_override;
varying vec4 v_col;
void main() { gl_FragColor = u_override.a > 0.0 ? u_override : v_col; }
"""


def np_to_qimage(img: np.ndarray) -> QImage:
    h, w = img.shape[:2]
    data = np.ascontiguousarray(img, np.uint8).tobytes()
    return QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()


class DrawItem:

    def __init__(self, part_key, corners: np.ndarray, tex_name: str, tint, opaque=False):
        self.part_key = part_key
        self.opaque = opaque
        self.corners = corners
        self.tex_name = tex_name
        self.tint = tint
        self.buffer: QOpenGLBuffer | None = None
        self.texture: QOpenGLTexture | None = None
        self.count = len(corners)


class Viewport(QOpenGLWidget):
    statsChanged = pyqtSignal(str)
    togglePlay = pyqtSignal()

    MODES = ('Texturizado', 'Sólido', 'Normais', 'UV')

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)
        self.gl = None
        self.error = ''
        self.items: list[DrawItem] = []
        self.part_uvs: dict = {}
        self.images: dict[str, np.ndarray] = {}
        self.gl_textures: dict[str, QOpenGLTexture] = {}
        self.pending_rebuild = False
        self.pending_textures = False
        self.frame_data: dict = {}
        self.bone_lines: np.ndarray | None = None
        self.lines_buf: QOpenGLBuffer | None = None
        self.lines_count = 0
        self.grid = None
        self.mode = 0
        self.inspect = False
        self.colors: dict = {}
        self.wireframe = False
        self.show_bones = False
        self.show_grid = True
        self.yaw, self.pitch, self.distance = 25.0, 8.0, 400.0
        self.target = QVector3D(0, 90, 0)
        self.radius = 100.0
        self.floor = 0.0
        self.last = QPoint()

    def set_scene(self, parts: list[dict], images: dict[str, np.ndarray], reframe=True):
        self.scene_parts = parts
        self.images = images
        self.pending_rebuild = True
        self.pending_textures = True
        self.reframe = reframe
        self.update()

    def set_images(self, images: dict[str, np.ndarray]):
        self.images = images
        self.pending_textures = True
        self.update()

    def set_colors(self, colors: dict, inspect: bool):
        self.colors = colors
        self.inspect = inspect
        self.pose_dirty = True
        self.update()

    def set_pose(self, frame_data: dict, bone_lines: np.ndarray | None):
        self.frame_data = frame_data
        self.bone_lines = bone_lines
        self.pose_dirty = True
        self.update()

    def _rebuild(self):
        for it in self.items:
            if it.buffer is not None:
                it.buffer.destroy()
        self.items = []
        self.part_uvs = {}
        for p in getattr(self, 'scene_parts', []):
            self.part_uvs[p['key']] = p['uv'].astype(np.float32)
            faces, fm = p['faces'], p['face_mats']
            for mi in sorted(set(fm.tolist())):
                sel = faces[fm == mi].reshape(-1)
                tex = p['mat_tex'][mi] if mi < len(p['mat_tex']) else ''
                it = DrawItem(p['key'], sel.astype(np.int64), tex, p.get('tint', (1, 1, 1, 1)), p.get('opaque', False))
                buf = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
                buf.setUsagePattern(QOpenGLBuffer.DynamicDraw)
                buf.create()
                buf.bind()
                buf.allocate(len(sel) * 44)
                buf.release()
                it.buffer = buf
                self.items.append(it)
        self.pose_dirty = True

    def _upload_textures(self):
        for t in self.gl_textures.values():
            t.destroy()
        self.gl_textures = {}
        for name, img in self.images.items():
            cutout = img.ndim == 3 and img.shape[2] == 4 and bool((img[..., 3] < 128).any())
            if cutout:
                tex = QOpenGLTexture(np_to_qimage(img).mirrored(False, False), QOpenGLTexture.DontGenerateMipMaps)
                tex.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)
            else:
                tex = QOpenGLTexture(np_to_qimage(img).mirrored(False, False), QOpenGLTexture.GenerateMipMaps)
                tex.setMinMagFilters(QOpenGLTexture.LinearMipMapLinear, QOpenGLTexture.Linear)
            tex.setWrapMode(QOpenGLTexture.Repeat)
            self.gl_textures[name] = tex
        for it in self.items:
            it.texture = self.gl_textures.get(it.tex_name)

    def _upload_pose(self):
        lows, highs = [], []
        tris = verts = 0
        for it in self.items:
            fd = self.frame_data.get(it.part_key)
            if fd is None:
                continue
            pos, nrm = fd
            uv = self.part_uvs[it.part_key]
            c = it.corners
            col = self.colors.get(it.part_key)
            if col is None or len(col) != len(pos):
                col = np.ones((len(pos), 3), np.float32)
            inter = np.concatenate([pos[c], nrm[c], uv[c], col[c]], axis=1).astype(np.float32)
            it.buffer.bind()
            it.buffer.write(0, inter.tobytes(), inter.nbytes)
            it.buffer.release()
            tris += len(c) // 3
        for key, (pos, _) in self.frame_data.items():
            if len(pos):
                lows.append(pos.min(0)); highs.append(pos.max(0))
                verts += len(pos)
        if self.lines_buf is not None:
            self.lines_buf.destroy()
            self.lines_buf = None
        if self.bone_lines is not None and len(self.bone_lines):
            self.lines_buf = self._buffer(self.bone_lines)
            self.lines_count = len(self.bone_lines)
        if lows and getattr(self, 'reframe', False):
            low, high = np.min(lows, 0), np.max(highs, 0)
            center = (low + high) / 2
            self.radius = max(float(np.linalg.norm(high - low)) / 2, 1.0)
            self.floor = min(0.0, float(low[1]))
            self.target = QVector3D(*map(float, center))
            self.distance = self.radius * 2.6
            self.reframe = False
            self._build_grid()
        self.statsChanged.emit(_t("{0} submalhas · {1} triângulos · {2} vértices", len(self.items), tris, verts))
        self.pose_dirty = False

    def _buffer(self, array: np.ndarray) -> QOpenGLBuffer:
        buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        buffer.create()
        buffer.bind()
        arr = np.ascontiguousarray(array, np.float32)
        buffer.allocate(arr.tobytes(), arr.nbytes)
        buffer.release()
        return buffer

    def _build_grid(self):
        if self.gl is None:
            return
        if self.grid is not None:
            self.grid[0].destroy()
        step = 10 ** math.floor(math.log10(max(self.radius, 1.0) / 2))
        count = 20
        extent = step * count
        rows = []
        for i in range(-count, count + 1):
            strong = i == 0
            color = (0.50, 0.50, 0.56, 1.0) if strong else ((0.29, 0.29, 0.32, 1.0) if i % 5 == 0 else (0.22, 0.22, 0.24, 1.0))
            rows.append((i * step, self.floor, -extent, *color))
            rows.append((i * step, self.floor, extent, *color))
            rows.append((-extent, self.floor, i * step, *color))
            rows.append((extent, self.floor, i * step, *color))
        grid = np.asarray(rows, np.float32)
        self.grid = (self._buffer(grid), len(grid))

    def initializeGL(self):
        profile = QOpenGLVersionProfile()
        profile.setVersion(2, 1)
        try:
            self.gl = self.context().versionFunctions(profile)
            self.gl.initializeOpenGLFunctions()
        except Exception as exc:
            self.gl = None
            self.error = _t("OpenGL 2.1 indisponível: {0}", exc)
            return
        self.mesh_program = self._program(MESH_VS, MESH_FS, ('a_pos', 'a_nrm', 'a_uv', 'a_col'))
        self.line_program = self._program(LINE_VS, LINE_FS, ('a_pos', 'a_col'))
        if self.mesh_program is None or self.line_program is None:
            self.gl = None
            return
        self._build_grid()

    def _program(self, vs, fs, attributes):
        program = QOpenGLShaderProgram(self)
        ok = program.addShaderFromSourceCode(QOpenGLShader.Vertex, vs)
        ok = ok and program.addShaderFromSourceCode(QOpenGLShader.Fragment, fs)
        for i, name in enumerate(attributes):
            program.bindAttributeLocation(name, i)
        if not ok or not program.link():
            self.error = _t("Shader do viewport: {0}", program.log())
            return None
        return program

    def _matrices(self):
        aspect = self.width() / max(self.height(), 1)
        projection = QMatrix4x4()
        projection.perspective(40.0, aspect, max(self.distance / 500, 0.05), self.distance * 20 + self.radius * 4)
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        offset = QVector3D(math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw))
        eye = self.target + offset * self.distance
        view = QMatrix4x4()
        view.lookAt(eye, self.target, QVector3D(0, 1, 0))
        return projection * view, eye

    def paintGL(self):
        gl = self.gl
        if gl is None:
            return
        if self.pending_rebuild:
            self._rebuild()
            self.pending_rebuild = False
        if self.pending_textures:
            self._upload_textures()
            self.pending_textures = False
        if getattr(self, 'pose_dirty', False):
            self._upload_pose()
        gl.glClearColor(0.118, 0.118, 0.129, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        gl.glDisable(GL_CULL_FACE)
        gl.glEnable(GL_MULTISAMPLE)
        mvp, eye = self._matrices()

        if self.show_grid and self.grid is not None:
            self._draw_lines(self.grid, mvp)

        program = self.mesh_program
        program.bind()
        program.setUniformValue('u_mvp', mvp)
        program.setUniformValue('u_eye', eye)
        program.setUniformValue('u_mode', self.mode)
        program.setUniformValue('u_tex', 0)
        program.setUniformValue('u_cutoff', 0.30 if self.mode == 0 else -1.0)
        program.setUniformValue('u_inspect', 1 if self.inspect else 0)
        if self.wireframe:
            gl.glEnable(GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(1.0, 1.0)
        opaque = [it for it in self.items if it.tint[3] >= 1.0]
        translucent = [it for it in self.items if it.tint[3] < 1.0]
        for it in opaque:
            self._draw_item(program, it)
        if translucent:
            gl.glEnable(GL_BLEND)
            gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            for it in translucent:
                self._draw_item(program, it)
            gl.glDisable(GL_BLEND)
        gl.glDisable(GL_POLYGON_OFFSET_FILL)
        program.release()

        if self.wireframe:
            self.line_program.bind()
            self.line_program.setUniformValue('u_mvp', mvp)
            self.line_program.setUniformValue('u_override', 0.42, 0.62, 0.95, 1.0)
            gl.glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            for it in self.items:
                it.buffer.bind()
                self.line_program.enableAttributeArray(0)
                self.line_program.setAttributeBuffer(0, GL_FLOAT, 0, 3, 44)
                self.line_program.disableAttributeArray(1)
                gl.glDrawArrays(GL_TRIANGLES, 0, it.count)
                it.buffer.release()
            gl.glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            self.line_program.release()

        if self.show_bones and self.lines_buf is not None:
            gl.glDisable(GL_DEPTH_TEST)
            self._draw_lines((self.lines_buf, self.lines_count), mvp)
            gl.glEnable(GL_DEPTH_TEST)

    def _draw_item(self, program, it):
        it.buffer.bind()
        for location, offset, size in ((0, 0, 3), (1, 12, 3), (2, 24, 2), (3, 32, 3)):
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, GL_FLOAT, offset, size, 44)
        program.setUniformValue('u_opaque', 1 if it.opaque else 0)
        if it.texture is not None:
            it.texture.bind(0)
            program.setUniformValue('u_has_tex', 1)
        else:
            program.setUniformValue('u_has_tex', 0)
        program.setUniformValue('u_tint', *it.tint)
        self.gl.glDrawArrays(GL_TRIANGLES, 0, it.count)
        it.buffer.release()

    def _draw_lines(self, lines, mvp):
        buffer, count = lines
        program = self.line_program
        program.bind()
        program.setUniformValue('u_mvp', mvp)
        program.setUniformValue('u_override', 0.0, 0.0, 0.0, 0.0)
        buffer.bind()
        program.enableAttributeArray(0)
        program.setAttributeBuffer(0, GL_FLOAT, 0, 3, 28)
        program.enableAttributeArray(1)
        program.setAttributeBuffer(1, GL_FLOAT, 12, 4, 28)
        self.gl.glDrawArrays(GL_LINES, 0, count)
        buffer.release()
        program.release()

    def resizeGL(self, w, h):
        if self.gl:
            self.gl.glViewport(0, 0, w, h)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.gl is None and self.error:
            from PyQt5.QtGui import QPainter, QColor
            painter = QPainter(self)
            painter.setPen(QColor('#d4d4d4'))
            painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.error)

    def frame(self):
        self.distance = self.radius * 2.6
        self.update()

    def set_view(self, yaw, pitch):
        self.yaw, self.pitch = yaw, pitch
        self.update()

    def mousePressEvent(self, event):
        self.last = event.pos()

    def mouseMoveEvent(self, event):
        dx, dy = event.x() - self.last.x(), event.y() - self.last.y()
        self.last = event.pos()
        if event.buttons() & Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier:
            self.yaw -= dx * 0.4
            self.pitch = max(-89.0, min(89.0, self.pitch + dy * 0.4))
        elif event.buttons() & (Qt.RightButton | Qt.MiddleButton | Qt.LeftButton):
            scale = self.distance / max(self.height(), 1) * 0.8
            yaw = math.radians(self.yaw)
            right = QVector3D(math.cos(yaw), 0, -math.sin(yaw))
            pitch = math.radians(self.pitch)
            up = QVector3D(-math.sin(pitch) * math.sin(yaw), math.cos(pitch), -math.sin(pitch) * math.cos(yaw))
            self.target += right * (-dx * scale) + up * (dy * scale)
        self.update()

    def wheelEvent(self, event):
        factor = 0.85 ** (event.angleDelta().y() / 120)
        self.distance = max(self.radius * 0.05, min(self.radius * 40, self.distance * factor))
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F:
            self.frame()
        elif Qt.Key_1 <= key <= Qt.Key_4:
            self.mode = key - Qt.Key_1
        elif key == Qt.Key_W:
            self.wireframe = not self.wireframe
        elif key == Qt.Key_B:
            self.show_bones = not self.show_bones
        elif key == Qt.Key_G:
            self.show_grid = not self.show_grid
        elif key == Qt.Key_Space:
            self.togglePlay.emit()
        else:
            super().keyPressEvent(event)
            return
        self.update()

    def grab_image(self) -> QImage:
        return self.grabFramebuffer()
