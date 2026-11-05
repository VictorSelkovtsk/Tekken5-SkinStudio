from pathlib import Path
import hashlib
import struct
import numpy as np


def unpack_lz(data):
    out = bytearray()
    pos = 0
    while pos < len(data):
        flags = data[pos]
        pos += 1
        if flags == 0:
            return bytes(out)
        while flags > 1:
            if flags & 1:
                out.append(data[pos])
                pos += 1
            else:
                value = int.from_bytes(data[pos:pos + 2], 'big')
                pos += 2
                distance = (value & 2047) or 2048
                length = (value >> 11) or 32
                if distance > len(out):
                    raise ValueError('Invalid compressed back reference')
                for _ in range(length):
                    out.append(out[-distance])
            flags >>= 1
    raise ValueError('Missing compressed stream terminator')


def crypt(data, identifier):
    result = bytearray(data)
    multipliers, offsets = [], []
    mul, off = 1, 0
    for _ in range(512):
        multipliers.append(mul)
        offsets.append(off)
        mul, off = (mul * 5) & 0xffffffff, (off * 5 + 3) & 0xffffffff
    keys = (np.asarray(multipliers, dtype=np.uint64) * identifier +
            np.asarray(offsets, dtype=np.uint64)).astype('<u4')
    words = np.frombuffer(result, '<u4', len(result) // 4)
    words ^= np.resize(keys, len(words))
    tail = len(words) * 4
    if tail < len(result):
        key = int(keys[len(words) % 512]).to_bytes(4, 'little')
        for j in range(len(result) - tail):
            result[tail + j] ^= key[j]
    return bytes(result)


class Archive:
    def __init__(self, iso):
        self.path = Path(iso)
        with self.path.open('rb') as f:
            f.seek(16 * 2048)
            pvd = f.read(2048)
            if pvd[:7] != b'\x01CD001\x01':
                raise ValueError('Expected ISO9660')
            self.files = {}
            def directory(record, prefix=''):
                sector = struct.unpack_from('<I', record, 2)[0]
                size = struct.unpack_from('<I', record, 10)[0]
                f.seek(sector * 2048)
                data = f.read(size)
                pos = 0
                while pos < len(data):
                    n = data[pos]
                    if not n:
                        pos = (pos // 2048 + 1) * 2048
                        continue
                    row = data[pos:pos + n]
                    pos += n
                    name = row[33:33 + row[32]]
                    if name in (b'\0', b'\1'):
                        continue
                    name = prefix + '/' + name.decode('ascii').split(';')[0]
                    if row[25] & 2:
                        directory(row, name)
                    else:
                        self.files[name] = (struct.unpack_from('<I', row, 2)[0] * 2048,
                                            struct.unpack_from('<I', row, 10)[0])
            directory(pvd[156:190])
            off, size = self.files['/SLUS_210.59']
            f.seek(off)
            loader = f.read(size)
            if hashlib.sha256(loader).hexdigest() != '3ac56eda66cbd0b3fff22ccac961449a4f2690842c6c0b9839ab450c206fc7df':
                raise ValueError('Unsupported Tekken 5 executable fingerprint')
            base, _ = self.files['/TK5DATA3.BIN']
            f.seek(base)
            header = f.read(84)
            off, size = struct.unpack_from('<II', header, 4 + 5 * 8)
            f.seek(base + off)
            self.main = unpack_lz(f.read(size))
        self.entries = list(struct.iter_unpack('<II', self.main[0x27b5b0:0x27b5b0 + 1571 * 8]))
        self.checksums = struct.unpack_from('<1571I', self.main, 0x27e838)
        self.base, self.size = self.files['/TK5DATA1.BIN']
        for sector, size in self.entries:
            if size not in (0, 0xffffffff) and sector * 2048 + size > self.size:
                raise ValueError('Resource outside archive')

    def read(self, identifier):
        sector, size = self.entries[identifier]
        if size in (0, 0xffffffff):
            return b''
        with self.path.open('rb') as f:
            f.seek(self.base + sector * 2048)
            data = crypt(f.read(size), identifier)
        if len(data) != size:
            raise ValueError('Truncated resource')
        checksum = int(np.frombuffer(data, '<u4', len(data) // 4).sum()) & 0xffffffff
        if checksum != self.checksums[identifier]:
            raise ValueError('Resource checksum mismatch: ' + str(identifier))
        return data
