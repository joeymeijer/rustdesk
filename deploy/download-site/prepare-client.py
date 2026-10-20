"""Fetch both branded clients from Joey's fork; never replace them with stock builds."""
import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPOSITORY='joeymeijer/rustdesk'
FILES=('rustdesk-support-windows.exe','rustdesk-admin-windows.exe')

def main():
    output=Path(os.environ.get('DOWNLOAD_DIR','/downloads'))
    output.mkdir(parents=True,exist_ok=True)
    output.chmod(0o755)
    headers={'User-Agent':'JoeyMeijer-client-updater','Accept':'application/vnd.github+json'}
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',headers=headers)
    with urllib.request.urlopen(request,timeout=60) as response:
        release=json.load(response)
    assets={asset['name']:asset for asset in release['assets']}
    missing=set(FILES)-assets.keys()
    if missing:
        raise RuntimeError('Geen complete branded release gevonden: '+', '.join(sorted(missing)))
    staged=[]
    metadata={'release':release['tag_name'],'source':release['html_url'],'clients':{}}
    try:
        for filename in FILES:
            asset=assets[filename]
            url=asset['browser_download_url']
            if not url.startswith(f'https://github.com/{REPOSITORY}/releases/download/'):
                raise RuntimeError('Onverwachte downloadbron')
            temporary=output/(filename+'.part')
            staged.append((temporary,output/filename))
            digest=hashlib.sha256()
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':headers['User-Agent']}),timeout=120) as response, temporary.open('wb') as target:
                first=response.read(1024*1024)
                if not first.startswith(b'MZ'):
                    raise RuntimeError('Geen Windows executable: '+filename)
                target.write(first)
                digest.update(first)
                while chunk:=response.read(1024*1024):
                    target.write(chunk)
                    digest.update(chunk)
            if temporary.stat().st_size!=asset['size']:
                raise RuntimeError('Onvolledige download: '+filename)
            expected=asset.get('digest')
            if expected and expected!='sha256:'+digest.hexdigest():
                raise RuntimeError('SHA256 wijkt af: '+filename)
            temporary.chmod(0o644)
            metadata['clients'][filename]={'sha256':digest.hexdigest(),'source':url}
        # Stage both before replacing either client; partial downloads stay unpublished.
        for temporary,destination in staged:
            temporary.replace(destination)
        manifest=output/'release.json'
        manifest.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        manifest.chmod(0o644)
        print('Beide branded clients bijgewerkt:',release['tag_name'])
    finally:
        for temporary,_ in staged:
            temporary.unlink(missing_ok=True)

if __name__=='__main__':
    main()
