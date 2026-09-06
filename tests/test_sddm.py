"""Exercise the proposed SDDM stack with real libpam and synthetic results."""
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.install_sddm_pam import BLOCK, updated

ORIGINAL = (Path(__file__).parent / 'fixtures/sddm.pam').read_bytes()


class SddmPamTests(unittest.TestCase):
    def test_reviewed_change_and_drift(self):
        result = updated(ORIGINAL)
        self.assertEqual(result.replace(BLOCK.encode(), b'', 1), ORIGINAL)
        self.assertLess(result.index(b'user != root'), result.index(b'pam_fprintd.so'))
        with self.assertRaises(RuntimeError):
            updated(ORIGINAL + b'# unreviewed change\n')

    def test_authentication_guards_fallback_and_account(self):
        pam = ctypes.CDLL('libpam.so.0')
        ptr = ctypes.c_void_p
        callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ptr, ptr, ptr)
        callback = callback_type(lambda *_: 19)

        class Conversation(ctypes.Structure):
            _fields_ = [('conv', callback_type), ('data', ptr)]

        conversation = Conversation(callback, None)
        pam.pam_start_confdir.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                         ctypes.POINTER(Conversation), ctypes.c_char_p,
                                         ctypes.POINTER(ptr)]
        for name in ('pam_authenticate', 'pam_acct_mgmt', 'pam_end'):
            getattr(pam, name).argtypes = [ptr, ctypes.c_int]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, module = root / 'mock.c', root / 'mock.so'
            source.write_text('#include <stdlib.h>\n'
                              'int pam_sm_authenticate(void*p,int f,int n,const char**v)'
                              '{(void)p;(void)f;return n ? atoi(v[0]) : 7;}\n')
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(module)], check=True)
            for user, fingerprint, password, account, nologin, expected in (
                ('nobody', 0, 'deny', 'permit', 0, True),
                ('nobody', 7, 'permit', 'permit', 0, True),
                ('nobody', 9, 'permit', 'permit', 0, True),
                ('nobody', 7, 'deny', 'permit', 0, False),
                ('nobody', 0, 'permit', 'deny', 0, False),
                ('root', 0, 'permit', 'permit', 0, False),
                ('nobody', 0, 'permit', 'permit', 7, False),
            ):
                with self.subTest(user=user, fingerprint=fingerprint, password=password,
                                  account=account, nologin=nologin):
                    configuration = updated(ORIGINAL).decode()
                    configuration = configuration.replace('pam_fprintd.so max-tries=1 timeout=15',
                                                          f'{module} {fingerprint}')
                    configuration = configuration.replace('pam_nologin.so', f'{module} {nologin}')
                    # Optional keyring modules are irrelevant to this auth test.
                    configuration = '\n'.join(line for line in configuration.splitlines()
                                              if not line.startswith('-auth'))
                    for include in ('common-auth', 'common-account', 'common-session', 'common-password'):
                        configuration = configuration.replace('@include ' + include,
                                                              '@include ' + str(root / include))
                    (root / 'common-auth').write_text(f'auth required pam_{password}.so\n')
                    (root / 'common-account').write_text(f'account required pam_{account}.so\n')
                    (root / 'common-session').write_text('session required pam_permit.so\n')
                    (root / 'common-password').write_text('password required pam_deny.so\n')
                    (root / 'regis-test').write_text(configuration)
                    handle = ptr()
                    code = pam.pam_start_confdir(b'regis-test', user.encode(),
                                                ctypes.byref(conversation), os.fsencode(root),
                                                ctypes.byref(handle))
                    self.assertEqual(code, 0)
                    try:
                        code = pam.pam_authenticate(handle, 0)
                        if code == 0:
                            code = pam.pam_acct_mgmt(handle, 0)
                        self.assertEqual(code == 0, expected, f'PAM code={code}')
                    finally:
                        pam.pam_end(handle, code)
