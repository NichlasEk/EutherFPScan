"""Check activation ordering and recovery with private files, without sudo."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import install_sddm as installer


class SddmInstallTests(unittest.TestCase):
    def test_config_drift_is_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.config_updated(b'[Theme]\nCurrent=other\n')

    def test_activation_restore_and_failed_activation(self):
        for fail_activation in (False, True):
            with self.subTest(fail_activation=fail_activation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                config, pam = root / 'sddm.conf', root / 'sddm.pam'
                config_original = b'[Autologin]\nSession=plasma\n\n'
                pam_original = (Path(__file__).parent / 'fixtures/sddm.pam').read_bytes()
                config.write_bytes(config_original)
                pam.write_bytes(pam_original)

                def replace(path, expected, content):
                    self.assertEqual(path.read_bytes(), expected)
                    if path == config and fail_activation:
                        raise OSError('Simulated configuration write failure')
                    path.write_bytes(content)

                def run_pam(option):
                    self.assertTrue((root / 'theme/Main.qml').is_file())
                    pam.write_bytes(installer.pam.updated(pam_original) if option == '--apply' else pam_original)

                with ExitStack() as stack:
                    for name, value in {'CONFIG': config, 'CONFIG_BACKUP': root / 'config.backup',
                                        'THEME': root / 'theme', 'run_pam': run_pam}.items():
                        stack.enter_context(patch.object(installer, name, value))
                    for name, value in {'TARGET': pam, 'BACKUP': root / 'pam.backup',
                                        'replace_file': replace}.items():
                        stack.enter_context(patch.object(installer.pam, name, value))
                    stack.enter_context(patch('os.geteuid', return_value=0))
                    stack.enter_context(patch('sys.argv', ['install_sddm.py', '--apply']))
                    if fail_activation:
                        with self.assertRaises(OSError):
                            installer.main()
                    else:
                        installer.main()
                        self.assertEqual(config.read_bytes(), installer.config_updated(config_original))
                        self.assertEqual(pam.read_bytes(), installer.pam.updated(pam_original))
                        self.assertFalse((root / 'theme/Preview.qml').exists())
                        installer.restore()
                    self.assertEqual(config.read_bytes(), config_original)
                    self.assertEqual(pam.read_bytes(), pam_original)
