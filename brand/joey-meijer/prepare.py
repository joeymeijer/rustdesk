"""Stage branding in a disposable build checkout; leaves service identity intact."""
import argparse
import re
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ASSETS=Path(__file__).resolve().parent

def prepare(variant):
    mapping={
        'icon.ico':['res/icon.ico','res/tray-icon.ico','flutter/windows/runner/resources/app_icon.ico'],
        'icon.png':['res/icon.png','flutter/assets/icon.png'],
        'icon.svg':['flutter/assets/icon.svg'],
        f'logo_{variant}_light.png':['flutter/assets/logo.png','flutter/assets/logo_light.png'],
        f'logo_{variant}_dark.png':['flutter/assets/logo_dark.png'],
    }
    for source,destinations in mapping.items():
        for destination in destinations:
            shutil.copyfile(ASSETS/source,ROOT/destination)
    label='Joey Meijer Support' + (' - Beheer' if variant=='admin' else '')
    resource=ROOT/'flutter/windows/runner/Runner.rc'
    content=resource.read_text(encoding='utf-8')
    content=re.sub(r'(VALUE "(?:FileDescription|ProductName)", )"[^"]*"',lambda match: match[1]+f'"{label}"',content)
    resource.write_text(content,encoding='utf-8')
    portable=ROOT/'libs/portable/Cargo.toml'
    content=portable.read_text(encoding='utf-8')
    content=re.sub(r'^(ProductName|FileDescription) = "[^"]*"',lambda match: f'{match[1]} = "{label}"',content,flags=re.M)
    portable.write_text(content,encoding='utf-8')
    common=ROOT/'flutter/lib/common.dart'
    content=common.read_text(encoding='utf-8')
    content=content.replace('static const Color accent = Color(0xFF0071FF);','static const Color accent = Color(0xFF0F766E);')
    common.write_text(content,encoding='utf-8')
    print(f'Staged {label}; executable, service and config paths remain RustDesk.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('variant',choices=['support','admin'])
    prepare(parser.parse_args().variant)
