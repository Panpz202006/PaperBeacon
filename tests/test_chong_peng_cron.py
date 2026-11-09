"""Cron installation preserves unrelated jobs and is safe to repeat."""
from pathlib import Path
import unittest
from scripts.install_chong_peng_cron import BEGIN, END, build_crontab


class ChongPengCronTests(unittest.TestCase):
    def test_existing_jobs_are_preserved_and_managed_job_is_idempotent(self):
        original = 'MAILTO=""\n0 9 * * * /bin/echo existing-job\n'
        root = Path('/tmp/PaperBeacon')
        installed = build_crontab(original, root)
        self.assertTrue(installed.startswith(original))
        self.assertEqual(installed.count(BEGIN), 1)
        self.assertIn('*/5 * * * * /bin/bash /tmp/PaperBeacon/scripts/chong_peng_daily.sh', installed)
        self.assertEqual(build_crontab(installed, root), installed)

    def test_invalid_markers_do_not_delete_other_jobs(self):
        for original in (BEGIN+'\n0 9 * * * important-job\n',
                         BEGIN+'\n'+BEGIN+'\n'+END+'\n', END+'\n'+BEGIN+'\n'):
            with self.assertRaises(ValueError):
                build_crontab(original, Path('/tmp/PaperBeacon'))

    def test_shell_and_cron_special_characters_are_escaped(self):
        result = build_crontab('', Path('/tmp/Paper Beacon%copy'))
        self.assertIn("'/tmp/Paper Beacon\\%copy/scripts/chong_peng_daily.sh'", result)
        self.assertIn('chong-peng-daily-error.log', result)
