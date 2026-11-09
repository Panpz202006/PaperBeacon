"""Future recipient changes must not leak addresses through files or commit identities."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts.check_recipient_privacy import audit_identity, audit_tracked_files, is_private


class RecipientPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Privacy Test')
        self.git('config', 'user.email', 'developer@example.org')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT)

    def test_reserved_examples_and_public_noreply_identities_are_allowed(self):
        for value in (b'recipient@example.org', b'developer@example.com',
                      b'123+user@users.noreply.github.com', b'noreply@github.com',
                      b"'noreply@github.com"):
            self.assertFalse(is_private(value))
        self.assertTrue(is_private(b'recipient' + b'@' + b'mail-provider.com'))

    def test_guard_checks_exact_staged_content_and_redacts_matches(self):
        private = b'recipient' + b'@' + b'mail-provider.com'
        file = self.root/'profile.txt'
        file.write_bytes(private + b'\n')
        self.git('add', 'profile.txt')
        file.write_text('recipient@example.org\n')
        self.assertEqual(audit_tracked_files(self.root), [])
        findings = audit_tracked_files(self.root, staged=True)
        self.assertEqual(findings, ['profile.txt:1: non-placeholder email address'])
        self.assertNotIn(private.decode(), '\n'.join(findings))

    def test_personal_author_and_committer_overrides_are_detected(self):
        private = 'recipient' + '@' + 'mail-provider.com'
        with patch.dict(os.environ, {'GIT_AUTHOR_EMAIL': private, 'GIT_COMMITTER_EMAIL': private}):
            findings = audit_identity(self.root)
        self.assertEqual(len(findings), 2)
        self.assertNotIn(private, '\n'.join(findings))

    def test_ignored_private_files_are_not_scanned_but_force_added_files_are(self):
        (self.root/'.gitignore').write_text('.env.private\n')
        self.git('add', '.gitignore')
        private = self.root/'.env.private'
        private.write_bytes(b'SCOUT_EMAIL_TO=' + b'recipient' + b'@' + b'mail-provider.com\n')
        self.assertEqual(audit_tracked_files(self.root), [])
        self.git('add', '-f', '.env.private')
        self.assertEqual(len(audit_tracked_files(self.root, staged=True)), 1)
