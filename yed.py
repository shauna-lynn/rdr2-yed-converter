"""Independent, preservation-oriented horse YED/XML converter. Python stdlib only."""
import argparse
import base64
import hashlib
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zlib

LIMIT = 32 * 1024 * 1024
VIRTUAL = 0x50000000
# Operand sizes measured in the inspected horse instruction streams, not a
# complete opcode specification. Unknown opcodes fail instead of losing bytes.
EMPTY = {0, 1, 3, 4, 15, 16, 17, 24, 28, 29, 30, 33, 46, 47, 48,
         49, 50, 51, 53, 54, 57, 59, 60, 61, 63, 72, 75, 79, 93, 101, 106}
SIZES = {code: (0, 0) for code in EMPTY}
SIZES.update({code: (0, 8) for code in
              (6, 7, 8, 9, 10, 32, 36, 38, 39, 40, 41, 42, 66, 67, 69,
               87, 103, 109, 113, 114)})
SIZES.update({5: (0, 4), 11: (16, 0), 82: (0, 4), 92: (32, 0),
              98: (80, 0), 116: (0, 76)})
BRANCHES = {43, 44, 112}  # 0x70 has the same relative layout in this corpus.
SIZES.update({code: (0, 12) for code in BRANCHES | {94, 96, 97}})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unpack(fmt, data, at=0):
    require(at >= 0 and at + struct.calcsize('<' + fmt) <= len(data),
            'Truncated field or pointer outside payload')
    return struct.unpack_from('<' + fmt, data, at)


def number(text):
    return int(text, 0)


def floats(text, count):
    values = [float(v) for v in text.split()]
    require(len(values) == count and all(math.isfinite(v) for v in values),
            f'Expected {count} finite floats')
    return struct.pack('<' + 'f' * count, *values)


def float_text(data):
    values = unpack('f' * (len(data) // 4), data)
    require(all(math.isfinite(v) for v in values), 'Non-finite float unsupported')
    return ' '.join(repr(v) for v in values)


def read_file(path):
    require(path.stat().st_size <= LIMIT, 'Input exceeds 32 MiB limit')
    return path.read_bytes()


def decode(binary):
    require(len(binary) >= 16 and binary[:4] == b'RSC8', 'Expected RSC8 file')
    control, virtual, physical = unpack('III', binary, 4)
    compression = ((control >> 8) & 31) + 1
    require(compression == 1,
            f'Compression {compression} unsupported. Native Oodle input is not '
            'supported; use a DEFLATE RSC8 copy. No external DLL is loaded.')
    require(control >> 13 == 0, 'Signed/encrypted/unknown container flags unsupported')
    require((physical & ~15) == 0, 'Physical resource pages unsupported')
    size = virtual & ~15
    require(112 <= size <= LIMIT, 'Invalid decoded resource size')
    inflater = zlib.decompressobj(-15)
    data = inflater.decompress(binary[16:], size + 1)
    require(len(data) == size and inflater.eof and not inflater.unused_data
            and not inflater.unconsumed_tail, 'Invalid DEFLATE size or trailing data')
    return binary[:16], bytearray(data)


def encode(header, data):
    require(len(data) <= LIMIT and len(data) % 16 == 0, 'Invalid payload size')
    result = bytearray(header)
    old_size = unpack('I', result, 8)[0]
    struct.pack_into('<I', result, 8, len(data) | (old_size & 15))
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return bytes(result) + compressor.compress(data) + compressor.flush()


def pointer(data, field, length=1):
    value = unpack('Q', data, field)[0]
    offset = value - VIRTUAL
    require(value != 0 and 0 <= offset <= len(data) - length,
            f'Invalid virtual pointer at 0x{field:x}')
    return offset


def array(data, field, stride):
    count, capacity = unpack('HH', data, field + 8)
    require(capacity == 0 or count <= capacity, 'Array count exceeds capacity')
    offset = pointer(data, field, count * stride) if count else 0
    return offset, count


def string(data, field):
    count = unpack('H', data, field + 8)[0]
    pos = pointer(data, field, count + 1)
    require(data[pos + count] == 0, 'String missing terminator')
    return bytes(data[pos:pos + count]).decode('utf-8')


def expressions(data):
    # All inspected rebuilt files use one virtual page and no physical pages.
    block_map = pointer(data, 8, 10)
    require(data[block_map + 8:block_map + 10] == b'\x01\x00',
            'Only one virtual page/no physical pages is currently supported')
    buckets, count = array(data, 0x48, 8)
    seen_entries, seen_expressions, result = set(), set(), []
    for i in range(count):
        field = buckets + i * 8
        while unpack('Q', data, field)[0]:
            entry = pointer(data, field, 32)
            require(entry not in seen_entries, 'Cyclic or shared dictionary entry')
            seen_entries.add(entry)
            exp = pointer(data, entry + 8, 160)
            require(exp not in seen_expressions, 'Shared expression unsupported')
            seen_expressions.add(exp)
            result.append((string(data, exp + 0x70), exp))
            field = entry + 16
    require(len(result) == unpack('I', data, 0x58)[0], 'Dictionary count mismatch')
    require(len({name for name, _ in result}) == len(result), 'Duplicate names')
    return result


def split_ops(a, b, codes):
    rows, x, y = [], 0, 0
    for code in codes:
        if code == 80:
            size, count = unpack('II', a, x)
            require(size == 32 + 56 * count + 8 * (count % 2),
                    'Invalid 0x50 operand length')
            lengths = size, 0
        else:
            require(code in SIZES, f'Unsupported opcode 0x{code:02x}')
            lengths = SIZES[code]
        na, nb = lengths
        require(x + na <= len(a) and y + nb <= len(b), 'Truncated operands')
        rows.append((code, bytes(a[x:x+na]), bytes(b[y:y+nb]), x, y))
        x += na
        y += nb
    require(x == len(a) and y == len(b), 'Unconsumed instruction operands')
    require(rows and rows[-1][0] == 0, 'Stream must end with opcode 0')
    for i, (code, aa, bb, x, y) in enumerate(rows):
        if code in BRANCHES:
            dx, dy, steps = unpack('iii', bb)
            target = i + 1 + steps
            require(0 <= target < len(rows), 'Branch target outside stream')
            require((dx, dy) == (rows[target][3] - x, rows[target][4] - y - 12),
                    'Branch operand displacements do not match target')
    return rows


def stream(data, field):
    pos = pointer(data, field, 16)
    name, na, nb, nc, depth = unpack('IIIHH', data, pos)
    end = pos + 16 + na + nb + nc
    require(end <= len(data), 'Stream extends beyond payload')
    a = data[pos + 16:pos + 16 + na]
    b = data[pos + 16 + na:pos + 16 + na + nb]
    codes = data[pos + 16 + na + nb:end]
    return pos, end - pos, name, depth, split_ops(a, b, codes)


def op_xml(parent, i, row):
    code, a, b, _, _ = row
    op = ET.SubElement(parent, 'Op', id=f'i{i}', code=f'0x{code:02x}')
    if code in BRANCHES:
        op.set('target', f'i{i + 1 + unpack("iii", b)[2]}')
    elif code == 5:
        op.set('value', float_text(b))
    elif code == 11:
        op.set('value', float_text(a))
    elif code == 82:
        op.set('slot', str(unpack('I', b)[0]))
    elif code == 80:
        _, count, u1, u2 = unpack('IIII', a)
        op.set('u1', str(u1))
        op.set('u2', str(u2))
        op.set('bias', float_text(a[16:32]))
        for j in range(count):
            vectors = a[32 + j * 48:80 + j * 48]
            indices = unpack('4H', a, 32 + count * 48 + j * 8)
            ET.SubElement(op, 'Term', indices=' '.join(map(str, indices)),
                          vectors=float_text(vectors))
        if count % 2:
            op.set('padding', a[-8:].hex())
    else:
        op.set('a', a.hex())
        op.set('b', b.hex())


def export_xml(binary):
    _, data = decode(binary)
    root = ET.Element('HorseYed', version='1', name=string(data, 0x38))
    # Retain opaque metadata, properties, springs and original allocation bytes.
    ET.SubElement(root, 'Base', sha256=hashlib.sha256(binary).hexdigest()).text = (
        base64.b64encode(binary).decode('ascii'))
    for name, exp in expressions(data):
        element = ET.SubElement(root, 'Expression', name=name,
                                registers=str(unpack('H', data, exp + 0x8e)[0]))
        tracks = ET.SubElement(element, 'Tracks')
        pos, count = array(data, exp + 0x40, 4)
        for j in range(count):
            bone, track, kind = unpack('HBB', data, pos + j * 4)
            ET.SubElement(tracks, 'Track', bone=str(bone), track=str(track),
                          flags=str(kind))
        slots, count = array(data, exp + 0x30, 8)
        for j in range(count):
            _, _, name_hash, depth, rows = stream(data, slots + j * 8)
            child = ET.SubElement(element, 'Stream', hash=f'0x{name_hash:08x}',
                                  depth=str(depth))
            for i, row in enumerate(rows):
                op_xml(child, i, row)
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def assemble(element):
    chunks, labels, x, y = [], {}, 0, 0
    for op in element:
        require(op.tag == 'Op', 'Expected Op element')
        label = op.attrib['id']
        require(label not in labels, 'Duplicate instruction label')
        labels[label] = len(chunks), x, y
        code = number(op.attrib['code'])
        if code in BRANCHES:
            a, b = b'', bytes(12)
        elif code == 5:
            a, b = b'', floats(op.attrib['value'], 1)
        elif code == 11:
            a, b = floats(op.attrib['value'], 4), b''
        elif code == 82:
            a, b = b'', struct.pack('<I', number(op.attrib['slot']))
        elif code == 80:
            count = len(op)
            size = 32 + 56 * count + 8 * (count % 2)
            a = struct.pack('<IIII', size, count, number(op.attrib['u1']),
                            number(op.attrib['u2'])) + floats(op.attrib['bias'], 4)
            for term in op:
                require(term.tag == 'Term', 'Expected Term element')
                a += floats(term.attrib['vectors'], 12)
            for term in op:
                indices = [number(v) for v in term.attrib['indices'].split()]
                require(len(indices) == 4, 'Expected four register indices')
                a += struct.pack('<4H', *indices)
            if count % 2:
                padding = bytes.fromhex(op.get('padding', '00' * 8))
                require(len(padding) == 8, 'Expected eight padding bytes')
                a += padding
            b = b''
        else:
            require(code in SIZES, f'Unsupported opcode 0x{code:02x}')
            a, b = bytes.fromhex(op.attrib['a']), bytes.fromhex(op.attrib['b'])
            require((len(a), len(b)) == SIZES[code], 'Incorrect operand sizes')
        chunks.append([code, a, b, x, y, op.get('target')])
        x += len(a)
        y += len(b)
    for i, row in enumerate(chunks):
        if row[0] in BRANCHES:
            require(row[5] in labels, 'Missing branch target label')
            dest, dx, dy = labels[row[5]]
            row[2] = struct.pack('<iii', dx - row[3], dy - row[4] - 12, dest-i-1)
    a = b''.join(r[1] for r in chunks)
    b = b''.join(r[2] for r in chunks)
    codes = bytes(r[0] for r in chunks)
    split_ops(a, b, codes)
    return struct.pack('<IIIHH', number(element.attrib['hash']), len(a), len(b),
                       len(codes), number(element.attrib['depth'])) + a + b + codes


def replace_block(data, field, old_size, value):
    if not value:
        return
    original = pointer(data, field, old_size) if old_size else None
    if len(value) <= old_size:
        data[original:original + len(value)] = value
        return
    # ponytail: append-only relocation preserves unknown fields; repeated growing
    # edits waste space. A full resource repacker is needed if this becomes large.
    data.extend(bytes((-len(data)) % 16))
    offset = len(data)
    require(offset + len(value) <= LIMIT, 'Edited resource exceeds size limit')
    data.extend(value)
    struct.pack_into('<Q', data, field, VIRTUAL + offset)


def build_xml(xml):
    require(len(xml) <= LIMIT and b'<!DOCTYPE' not in xml.upper()
            and b'<!ENTITY' not in xml.upper(), 'Oversized XML or DTD/entities forbidden')
    # Decode to UTF-8 first so an alternate encoding cannot bypass the DTD check.
    text = xml.decode('utf-8-sig')
    require('\x00' not in text, 'XML must be UTF-8, without NUL characters')
    root = ET.fromstring(text)
    require(root.tag == 'HorseYed' and root.get('version') == '1',
            'Expected HorseYed XML version 1 (not CodeX XML)')
    base = root.find('Base')
    require(base is not None, 'Missing preserved base file')
    binary = base64.b64decode(''.join((base.text or '').split()), validate=True)
    require(hashlib.sha256(binary).hexdigest() == base.get('sha256'),
            'Preserved base file hash mismatch')
    header, data = decode(binary)
    original = bytes(data)
    expected = expressions(data)
    elements = root.findall('Expression')
    require(root.get('name') == string(data, 0x38), 'Dictionary renaming unsupported')
    require([e.get('name') for e in elements] == [n for n, _ in expected],
            'Expression additions, removals or reordering unsupported')
    require(len(root) == len(elements) + 1, 'Unexpected XML root elements')
    for element, (_, exp) in zip(elements, expected):
        struct.pack_into('<H', data, exp + 0x8e, number(element.attrib['registers']))
        track_nodes = element.find('Tracks')
        require(track_nodes is not None, 'Missing Tracks')
        tracks = bytearray()
        for node in track_nodes:
            require(node.tag == 'Track', 'Expected Track element')
            tracks.extend(struct.pack('<HBB', number(node.attrib['bone']),
                                      number(node.attrib['track']), number(node.attrib['flags'])))
        _, old_count = array(data, exp + 0x40, 4)
        replace_block(data, exp + 0x40, old_count * 4, tracks)
        if len(track_nodes) != old_count:
            struct.pack_into('<HH', data, exp + 0x48, len(track_nodes), len(track_nodes))
        slots, count = array(data, exp + 0x30, 8)
        streams = element.findall('Stream')
        require(len(streams) == count and len(element) == count + 1,
                'Stream additions/removals or unexpected elements unsupported')
        maximum = 0
        for j, child in enumerate(streams):
            field = slots + j * 8
            _, old_size, old_hash, _, _ = stream(data, field)
            require(number(child.attrib['hash']) == old_hash, 'Stream renaming unsupported')
            result = assemble(child)
            maximum = max(maximum, len(result))
            replace_block(data, field, old_size, result)
        struct.pack_into('<I', data, exp + 0x88, maximum)
    if bytes(data) == original:
        return binary  # exact compressed bytes on an unchanged round trip
    alignment = 65536 if len(data) > 32768 else 16
    data.extend(bytes((-len(data)) % alignment))
    result = encode(header, data)
    export_xml(result)  # independently parse the final pointers and branches
    return result


def self_check():
    source = ET.fromstring('<Stream hash="1" depth="2"><Op id="a" code="43" '
                           'target="end"/><Op id="v" code="11" value="1 2 3 4"/>'
                           '<Op id="end" code="0" a="" b=""/></Stream>')
    result = assemble(source)
    # Branch crosses a 16-byte vector, with no scalar operand between it and End.
    require(unpack('iii', result, 32) == (16, 0, 1), 'Branch self-check failed')
    source[0].set('target', 'missing')
    try:
        assemble(source)
    except ValueError:
        pass
    else:
        raise ValueError('Missing branch target accepted')
    print('Self-check passed: relative branch origins and invalid target rejection')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('export', 'build'):
        item = sub.add_parser(command)
        item.add_argument('input', type=Path)
        item.add_argument('output', type=Path)
    item = sub.add_parser('inspect')
    item.add_argument('input', type=Path)
    sub.add_parser('self-check')
    args = parser.parse_args()
    try:
        if args.command == 'self-check':
            self_check()
            return
        source = read_file(args.input)
        if args.command == 'inspect':
            _, data = decode(source)
            entries = expressions(data)
            print(f'{string(data, 0x38)}: {len(entries)} expressions, {len(data)} decoded bytes')
            for name, exp in entries:
                slots, count = array(data, exp + 0x30, 8)
                for i in range(count):
                    _, _, _, _, ops = stream(data, slots + i * 8)
                    print(f'  {name}: stream {i}, {len(ops)} instructions')
            return
        require(not args.output.exists(), 'Output exists; choose a new path')
        result = export_xml(source) if args.command == 'export' else build_xml(source)
        with args.output.open('xb') as handle:
            handle.write(result)
        print(f'{args.output}: {len(result)} bytes; SHA256 {hashlib.sha256(result).hexdigest()}')
    except (ValueError, OSError, KeyError, struct.error, zlib.error, ET.ParseError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
