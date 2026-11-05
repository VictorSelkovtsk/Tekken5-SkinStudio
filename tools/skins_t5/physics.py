import struct
from tools.stages.container import pack

SHARED = 111


def physics(package, bone_count):
    parts = pack(package)
    data = parts[13] if len(parts) > 13 else b''
    extra = max(bone_count-SHARED, 0)
    if data[:3] != b'MOP': return dict(colliders=[], joints={}, status='none', note='Este traje não tem bloco MOP de física.')
    def word(at):
        if at+4 > len(data): raise ValueError('Bloco MOP truncado')
        return struct.unpack_from('<i', data, at)[0]
    at, colliders = 4, []
    while word(at) != -1:
        if at+60 > len(data): raise ValueError('Bloco MOP truncado')
        _, shape, bone = struct.unpack_from('<3I', data, at); values = struct.unpack_from('<12f', data, at+12)
        colliders.append(dict(shape=shape, bone=bone, rotation=values[0:3], position=values[4:7], size=values[8:11]))
        at += 60
    at += 4; records = []
    while at+4 <= len(data) and word(at) not in (-1, -2):
        if at+56 > len(data): raise ValueError('Bloco MOP truncado')
        values = struct.unpack_from('<11f', data, at+4); flags, ident, count = struct.unpack_from('<HHI', data, at+48)
        if count > len(colliders) or at+56+4*count > len(data): raise ValueError('Colisores MOP inválidos')
        records.append(dict(stiffness=values[0], damping=values[1], gravity=values[2], mass=values[3],
                            limits=values[4:8], radius=values[10], flags=flags, id=ident,
                            colliders=list(struct.unpack_from('<%dI' % count, data, at+56))))
        at += 56+4*count
    if not records:
        note = 'Os ossos extras deste traje não têm registro de física.' if extra else 'Este traje não tem ossos de física.'
        return dict(colliders=colliders, joints={}, status='none', note=note)
    if len(records) != extra:
        note = ('O bloco MOP deste traje descreve %d juntas físicas, mas o esqueleto tem %d ossos extras; '
                'não foi possível confirmar quais ossos o jogo simula.' % (len(records), extra))
        return dict(colliders=colliders, joints={}, status='unknown', note=note)
    return dict(colliders=colliders, joints={SHARED+i: r for i, r in enumerate(records)}, status='ok',
                note='%d ossos simulados pelo jogo (bloco MOP do traje base).' % len(records))
