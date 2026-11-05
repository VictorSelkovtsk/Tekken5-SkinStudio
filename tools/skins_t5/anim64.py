import struct

import numpy as np

ANGLE = np.float32(0.000095873802)
END = -268435456
_TABLE = {1: (2, 1), 2: (2, -4), 3: (4, 5), 4: (4, -20), 5: (6, 21), 6: (6, -84), 7: (8, 85),
          8: (8, -340), 9: (10, 341), 10: (10, -1364), 11: (12, 1365), 12: (12, -5460), 13: (16, 0)}


def is_short(kind):
    return 4 <= kind <= 7


class BodyBank:

    def __init__(self, data):
        self.data = bytes(data)
        kind, count, tracks = struct.unpack_from('<3H', self.data)
        if kind != 100 or not 0 < count <= 16384 or not 0 < tracks < 256:
            raise ValueError('Banco de animação inválido')
        table = (6 + tracks * 2 + 3) & ~3
        self.types = struct.unpack_from('<%dH' % tracks, self.data, 6)
        self.offsets = struct.unpack_from('<%dI' % count, self.data, table)
        head = table + 4 * count
        if any(o < head or o + 4 > len(self.data) for o in self.offsets):
            raise ValueError('Clipe fora do banco')
        unique = sorted(set(self.offsets))
        self.ends = dict(zip(unique, unique[1:] + [len(self.data)]))

    def __len__(self):
        return len(self.offsets)

    def clip(self, index):
        o = self.offsets[index]
        return struct.pack('<2H', 100, len(self.types)) + struct.pack(
            '<%dH' % len(self.types), *self.types) + self.data[o:]

    def duration(self, index):
        return struct.unpack_from('<H', self.data, self.offsets[index])[0]


class _Bits:
    __slots__ = ('data', 'at', 'rem', 'avail')

    def __init__(self, data, at, rem):
        self.data, self.at, self.rem, self.avail = data, at, rem, 2

    def read(self, n):
        avail, rem = self.avail, self.rem
        if avail < n:
            count = ((n - avail - 1) >> 3) + 1
            avail += 8 * count
            for _ in range(count):
                byte = self.data[self.at] if self.at < len(self.data) else 0
                rem = ((rem << 8) | byte) & 0xffffffff
                self.at += 1
        left = avail - n
        self.avail = left
        self.rem = rem & ~(0xffffffff << left) & 0xffffffff
        return (((rem >> left) + 32768) & 0xffff) - 32768


def _value(bits, state):
    if state[0]:
        state[0] -= 1
        x1, x2 = state[1], state[2]
        if not x1:
            return 0
        return END if x1 == 99 else x2 + bits.read(x1)
    code = bits.read(4)
    if code == 0:
        state[1] = state[2] = 0
        return 0
    if code in _TABLE:
        x1, x2 = _TABLE[code]
        state[1], state[2] = x1, x2
        return bits.read(x1) + x2
    if code == 14:
        state[0] = bits.read(4) - 1
        x1, x2 = state[1], state[2]
        if not x1:
            return 0
        return END if x1 == 99 else x2 + bits.read(x1)
    state[1], state[2] = 99, 0
    return END


def _s16(v):
    return ((int(v) + 32768) & 0xffff) - 32768


def _s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def quaternions(frames, types):
    f = np.asarray(frames, np.float64)
    out = np.zeros(f.shape[:2] + (4,), np.float64)
    for j, t in enumerate(types):
        v0, v1, v2 = f[:, j, 0], f[:, j, 1], f[:, j, 2]
        if is_short(t):
            axis = np.stack([np.cos(v0) * np.sin(v1), -np.sin(v0), np.cos(v0) * np.cos(v1)], -1)
            out[:, j, :3] = axis * np.sin(v2 / 2)[:, None]
            out[:, j, 3] = np.cos(v2 / 2)
        else:
            out[:, j, :3] = f[:, j]
            out[:, j, 3] = 1
    return out


def decode(clip):
    kind, tracks = struct.unpack_from('<2H', clip)
    if kind != 100 or not 0 < tracks < 256:
        raise ValueError('Clipe 0x64 inválido')
    types = struct.unpack_from('<%dH' % tracks, clip, 4)
    post = 4 + 2 * tracks
    length = struct.unpack_from('<H', clip, post)[0]
    shift = clip[post + 2] & 0x7f
    fshift = clip[post + 3]
    nfloat = struct.unpack_from('<H', clip, post + 4)[0]
    scales = struct.unpack_from('<%df' % nfloat, clip, post + 6) if nfloat else ()
    if not 0 < length <= 10000:
        raise ValueError('Duração inválida')
    at = post + 2 * ((4 * nfloat + 6) // 2)
    base = np.zeros((tracks, 3), np.float32)
    start = np.zeros((tracks, 3), np.int64)
    for i, t in enumerate(types):
        if is_short(t):
            v = struct.unpack_from('<3h', clip, at)
            at += 6
            base[i] = np.asarray(v, np.float32) * ANGLE
            start[i] = [x >> shift for x in v]
        else:
            base[i] = struct.unpack_from('<3f', clip, at)
            at += 12
    anim = at
    frames = np.empty((length, tracks, 3), np.float32)
    frames[0] = base
    fscale = [None] * tracks
    k = 0
    for i, t in enumerate(types):
        if not is_short(t):
            fscale[i] = scales[k]
            k += 1
    blocks = max(1, struct.unpack_from('<I', clip, anim)[0] // 4)
    for frame in range(1, length):
        key, sub = frame >> 4, frame & 15
        if key >= blocks:
            key, sub = blocks - 1, frame - 16 * (blocks - 1)
        block = struct.unpack_from('<I', clip, anim + 4 * key)[0]
        ptr = anim + block
        state = [0, 0, 0]
        acc = start.copy()
        for j, t in enumerate(types):
            short = is_short(t)
            for axis in range(3):
                head = clip[ptr]
                bits = _Bits(clip, ptr + 1, head & 3)
                state[0] = 0
                v = _s16(acc[j, axis] + _value(bits, state))
                if sub:
                    total = 0
                    for _ in range(sub):
                        r = _value(bits, state)
                        if r == END:
                            break
                        total = _s32(total + r)
                        v = _s16(v + total)
                if short:
                    frames[frame, j, axis] = np.float32(_s32(v << shift)) * ANGLE
                else:
                    frames[frame, j, axis] = np.float32(np.float32(_s32(v << fshift)) * np.float32(fscale[j])) + base[j, axis]
                ptr += head >> 2
    return frames
