#!/usr/bin/env python3
"""Extract USBPcap transactions from little-endian pcapng without Wireshark."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import struct


def packets(path):
    data = Path(path).read_bytes()
    offset = 0
    number = 0
    while offset < len(data):
        kind, size = struct.unpack_from('<II', data, offset)
        if size < 12 or offset + size > len(data):
            raise ValueError(f'Invalid block at {offset}')
        if struct.unpack_from('<I', data, offset + size - 4)[0] != size:
            raise ValueError('Block length mismatch')
        if kind == 0x0A0D0D0A and data[offset+8:offset+12] != b'\x4d\x3c\x2b\x1a':
            raise ValueError('Only little-endian pcapng supported')
        if kind == 1 and struct.unpack_from('<H', data, offset+8)[0] != 249:
            raise ValueError('Expected USBPcap link type 249')
        if kind == 6:
            number += 1
            interface, hi, lo, captured, original = struct.unpack_from('<IIIII', data, offset+8)
            raw = data[offset+28:offset+28+captured]
            header, irp, status, function, info, bus, device, endpoint, transfer, length = struct.unpack_from('<HQIHBHHBBI', raw)
            yield dict(packet=number, time=(hi << 32 | lo)/1e6, irp=irp,
                       status=status, function=function, completion=bool(info & 1),
                       bus=bus, device=device, endpoint=endpoint, transfer=transfer,
                       requested_length=length, captured_length=captured, original_length=original,
                       payload=raw[header:])
        offset += size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', nargs='?', default=Path(__file__).resolve().parents[1]/'captures/june/export.pcapng')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'analysis/june')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = list(packets(args.capture))
    start = rows[0]['time']
    frames = []
    with (args.output/'transactions.jsonl').open('w') as log:
        for row in rows:
            payload = row['payload']
            public = {k:v for k,v in row.items() if k != 'payload'}
            public.update(relative_time=round(row['time']-start, 6),
                          payload_length=len(payload), prefix=payload[:80].hex(' '))
            log.write(json.dumps(public)+'\n')
            if row['endpoint'] == 2 and not row['completion'] and len(payload)>20:
                stem = f"frame-{len(frames):02d}"
                (args.output/(stem+'.partial.bin')).write_bytes(payload)
                # Show ONLY complete captured rows; missing pixels are never invented.
                try:
                    from PIL import Image
                    width = 640
                    height = len(payload)//(width*3)
                    Image.frombytes('RGB', (width,height), payload[:width*height*3]).save(args.output/(stem+'.rgb-prefix.png'))
                except ImportError:
                    pass
                frames.append(dict(packet=row['packet'], captured=len(payload),
                                   declared=row['requested_length'], sha256=hashlib.sha256(payload).hexdigest()))
    summary = dict(packets=len(rows), duration=rows[-1]['time']-start, frames=frames,
                   commands=dict(collections.Counter(r['payload'][:5].hex(' ') for r in rows
                       if r['endpoint']==1 and not r['completion'] and r['payload'])))
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
