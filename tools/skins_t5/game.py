from pathlib import Path
from collections import defaultdict
import hashlib
import json
import os
import shutil
import struct
from tools.stages.tekken5ps2 import Archive, crypt, unpack_lz

BASE = 0x1f0180
RESERVE = 0x1fe0000
SIGNATURE = b'T5SKINSTUDIOv1\0\0'
NAMES = ['Paul', 'Law', 'Lei', 'King', 'Yoshimitsu', 'Nina', 'Hwoarang',
         'Xiaoyu', 'Christie', 'Jin', 'Julia', 'Kuma / Panda', 'Bryan',
         'Heihachi', 'Kazuya', 'Lee', 'Steve', 'Marduk', 'Mokujin', 'Jack-5',
         'Roger Jr.', 'Anna', 'Wang', 'Ganryu', 'Asuka', 'Bruce', 'Baek',
         'Devil Jin', 'Raven', 'Feng', 'Jinpachi', 'Eddy']


def loader_bytes(archive):
    with archive.path.open('rb') as f:
        offset, size = archive.files['/SLUS_210.59']
        f.seek(offset)
        return f.read(size)


def catalogue(archive):
    loader = loader_bytes(archive)
    rows = [list(struct.unpack_from('<2h8I', archive.main, 0x465b68-BASE+i*36)) for i in range(80)]
    characters = []
    for char in range(32):
        pointer, count, _ = struct.unpack_from('<IHH', archive.main, 0x3abf88-BASE+char*8)
        buf, offset = (archive.main, pointer-BASE) if pointer >= BASE else (loader, pointer-0xff000)
        indices = list(struct.unpack_from('<%dI' % count, buf, offset))
        characters.append({'id': char, 'name': NAMES[char], 'slots': [
            {'index': i, 'ordinal': n, 'resource': 240+11*i, 'label': '%dP' % (n+1)}
            for n, i in enumerate(indices)], 'can_add': count < 5 and char not in (30, 31)})
    return characters, rows


def relz(compressed, desired):
    old = unpack_lz(compressed)
    if len(old) != len(desired):
        raise ValueError('Executable size changed')
    out, group = bytearray(), []
    def emit(literal, payload):
        group.append((literal, payload))
        if len(group) == 7:
            flush()
    def flush():
        if group:
            out.append((1 << len(group)) | sum(int(x[0]) << i for i, x in enumerate(group)))
            for _, payload in group:
                out.extend(payload)
            group.clear()
    pos, cursor = 0, 0
    while compressed[pos]:
        flags = compressed[pos]; pos += 1
        while flags > 1:
            if flags & 1:
                emit(True, desired[cursor:cursor+1]); cursor += 1; pos += 1
            else:
                payload = compressed[pos:pos+2]; pos += 2
                word = int.from_bytes(payload, 'big')
                distance, length = (word & 2047) or 2048, (word >> 11) or 32
                if all(desired[cursor+i] == desired[cursor+i-distance] for i in range(length)):
                    emit(False, payload)
                else:
                    for x in desired[cursor:cursor+length]:
                        emit(True, bytes([x]))
                cursor += length
            flags >>= 1
    flush(); out.append(0)
    if unpack_lz(out) != desired:
        raise ValueError('Executable compression round trip failed')
    return bytes(out)


def patch_address(code, old, new):
    oldhi, oldlo = (old+32768) >> 16, old & 65535
    newhi, newlo = (new+32768) >> 16, new & 65535
    hits = []
    for pos in range(0, 0x1b0000, 4):
        w = struct.unpack_from('<I', code, pos)[0]
        if w >> 26 != 15 or w & 65535 != oldhi:
            continue
        reg = (w >> 16) & 31
        for delta in (4, 8, 12):
            v = struct.unpack_from('<I', code, pos+delta)[0]
            op = v >> 26
            if (v >> 21) & 31 == reg and v & 65535 == oldlo and op in (9, 35, 43, 33, 37):
                struct.pack_into('<I', code, pos, (w & 0xffff0000) | newhi)
                struct.pack_into('<I', code, pos+delta, (v & 0xffff0000) | newlo)
                hits.append(BASE+pos)
                break
    if not hits:
        raise ValueError('Native address has no verified references: %x' % old)
    return hits


def iop(op, rs, rt, imm):
    return (op << 26) | (rs << 21) | (rt << 16) | (imm & 65535)


def slot_patch(archive, main, additions, entries, checksums):
    chars, rows = catalogue(archive)
    lists = [[s['index'] for s in c['slots']] for c in chars]
    mappings = []
    for item in additions:
        char, base, resource = item['character'], item['base_index'], item['resource']
        if char in (30, 31) or len(lists[char]) >= 5 or base not in lists[char]:
            raise ValueError('No native slot available for this character/base costume')
        row = rows[base].copy()
        row[0], row[1], row[-1] = char, len(lists[char]), 0x218ac0
        lists[char].append(len(rows)); rows.append(row); mappings.append((base, resource))
        for idx in lists[char]:
            rows[idx][-1] = 0x218ac0
    segment = bytearray(64)
    segment[:16] = SIGNATURE
    def allocate(data):
        segment.extend(b'\0' * (-len(segment) % 16))
        address = RESERVE+len(segment); segment.extend(data)
        return address
    table = allocate(b''.join(struct.pack('<2h8I', *r) for r in rows))
    for char, indices in enumerate(lists):
        address = allocate(struct.pack('<%dI' % len(indices), *indices))
        struct.pack_into('<IHH', main, 0x3abf88-BASE+char*8, address, len(indices), 0)
    map_address = allocate(b''.join(struct.pack('<II', *x) for x in mappings))
    catalog_address = allocate(b''.join(struct.pack('<II', *x) for x in entries))
    checksum_address = allocate(struct.pack('<%dI' % len(checksums), *checksums))
    hits = {'costumes': patch_address(main, 0x465b68, table),
            'resources': patch_address(main, 0x46b730, catalog_address),
            'resource_sizes': patch_address(main, 0x46b734, catalog_address+4),
            'checksums': patch_address(main, 0x46e9b8, checksum_address)}
    bounds = []
    for address in range(0x218ae8, 0x219190, 4):
        pos = address-BASE; word = struct.unpack_from('<I', main, pos)[0]
        if word >> 26 in (10, 11) and word & 65535 == 80:
            struct.pack_into('<I', main, pos, (word & 0xffff0000) | len(rows)); bounds.append(address)
    struct.pack_into('<I', main, 0x2190f8-BASE, iop(15, 0, 2, (table+24+32768) >> 16))
    struct.pack_into('<I', main, 0x219100-BASE, iop(35, 2, 2, table+24))
    struct.pack_into('<I', main, 0x24c7ec-BASE, iop(9, 0, 6, 5))
    original_branch = struct.unpack_from('<I',main,0x24c7f0-BASE)[0]
    struct.pack_into('<I',main,0x24c7f0-BASE,(original_branch & ~(31<<21)) | (21<<21))
    resource_bounds = []
    for pos in range(0, 0x1b0000, 4):
        word = struct.unpack_from('<I', main, pos)[0]
        if word >> 26 in (10, 11) and word & 65535 == 1571:
            struct.pack_into('<I', main, pos, (word & 0xffff0000) | len(entries)); resource_bounds.append(BASE+pos)
    code, labels, branches = [], {}, []
    def emit(w): code.append(w)
    def li(reg, value):
        emit(iop(15, 0, reg, value >> 16)); emit(iop(13, reg, reg, value))
    def label(name): labels[name] = len(code)
    def branch(op, rs, rt, target): branches.append((len(code), op, rs, rt, target)); emit(0)
    emit(iop(11, 4, 8, 80)); branch(5, 8, 0, 'original'); emit(0)
    emit(iop(11, 4, 8, len(rows))); branch(4, 8, 0, 'invalid'); emit(0)
    li(8, 0x462f98); emit((5 << 16) | (9 << 11) | (2 << 6))
    emit((8 << 21) | (9 << 16) | (8 << 11) | 0x21)
    emit(iop(37, 8, 9, 2)); emit(iop(9, 0, 10, 2))
    branch(5, 9, 10, 'original'); emit(0)
    emit(iop(9, 4, 9, -80)); emit((9 << 16) | (9 << 11) | (3 << 6))
    li(10, map_address); emit((9 << 21) | (10 << 16) | (9 << 11) | 0x21)
    emit(iop(33, 8, 10, 0)); emit(iop(9, 0, 11, 10))
    branch(5, 10, 11, 'alias'); emit(0)
    emit(0x03e00008); emit(iop(35, 9, 2, 4))
    label('alias'); emit(iop(35, 9, 4, 0))
    label('original')
    emit(iop(0, 0, 0, 0) | (5 << 16) | (5 << 11) | (2 << 6))
    emit(iop(9, 0, 2, 1)); emit(0x08000000 | (0x1f09c0 >> 2)); emit(0)
    label('invalid'); emit(0x03e00008); emit(iop(9, 0, 2, -1))
    for pos, op, rs, rt, target in branches:
        code[pos] = iop(op, rs, rt, labels[target]-pos-1)
    hook = allocate(struct.pack('<%dI' % len(code), *code))
    if struct.unpack_from('<II', main, 0x1f09b8-BASE) != (0x00052880, 0x24020001):
        raise ValueError('Resource hook fingerprint differs')
    struct.pack_into('<II', main, 0x1f09b8-BASE, 0x08000000 | (hook >> 2), 0)
    struct.pack_into('<I', main, 0x2f0544-BASE, iop(15, 0, 2, RESERVE >> 16))
    struct.pack_into('<I', main, 0x2f054c-BASE, iop(13, 2, 2, 0))
    struct.pack_into('<8I', segment, 16, 1, len(rows), catalog_address, checksum_address,
                     len(entries), table, hook, len(segment))
    if len(segment) > 65536:
        raise ValueError('Mod metadata exceeds reserved ELF segment')
    segment.extend(b'\0' * (65536-len(segment)))
    loader = bytearray(loader_bytes(archive))
    phoff = struct.unpack_from('<I', loader, 28)[0]
    if struct.unpack_from('<H', loader, 44)[0] != 5 or any(loader[phoff+160:phoff+192]):
        raise ValueError('Unsupported ELF program headers')
    heap_size = RESERVE-0x1bca460
    struct.pack_into('<I', loader, 0x100158-0xff000, iop(15, 0, 5, (heap_size+32768) >> 16))
    struct.pack_into('<I', loader, 0x100160-0xff000, iop(9, 5, 5, heap_size))
    loader.extend(b'\0' * (-len(loader) % 4096)); offset = len(loader)
    struct.pack_into('<8I', loader, phoff+160, 1, offset, RESERVE, RESERVE, len(segment), len(segment), 7, 4096)
    struct.pack_into('<H', loader, 44, 6); loader.extend(segment)
    return bytes(loader), {'segment': hex(RESERVE), 'costumes': len(rows), 'references': hits,
                           'costume_bounds': bounds, 'resource_bounds': resource_bounds,
                           'unlocks_original_extra_costumes': sorted({x['character'] for x in additions})}


def directory_records(stream):
    stream.seek(16*2048); pvd = stream.read(2048); result = {}
    def visit(record, prefix=''):
        sector, size = struct.unpack_from('<I', record, 2)[0], struct.unpack_from('<I', record, 10)[0]
        stream.seek(sector*2048); data = stream.read(size); pos = 0
        while pos < size:
            length = data[pos]
            if not length: pos = (pos//2048+1)*2048; continue
            row = data[pos:pos+length]; name = row[33:33+row[32]]
            absolute = sector*2048+pos; pos += length
            if name in (b'\0', b'\1'): continue
            name = prefix+'/'+name.decode('ascii').split(';')[0]
            if row[25] & 2: visit(row, name)
            else: result[name] = absolute
    visit(pvd[156:190]); return result


def build_iso(source, destination, mods, progress=lambda s: None):
    source, destination = Path(source), Path(destination)
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('Escolha um arquivo ISO novo; a ferramenta não sobrescreve imagens.')
    archive = Archive(source)
    main = bytearray(archive.main); entries = archive.entries.copy(); checks = list(archive.checksums)
    additions, resources, used = [], [], set()
    cursor = (archive.size+2047)//2048*2048
    for item in mods:
        base = int(item['base_index']); char = int(item['character'])
        if not 0 <= base < 79:
            raise ValueError('Invalid base costume')
        data = Path(item['asset']).read_bytes()
        if len(data) % 4: raise ValueError('Native package must be word aligned')
        if item['mode'] == 'add':
            rid = len(entries); entries.append((0, 0)); checks.append(0)
            additions.append(dict(character=char, base_index=base, resource=rid))
        elif item['mode'] == 'replace': rid = 240+11*base
        else: raise ValueError('Invalid slot mode')
        if rid in used: raise ValueError('Duas skins substituem a mesma roupa. Desative uma delas.')
        used.add(rid); entries[rid] = (cursor//2048, len(data))
        checks[rid] = sum(x[0] for x in struct.iter_unpack('<I', data)) & 0xffffffff
        resources.append((rid, cursor, data)); cursor += (len(data)+2047)//2048*2048
    replacement, slot_report = {}, None
    if additions:
        replacement['/SLUS_210.59'], slot_report = slot_patch(archive, main, additions, entries, checks)
    else:
        for rid, _, _ in resources:
            struct.pack_into('<II', main, 0x27b5b0+rid*8, *entries[rid])
            struct.pack_into('<I', main, 0x27e838+rid*4, checks[rid])
    with source.open('rb') as f:
        for name in ('/TK5DATA3.BIN', '/TK5DATA5.BIN'):
            offset, size = archive.files[name]; f.seek(offset); header = bytearray(f.read(84))
            start, length = struct.unpack_from('<II', header, 44)
            f.seek(offset+start); compressed = f.read(length)
            if unpack_lz(compressed) != archive.main: raise ValueError('Executable backup differs')
            packed = relz(compressed, main)
            append_offset = (size+2047)//2048*2048
            struct.pack_into('<II', header, 44, append_offset, len(packed))
            replacement[name] = (bytes(header), append_offset, packed)
    partial = destination.with_suffix(destination.suffix+'.partial')
    if partial.exists(): raise ValueError('Existe uma construção parcial neste destino; escolha outro nome.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open('rb') as src, partial.open('xb') as dst:
            records = directory_records(src)
            first = min(x[0] for x in archive.files.values())
            src.seek(0); dst.write(src.read(first)); extents = {}
            total = len(archive.files)
            for index, (name, (oldoff, oldsize)) in enumerate(sorted(archive.files.items(), key=lambda x:x[1][0])):
                progress('Gravando %s (%d/%d)' % (name[1:], index+1, total))
                dst.write(b'\0' * (-dst.tell()%2048)); start = dst.tell()
                value = replacement.get(name)
                if isinstance(value, bytes): dst.write(value)
                else:
                    src.seek(oldoff); remaining = oldsize
                    while remaining:
                        data = src.read(min(8*1024*1024, remaining))
                        if not data: raise ValueError('Source image truncated')
                        dst.write(data); remaining -= len(data)
                    if name == '/TK5DATA1.BIN':
                        for rid, offset, data in resources:
                            dst.write(b'\0'*(start+offset-dst.tell())); dst.write(crypt(data, rid))
                        dst.write(b'\0'*(start+cursor-dst.tell()))
                    elif isinstance(value, tuple):
                        header, offset, data = value
                        dst.write(b'\0'*(start+offset-dst.tell())); dst.write(data)
                        end = dst.tell(); dst.seek(start); dst.write(header); dst.seek(end)
                extents[name] = (start, dst.tell()-start)
            dst.write(b'\0'*(-dst.tell()%2048)); sectors = dst.tell()//2048
            for name, (start, size) in extents.items():
                dst.seek(records[name]+2); dst.write(struct.pack('<I',start//2048)+struct.pack('>I',start//2048))
                dst.seek(records[name]+10); dst.write(struct.pack('<I',size)+struct.pack('>I',size))
            dst.seek(16*2048+80); dst.write(struct.pack('<I',sectors)+struct.pack('>I',sectors))
        progress('Verificando recursos e executável da ISO')
        verified = read_studio_iso(partial)
        if verified.main != main: raise ValueError('Executable image mismatch')
        for rid, _, data in resources:
            if verified.read(rid) != data: raise ValueError('Resource verification failed: %d' % rid)
        partial.rename(destination)
    except Exception:
        if partial.exists(): partial.unlink()
        raise
    report = {'source': str(source), 'output': str(destination), 'mods': mods,
              'resources': [x[0] for x in resources], 'slot_patch': slot_report,
              'verification': 'ISO reopened, native checksums and all installed assets match',
              'game_validation': 'pending'}
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def read_studio_iso(path):
    try: return Archive(path)
    except ValueError as error:
        if 'fingerprint' not in str(error): raise
    path = Path(path)
    with path.open('rb') as f:
        records = directory_records(f); files = {}
        for name, pos in records.items():
            f.seek(pos); row = f.read(34)
            files[name] = (struct.unpack_from('<I',row,2)[0]*2048,struct.unpack_from('<I',row,10)[0])
        off, size = files['/SLUS_210.59']; f.seek(off); loader = f.read(size)
        phoff = struct.unpack_from('<I',loader,28)[0]
        if struct.unpack_from('<H',loader,44)[0] != 6: raise ValueError('Unknown modified loader')
        ph = struct.unpack_from('<8I',loader,phoff+160)
        if ph[0] != 1 or ph[2:4] != (RESERVE, RESERVE) or ph[4:6] != (65536,65536):
            raise ValueError('Unknown mod segment')
        segment = loader[ph[1]:ph[1]+65536]
        if segment[:16] != SIGNATURE: raise ValueError('Mod segment signature missing')
        normalized = bytearray(loader[:689304]); struct.pack_into('<H',normalized,44,5)
        normalized[phoff+160:phoff+192] = b'\0'*32
        struct.pack_into('<I',normalized,0x100158-0xff000,0x3c050000)
        struct.pack_into('<I',normalized,0x100160-0xff000,0x24a5ffff)
        if hashlib.sha256(normalized).hexdigest() != '3ac56eda66cbd0b3fff22ccac961449a4f2690842c6c0b9839ab450c206fc7df':
            raise ValueError('Modified loader normalization failed')
        _, _, entryaddr, sumaddr, count, _, _, _ = struct.unpack_from('<8I',segment,16)
        if not 1571 <= count <= 1731: raise ValueError('Invalid expanded resource count')
        result = Archive.__new__(Archive); result.path = path; result.files = files
        result.entries = list(struct.iter_unpack('<II',segment[entryaddr-RESERVE:entryaddr-RESERVE+count*8]))
        result.checksums = struct.unpack_from('<%dI'%count,segment,sumaddr-RESERVE)
        result.base,result.size = files['/TK5DATA1.BIN']
        for sector,n in result.entries:
            if n not in (0,0xffffffff) and sector*2048+n > result.size: raise ValueError('Resource outside mod archive')
        base,_ = files['/TK5DATA3.BIN']; f.seek(base); header = f.read(84)
        offset,n = struct.unpack_from('<II',header,44); f.seek(base+offset); result.main = unpack_lz(f.read(n))
        return result
