#!/usr/bin/env python3
"""Extract selected local CAM resources and embedded shader/font evidence. Never executes CAM."""
import hashlib
import io
import json
from pathlib import Path
import re
import struct
from PIL import ImageFont

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/local/cam-resources'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    archive=(ROOT/'artifacts/local/cam-installation/resources/app.asar').read_bytes()
    header_size=struct.unpack_from('<I',archive,4)[0]
    header=json.loads(archive[16:16+struct.unpack_from('<I',archive,12)[0]])
    entries={}
    def walk(node,prefix=''):
        for name,value in node.get('files',{}).items():
            path=prefix+name
            if 'files' in value: walk(value,path+'/')
            else: entries[path]=value
    walk(header)
    (OUT/'asar-index.json').write_text(json.dumps(entries,indent=2))
    extracted=[]
    for name,entry in entries.items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError(f'Unsafe archive path: {name}')
        selected=(not name.startswith('node_modules/') and path.suffix in
                  {'.js','.json','.html','.css','.map','.otf','.ttf','.woff','.svg'})
        selected |= name.startswith('node_modules/@nzxt/cam-core/dist/') and path.suffix in {'.js','.ts'}
        if not selected or 'offset' not in entry: continue
        start=8+header_size+int(entry['offset']); end=start+entry['size']
        if not 8+header_size <= start <= end <= len(archive): raise ValueError(name)
        blob=archive[start:end]
        integrity=entry.get('integrity',{})
        if integrity.get('algorithm')=='SHA256' and hashlib.sha256(blob).hexdigest()!=integrity['hash']:
            raise ValueError(f'Integrity mismatch: {name}')
        dest=OUT/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(blob)
        extracted.append(name)
    binary=ROOT/'artifacts/local/cam-installation/resources/app.asar.unpacked/node_modules/@nzxt/cam-core/dist/index.node'
    data=binary.read_bytes()
    shaders={}
    # UTF-8 handles degree symbols in comments; ASCII fallback handles a binary prefix.
    patterns=[rb'[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]{200,}',rb'[\x09\x0a\x0d\x20-\x7e]{200,}']
    for pattern in patterns:
        for match in re.finditer(pattern,data):
            run=match[0]
            if b'@fragment' not in run: continue
            start=re.search(rb'(?:struct \w+ \{|const \w+:)',run)
            if not start:continue
            end=run.rfind(b'}')+1
            source=run[start.start():end]
            if b'@vertex' not in source or source.count(b'{')!=source.count(b'}'):continue
            try: source.decode('utf8')
            except UnicodeDecodeError:continue
            names=re.findall(rb'([a-z_0-9]+\.wgsl)',run)
            name=names[0].decode() if names else 'glyphon-text.wgsl'
            for known in ('overlay_texture.wgsl', 'image_rotation.wgsl'):
                if known.encode() in run: name=known
            if name in shaders and shaders[name]['size']>=len(source):continue
            dest=OUT/'shaders'/name;dest.parent.mkdir(exist_ok=True); dest.write_bytes(source+b'\n')
            shaders[name]=dict(offset=hex(match.start()+start.start()),size=len(source),
                               sha256=hashlib.sha256(source).hexdigest(),balanced_braces=True)
    fonts=[]
    for match in re.finditer(b'OTTO',data):
        pos=match.start()
        if pos+12>len(data):continue
        count=struct.unpack_from('>H',data,pos+4)[0]
        if not 1<=count<=100 or pos+12+16*count>len(data):continue
        tables=[struct.unpack_from('>4sIII',data,pos+12+16*i) for i in range(count)]
        if not {b'head',b'name',b'cmap'}.issubset({t[0] for t in tables}):continue
        size=max(offset+length for tag,checksum,offset,length in tables)
        if size>5_000_000 or pos+size>len(data):continue
        blob=data[pos:pos+size]
        try:
            font=ImageFont.truetype(io.BytesIO(blob),32); family,style=font.getname()
        except (OSError,ValueError):continue
        name=f'{family}-{style}-{pos:08x}.otf'.replace(' ','_')
        dest=OUT/'embedded-fonts'/name;dest.parent.mkdir(exist_ok=True);dest.write_bytes(blob)
        fonts.append(dict(file=name,offset=hex(pos),size=size,family=family,style=style))
    report=dict(asar_entries=len(entries),selected_extracted=len(extracted),
                native_module_sha256=hashlib.sha256(data).hexdigest(),shaders=shaders,fonts=fonts,
                note='Shader boundaries are recovered heuristically; balanced braces are not compiler validation. Fonts were parsed with FreeType. Proprietary assets remain local.')
    (OUT/'extraction-report.json').write_text(json.dumps(report,indent=2)+'\n')
    analysis=ROOT/'artifacts/analysis/cam'
    analysis.mkdir(parents=True,exist_ok=True)
    (analysis/'extraction-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
