#!/usr/bin/env python3
"""Live CPU/GPU/coolant dashboard for Kraken Elite V2 (1e71:3012).
Run with Ubuntu's /usr/bin/python3. All output stays in this project.
"""
import argparse
from contextlib import AbstractContextManager
import fcntl
import json
import math
import signal
from pathlib import Path
import struct
import subprocess
import time

from PIL import Image, ImageDraw, ImageFont
import usb.core
import usb.util
from kraken_usb import MAGIC

ROOT = Path(__file__).resolve().parents[2]
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def cpu_sensor():
    for name, label in [('k10temp', 'Tctl'), ('coretemp', 'Package id 0')]:
        for hw in sorted(Path('/sys/class/hwmon').glob('hwmon*')):
            if (hw/'name').read_text().strip() == name:
                for p in hw.glob('temp*_label'):
                    if p.read_text().strip() == label:
                        return p.with_name(p.name.replace('_label', '_input'))
    raise RuntimeError('No CPU package sensor found; specify --cpu-sensor')


def temperatures(cpu_path, gpu_index):
    result = {'cpu': None, 'gpu': None}
    errors = []
    try:
        result['cpu'] = float(cpu_path.read_text()) / 1000
    except (OSError, ValueError) as e:
        errors.append(f'CPU: {e}')
    try:
        output = subprocess.run(
            ['nvidia-smi', f'--id={gpu_index}', '--query-gpu=temperature.gpu',
             '--format=csv,noheader,nounits'], capture_output=True, text=True,
            timeout=3, check=True)
        result['gpu'] = float(output.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        errors.append(f'GPU: {e}')
    for key, value in result.items():
        if value is not None and (not math.isfinite(value) or not -20 <= value <= 150):
            errors.append(f'{key}: invalid temperature {value}')
            result[key] = None
    return result, errors


class Kraken(AbstractContextManager):
    def __init__(self):
        self.dev = usb.core.find(idVendor=0x1e71, idProduct=0x3012)
        if self.dev is None:
            raise RuntimeError('Kraken Elite V2 not found')
        self.claimed = []
        self.detached = []
        self.liquid = None
        self.liquid_time = 0

    def __enter__(self):
        try:
            for interface in (0, 1):
                if self.dev.is_kernel_driver_active(interface):
                    self.dev.detach_kernel_driver(interface)
                    self.detached.append(interface)
                usb.util.claim_interface(self.dev, interface)
                self.claimed.append(interface)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        try:
            for interface in reversed(self.claimed):
                usb.util.release_interface(self.dev, interface)
        finally:
            try:
                for interface in self.detached:
                    self.dev.attach_kernel_driver(interface)
            finally:
                usb.util.dispose_resources(self.dev)

    def read(self, timeout=250):
        try:
            report = bytes(self.dev.read(0x81, 512, timeout=timeout))
        except usb.core.USBTimeoutError:
            return b''
        if len(report) >= 17 and report[:2] in (b'\x75\x01', b'\x75\x02'):
            value = report[15] + report[16]/10
            if report[16] < 10 and 0 <= value < 100:
                self.liquid, self.liquid_time = value, time.monotonic()
        return report

    def coolant(self):
        # Observe spontaneous reports; do not change report intervals or cooling.
        deadline = time.monotonic()+1.2
        while time.monotonic() < deadline:
            self.read()
            if time.monotonic()-self.liquid_time < 2:
                return self.liquid
        return None

    def write(self, endpoint, data):
        actual = self.dev.write(endpoint, data, timeout=5000)
        if actual != len(data):
            raise RuntimeError(f'Short USB write {actual}/{len(data)}')

    def command(self, data, reply):
        self.write(1, data.ljust(512, b'\0'))
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            report = self.read()
            if report[:2] == reply:
                if report[14:15] != b'\x01':
                    raise RuntimeError(f'LCD rejected command: {report[:20].hex()}')
                return
        raise RuntimeError(f'LCD acknowledgement timed out for {data.hex()}')

    def display(self, image):
        data = image.convert('RGB').tobytes()
        if image.size != (640, 640):
            raise ValueError('Display requires 640x640')
        self.command(bytes.fromhex('36 01 00 01 09'), b'\x37\x01')
        self.write(2, MAGIC + bytes([9, 0, 0, 0]) + struct.pack('<I', len(data)))
        self.write(2, data)
        self.command(b'\x36\x02', b'\x37\x02')


def render(values):
    image = Image.new('RGB', (640, 640), '#08090c')
    draw = ImageDraw.Draw(image)

    def gradient_arc(box, start, end, width):
        for angle in range(start, end):
            t = (angle-start)/max(1, end-start)
            color = (round(35+142*t), round(224-162*t), round(221+34*t))
            draw.arc(box, angle, angle+2, fill=color, width=width)

    gradient_arc((27, 27, 613, 613), 130, 410, 9)
    gradient_arc((69, 69, 571, 571), 130, 410, 4)
    # A dark lower arc leaves space around the bottom of the circular panel.
    def text(x, y, value, size, color='white', bold=False, anchor='mm'):
        draw.text((x,y), value, font=ImageFont.truetype(BOLD if bold else FONT, size),
                  fill=color, anchor=anchor)

    def number(key):
        value = values.get(key)
        return '--' if value is None else str(round(value))

    text(320, 174, 'NZXT', 24, bold=True)
    text(242, 314, number('gpu'), 146, bold=True)
    text(352, 268, '°', 42)
    text(240, 410, 'GPU', 25, bold=True)
    draw.line((391, 254, 391, 420), fill='#55565d', width=2)
    text(456, 288, number('cpu')+'°', 49, bold=True)
    text(452, 328, 'CPU', 20)
    text(456, 378, number('liquid')+'°', 49, bold=True)
    text(452, 418, 'Liquid', 20)
    # Mask corners outside the circular LCD.
    mask = Image.new('L', image.size)
    ImageDraw.Draw(mask).ellipse((0, 0, 639, 639), fill=255)
    return Image.composite(image, Image.new('RGB', image.size), mask)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=int, default=0, help='0 runs until Ctrl+C')
    p.add_argument('--interval', type=float, default=1, help='Seconds between updates')
    p.add_argument('--gpu-index', type=int, default=0)
    p.add_argument('--cpu-sensor', type=Path)
    p.add_argument('--preview', action='store_true', help='Save one image without USB access')
    args = p.parse_args()
    if args.frames < 0 or args.interval < 0.2:
        p.error('--frames must be nonnegative; --interval must be at least 0.2')
    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    output = ROOT/'artifacts/runtime'
    output.mkdir(exist_ok=True)
    sensor = args.cpu_sensor or cpu_sensor()
    print(f'CPU sensor: {sensor}; NVIDIA GPU index: {args.gpu_index}', flush=True)
    if args.preview:
        values, errors = temperatures(sensor, args.gpu_index)
        values['liquid'] = None  # Never invent a live sensor reading for a preview.
        render(values).save(output/'dashboard-preview.png')
        print(json.dumps({'temperatures': values, 'errors': errors}), flush=True)
        return
    # Prevent competing instances of this dashboard from owning the device.
    with (output/'dashboard.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.exit(1, 'Another dashboard instance is running.\n')
        try:
            with Kraken() as kraken:
                count = 0
                while args.frames == 0 or count < args.frames:
                    started = time.monotonic()
                    values, errors = temperatures(sensor, args.gpu_index)
                    values['liquid'] = kraken.coolant()
                    image = render(values)
                    kraken.display(image)
                    image.save(output/'dashboard-preview.png')
                    print(json.dumps({'temperatures': values, 'errors': errors}), flush=True)
                    count += 1
                    if args.frames == 0 or count < args.frames:
                        time.sleep(max(0, args.interval-(time.monotonic()-started)))
        except KeyboardInterrupt:
            print('Stopped; last frame remains displayed.', flush=True)


if __name__ == '__main__':
    main()
