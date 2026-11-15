#!/usr/bin/env python3
"""Validate CAM capture, compare raster frames, and inspect PE assets without execution."""
from pathlib import Path
import collections
import hashlib
import json
import re
import struct
import zlib
import numpy as np
from PIL import Image
from analyze_capture import packets

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'artifacts/analysis/windows'


def spans(flags):
    active = np.flatnonzero(flags)
    if not len(active):
        return []
    groups = np.split(active, np.where(np.diff(active)>1)[0]+1)
    return [[int(g[0]), int(g[-1])+1] for g in groups]


def inspect_capture():
    source = ROOT/'artifacts/local/windows-session/inspection'
    rows = list(packets(ROOT/'artifacts/captures/windows/cam-frames.pcapng'))
    frames = [r for r in rows if r['endpoint']==2 and not r['completion'] and len(r['payload'])>20]
    assert len(frames)==15
    assert all(r['captured_length']==r['original_length'] for r in rows)
    arrays = []
    frame_info = []
    for index, r in enumerate(frames):
        raw = r['payload']
        assert len(raw)==640*640*3
        if source.exists():
            assert raw==(source/f'frame_{index:03}.bin').read_bytes()
            assert raw==Image.open(source/f'frame_{index:03}.png').convert('RGB').tobytes()
        frames_dir = OUT/'frames'
        frames_dir.mkdir(exist_ok=True)
        Image.frombytes('RGB', (640, 640), raw).save(frames_dir/f'frame_{index:03}.png')
        arrays.append(np.frombuffer(raw,dtype=np.uint8).reshape(640,640,3))
        frame_info.append(dict(index=index, packet=r['packet'], time=r['time'], sha256=hashlib.sha256(raw).hexdigest()))
    stack=np.stack(arrays)
    delta=np.max(stack,axis=0).astype(np.int16)-np.min(stack,axis=0)
    changed=np.any(delta!=0,axis=2)
    strong=np.any(delta>8,axis=2)
    Image.fromarray(changed.astype(np.uint8)*255).save(OUT/'changed-pixels.png')
    invariant=arrays[0].copy()
    invariant[changed]=0
    Image.fromarray(invariant).save(OUT/'invariant-pixels.png')
    overlay=arrays[0].copy()//3
    overlay[strong]=[255,50,80]
    Image.fromarray(overlay).save(OUT/'changes-overlay.png')
    regions={
        'logo':(250,120,390,170), 'main_cpu_digits':(100,235,350,390),
        'gpu_digits':(440,235,525,300), 'liquid_digits':(440,350,525,410),
        'cpu_label':(190,405,270,445), 'gpu_label':(440,300,505,325),
        'liquid_label':(440,415,525,440), 'divider':(408,240,412,433)}
    region_info={}
    for name,(x0,y0,x1,y1) in regions.items():
        region_info[name]=dict(box=[x0,y0,x1,y1],changed_pixels=int(changed[y0:y1,x0:x1].sum()),
            distinct_rasters=len({a[y0:y1,x0:x1].tobytes() for a in arrays}))
    Image.fromarray(arrays[0][120:170,250:390]).save(OUT/'captured-nzxt-label.png')
    headers=[r['payload'].hex(' ') for r in rows if r['endpoint']==2 and not r['completion'] and len(r['payload'])==20]
    return dict(packets=len(rows),duration=rows[-1]['time']-rows[0]['time'],
        truncated_packets=0,frames=frame_info,frame_intervals_seconds=np.diff([r['time'] for r in frames]).tolist(),
        unique_bulk_headers=sorted(set(headers)),unique_frames=len({r['sha256'] for r in frame_info}),
        changed_pixels=int(changed.sum()),strongly_changed_pixels=int(strong.sum()),
        changed_row_spans=spans(changed.any(axis=1)),regions=region_info,
        note='Invariant pixels apply only to these samples, not all temperatures or configurations.')


def inspect_exe():
    path = ROOT/'artifacts/local/NZXT CAM.exe'
    if not path.exists():
        return {'available': False, 'note': 'Optional local CAM executable not present; capture analysis still runs.'}
    data=path.read_bytes()
    pe=struct.unpack_from('<I',data,0x3c)[0]
    assert data[pe:pe+4]==b'PE\0\0'
    count=struct.unpack_from('<H',data,pe+6)[0]
    optional_size=struct.unpack_from('<H',data,pe+20)[0]
    section_start=pe+24+optional_size
    sections=[]
    for i in range(count):
        pos=section_start+40*i
        name=data[pos:pos+8].rstrip(b'\0').decode('ascii',errors='replace')
        virtual_size,rva,size,offset=struct.unpack_from('<IIII',data,pos+8)
        sections.append(dict(name=name,offset=offset,size=size,rva=rva,virtual_size=virtual_size))
    evidence={}
    for token in [b'Electron v32.1.0',b'app.asar',b'vulkan-1.dll',b'vkCreateInstance',b'Kraken',b'kraken',b'Q565',b'q565',b'{"files":']:
        offsets=[m.start() for m in re.finditer(re.escape(token),data)]
        evidence[token.decode()]=dict(count=len(offsets),first_offsets=[hex(i) for i in offsets[:12]])
    pngs=[]
    for match in re.finditer(re.escape(b'\x89PNG\r\n\x1a\n'),data):
        start=match.start(); pos=start+8; valid=True; dimensions=None
        while pos+12<=len(data):
            length=struct.unpack_from('>I',data,pos)[0]
            if length>len(data)-pos-12:
                break
            kind=data[pos+4:pos+8]; content=data[pos+8:pos+8+length]
            crc=struct.unpack_from('>I',data,pos+8+length)[0]
            if zlib.crc32(kind+content)&0xffffffff!=crc:
                valid=False; break
            if kind==b'IHDR' and length==13:
                dimensions=list(struct.unpack_from('>II',content))
            pos+=length+12
            if kind==b'IEND':
                if valid and dimensions:
                    name=f'exe-png-{start:08x}.png'
                    (OUT/name).write_bytes(data[start:pos])
                    pngs.append(dict(offset=hex(start),size=pos-start,dimensions=dimensions,file=name))
                break
    # Magic alone is weak evidence; retain only sane SPIR-V headers.
    spirv=[]
    for m in re.finditer(re.escape(b'\x03\x02\x23\x07'),data):
        if m.start()+20>len(data): continue
        magic,version,generator,bound,schema=struct.unpack_from('<IIIII',data,m.start())
        if version in [0x10000,0x10100,0x10200,0x10300,0x10400,0x10500,0x10600] and 0<bound<10000000 and schema==0:
            spirv.append(dict(offset=hex(m.start()),version=hex(version),bound=bound))
    return dict(size=len(data),sha256=hashlib.sha256(data).hexdigest(),sections=sections,
        trailing_bytes_after_sections=len(data)-max(s['offset']+s['size'] for s in sections),
        string_evidence=evidence,validated_pngs=pngs,plausible_spirv_headers=spirv,
        note='Runtime Vulkan strings and even embedded shaders would not identify the LCD renderer. No executable code was run.')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report=dict(capture=inspect_capture(),executable=inspect_exe())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    c=report['capture']; e=report['executable']
    print(json.dumps(dict(frames=len(c['frames']),unique_frames=c['unique_frames'],changed_pixels=c['changed_pixels'],
        regions=c['regions'],validated_pngs=e.get('validated_pngs',[]),plausible_spirv_headers=e.get('plausible_spirv_headers',[]),
        evidence=e.get('string_evidence',{})),indent=2))

if __name__=='__main__':
    main()
