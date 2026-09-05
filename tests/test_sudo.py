import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.install_sudo import BLOCK, updated

ORIGINAL = b'''#%PAM-1.0

# Set up user limits from /etc/security/limits.conf.
session    required   pam_limits.so

@include common-auth
@include common-account
@include common-session-noninteractive
'''


class SudoTests(unittest.TestCase):
    def test_reviewed_change_preserves_other_pam_sections(self):
        result = updated(ORIGINAL)
        self.assertEqual(result.replace(BLOCK.encode(), b'', 1), ORIGINAL)
        self.assertLess(result.index(b'pam_fprintd.so'), result.index(b'@include common-auth'))
        for changed in (ORIGINAL + b'# local change\n', ORIGINAL.replace(b'common-auth', b'custom-auth')):
            with self.assertRaises(RuntimeError):
                updated(changed)

    def test_real_pam_control_flow_and_account_checks(self):
        # Real libpam, isolated configuration directory, synthetic auth result.
        # No reader, passwords, root privileges or system PAM writes involved.
        libpam = ctypes.CDLL('libpam.so.0')
        pointer = ctypes.c_void_p
        callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, pointer, pointer, pointer)
        callback = callback_type(lambda *_: 19)  # Unexpected conversation fails.

        class Conversation(ctypes.Structure):
            _fields_ = [('conv', callback_type), ('data', pointer)]

        conversation = Conversation(callback, None)
        libpam.pam_start_confdir.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                            ctypes.POINTER(Conversation), ctypes.c_char_p,
                                            ctypes.POINTER(pointer)]
        for name in ('pam_authenticate', 'pam_acct_mgmt', 'pam_end'):
            getattr(libpam, name).argtypes = [pointer, ctypes.c_int]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'mock.c'
            module = root / 'mock.so'
            source.write_text('#include <stdlib.h>\n'
                              'int pam_sm_authenticate(void*p,int f,int n,const char**v) '
                              '{(void)p;(void)f;(void)n;(void)v;'
                              'const char*s=getenv("EUTHER_TEST_PAM"); return s ? atoi(s) : 7;}\n'
                              'int pam_sm_setcred(void*p,int f,int n,const char**v) '
                              '{(void)p;(void)f;(void)n;(void)v;return 0;}\n')
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(module)], check=True)
            configuration = updated(ORIGINAL).decode().replace('pam_fprintd.so', str(module))
            # libpam resolves includes against /etc/pam.d even with confdir.
            for name in ('common-auth', 'common-account', 'common-session-noninteractive'):
                configuration = configuration.replace('@include ' + name, '@include ' + str(root / name))
            (root / 'sudo-test').write_text(configuration)
            (root / 'common-session-noninteractive').write_text('session required pam_permit.so\n')
            for fingerprint, fallback, account, expected in (
                (0, 'deny', 'permit', True),
                (7, 'permit', 'permit', True),
                (7, 'deny', 'permit', False),
                (9, 'permit', 'permit', True),
                (0, 'permit', 'deny', False),
            ):
                with self.subTest(fingerprint=fingerprint, fallback=fallback, account=account):
                    (root / 'common-auth').write_text(f'auth required pam_{fallback}.so\n')
                    (root / 'common-account').write_text(f'account required pam_{account}.so\n')
                    handle = pointer()
                    with patch.dict(os.environ, {'EUTHER_TEST_PAM': str(fingerprint)}):
                        code = libpam.pam_start_confdir(b'sudo-test', b'synthetic-user',
                                                       ctypes.byref(conversation), os.fsencode(root),
                                                       ctypes.byref(handle))
                        self.assertEqual(code, 0)
                        try:
                            code = libpam.pam_authenticate(handle, 0)
                            if code == 0:
                                code = libpam.pam_acct_mgmt(handle, 0)
                            self.assertEqual(code == 0, expected, f"PAM code={code}")
                        finally:
                            libpam.pam_end(handle, code)
