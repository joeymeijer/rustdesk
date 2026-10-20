import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('updater',Path(__file__).with_name('prepare-client.py'))
updater=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)

class UpdaterTest(unittest.TestCase):
    def fixture(self,corrupt=False):
        binary=b'MZ'+b'test Windows download'
        assets=[{'name':filename,'size':len(binary),'digest':'sha256:'+hashlib.sha256(binary).hexdigest(),
                 'browser_download_url':f'https://github.com/joeymeijer/rustdesk/releases/download/test/{filename}'}
                for filename in updater.FILES]
        if corrupt:
            assets[1]['digest']='sha256:'+'0'*64
        release={'tag_name':'test','html_url':'https://github.com/joeymeijer/rustdesk/releases/tag/test','assets':assets}
        def open_url(request,**kwargs):
            return io.BytesIO(json.dumps(release).encode() if request.full_url.endswith('/latest') else binary)
        return binary,open_url

    def test_both_clients_published_with_readable_permissions(self):
        binary,open_url=self.fixture()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DOWNLOAD_DIR':directory}),patch.object(updater.urllib.request,'urlopen',side_effect=open_url):
            output=Path(directory)
            if os.name!='nt':
                output.chmod(0o700)
            updater.main()
            for filename in updater.FILES:
                self.assertEqual((output/filename).read_bytes(),binary)
                if os.name!='nt':
                    self.assertEqual((output/filename).stat().st_mode & 0o777,0o644)
            if os.name!='nt':
                self.assertEqual(output.stat().st_mode & 0o777,0o755)
            self.assertEqual(json.loads((output/'release.json').read_text())['release'],'test')

    def test_bad_second_digest_keeps_both_previous_downloads(self):
        _,open_url=self.fixture(corrupt=True)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DOWNLOAD_DIR':directory}),patch.object(updater.urllib.request,'urlopen',side_effect=open_url):
            output=Path(directory)
            for filename in updater.FILES:
                (output/filename).write_bytes(b'previous release')
            with self.assertRaisesRegex(RuntimeError,'SHA256'):
                updater.main()
            for filename in updater.FILES:
                self.assertEqual((output/filename).read_bytes(),b'previous release')
            self.assertFalse(list(output.glob('*.part')))

if __name__=='__main__':
    unittest.main()
