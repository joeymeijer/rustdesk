import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rustdesk_dr', Path(__file__).with_name('rustdesk-dr.py'))
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)


class RecoveryTests(unittest.TestCase):
    def test_partial_stop_or_snapshot_failure_still_restarts_original_services(self):
        for failure in ['stop', 'tar']:
            with self.subTest(failure=failure):
                calls = []
                def command(args, *unused, **kwargs):
                    calls.append(args)
                    if (failure == 'stop' and 'stop' in args) or (failure == 'tar' and args[0] == 'tar'):
                        raise subprocess.CalledProcessError(1, args)
                with patch.object(dr, 'run', side_effect=command), patch.object(dr, 'wait_running') as health, patch.object(dr.signal, 'signal'), patch.object(dr.signal, 'SIGHUP', 1, create=True):
                    with self.assertRaises(subprocess.CalledProcessError):
                        dr.snapshot(Path('/stack'), ['docker','compose'], ['hbbs','hbbr'], Path('/snapshot.tar'))
                self.assertIn(['docker','compose','start','hbbs','hbbr'], calls)
                health.assert_called_once_with(Path('/stack'), ['docker','compose'], ['hbbs','hbbr'])

    def test_restore_rejects_traversal_and_links_before_extraction(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('linked', tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root/'unsafe.tar'
                with tarfile.open(archive, 'w') as handle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.size = 0
                    member.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                    handle.addfile(member, io.BytesIO(b''))
                with patch.object(dr, 'run') as execute:
                    with self.assertRaisesRegex(RuntimeError, 'tar-item'):
                        dr.extract_checked(archive, root)
                execute.assert_not_called()

    def test_invalid_hash_or_existing_restore_target_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root/'backup.tar.gz'
            archive.write_bytes(b'not a backup')
            target = root/'new'
            with patch.object(dr, 'run') as execute:
                with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                    dr.restore(archive, target, '0'*64)
                self.assertFalse(target.exists())
                target.mkdir()
                marker = target/'keep.txt'
                marker.write_text('existing data')
                with self.assertRaisesRegex(RuntimeError, 'bestaat al'):
                    dr.restore(archive, target, dr.digest(archive))
                self.assertEqual(marker.read_text(), 'existing data')
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
