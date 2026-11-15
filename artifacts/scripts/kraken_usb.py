#!/usr/bin/env python3
"""Experimental 1e71:3012 display uploader based on export.pcapng.

Use /usr/bin/python3 on Ubuntu (python3-usb and python3-pil).
Default action is discovery only. --image, --test-pattern, or --q565 writes the LCD.
"""
import argparse
from pathlib import Path
import struct
import sys
import time

MAGIC = bytes.fromhex('12 fa 01 e8 ab cd ef 98 76 54 32 10')


def image_data(args):
    from PIL import Image, ImageDraw, ImageOps
    if args.image:
        with Image.open(args.image) as source:
            image = ImageOps.fit(source.convert('RGB'), (640, 640))
    else:
        image = Image.new('RGB', (640, 640))
        draw = ImageDraw.Draw(image)
        for i, color in enumerate(['red', 'lime', 'blue', 'white']):
            draw.rectangle((i*160, 0, (i+1)*160-1, 639), fill=color)
        draw.ellipse((12, 12, 628, 628), outline='yellow', width=8)
        draw.text((270, 300), 'UBUNTU / KRAKEN', fill='black', stroke_width=1)
    return image.tobytes()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group()
    group.add_argument('--image', type=Path)
    group.add_argument('--test-pattern', action='store_true')
    group.add_argument('--q565', type=Path, help='Send an already encoded 640x640 Q565 frame (experimental mode 0x08)')
    p.add_argument('--dry-run', type=Path, help='Save frame and header without accessing USB')
    p.add_argument('--status', action='store_true', help='Listen to unsolicited reports for 3 seconds')
    args = p.parse_args()
    data = image_data(args) if args.image or args.test_pattern else None
    mode = 8 if args.q565 else 9
    if args.q565:
        data = args.q565.read_bytes()
        if len(data) < 8 or data[:4] != b'q565' or struct.unpack_from('<HH', data, 4) != (640, 640):
            p.error('--q565 requires a Q565 header with 640x640 dimensions')
    header = MAGIC + bytes([mode, 0, 0, 0]) + struct.pack('<I', len(data)) if data else None
    if args.dry_run:
        if data is None:
            p.error('--dry-run requires --image, --test-pattern, or --q565')
        args.dry_run.write_bytes(data)
        args.dry_run.with_suffix('.header.bin').write_bytes(header)
        print(f'{len(data)} payload bytes, mode 0x{mode:02x}; header {header.hex(" ")}')
        return
    import usb.core
    import usb.util
    try:
        dev = usb.core.find(idVendor=0x1e71, idProduct=0x3012)
    except usb.core.NoBackendError:
        sys.exit("USB backend unavailable in this session (libusb initialization failed). Run on the host with /dev/bus/usb access.")
    if dev is None:
        sys.exit('Kraken USB device unavailable. This session needs /dev/bus/usb access; sysfs visibility alone is insufficient.')
    print(f'Kraken Elite V2: bus {dev.bus}, address {dev.address}')
    if data is None and not args.status:
        return
    detached = []
    claimed = []
    try:
        for interface in ([0, 1] if data else [1]):
            if dev.is_kernel_driver_active(interface):
                dev.detach_kernel_driver(interface)
                detached.append(interface)
            usb.util.claim_interface(dev, interface)
            claimed.append(interface)

        def write(endpoint, payload):
            actual = dev.write(endpoint, payload, timeout=5000)
            if actual != len(payload):
                raise RuntimeError(f'Short USB write: {actual}/{len(payload)}')

        def command(payload, expected):
            write(1, payload.ljust(512, b'\0'))
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                report = bytes(dev.read(0x81, 512, timeout=1000))
                if report[:2] == expected:
                    if report[14:15] != b'\x01':
                        raise RuntimeError(f'Unexpected LCD acknowledgement: {report[:20].hex()}')
                    return
            raise RuntimeError(f'No acknowledgement for {payload.hex()}')

        if data:
            command(bytes([0x36, 1, 0, 1, mode]), bytes.fromhex('37 01'))
            write(2, header)
            write(2, data)
            command(bytes.fromhex('36 02'), bytes.fromhex('37 02'))
            print('Frame transferred and both LCD acknowledgements received; verify colors/orientation on the display.')
        if args.status:
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                try:
                    report = bytes(dev.read(0x81, 512, timeout=1000))
                    print(report[:32].hex(' '))
                except usb.core.USBTimeoutError:
                    pass
    finally:
        for interface in reversed(claimed):
            usb.util.release_interface(dev, interface)
        for interface in detached:
            dev.attach_kernel_driver(interface)
        usb.util.dispose_resources(dev)


if __name__ == '__main__':
    main()
