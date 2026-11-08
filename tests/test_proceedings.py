"""Independent retrieval, exact venue boundaries, and source failure isolation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from literature_scout.exploration import explore, STREAMS
from literature_scout.http_client import ResponseFormatError, RateLimitError
from literature_scout.models import Paper
from literature_scout.sources.proceedings import Proceedings, crossref_year


class ProceedingsTests(unittest.TestCase):
    def test_official_html_routes_exclude_other_years_and_workshops(self):
        cases = [
            ('NeurIPS', '/paper_files/paper/2024/hash/abc123-Abstract-Conference.html',
             '/paper_files/paper/2024/hash/abc123-Abstract-Workshop.html'),
            ('CVPR', '/content/CVPR2024/html/Author_Title_CVPR_2024_paper.html',
             '/content/CVPR2024W/html/Author_Title_CVPR_2024_paper.html'),
            ('IJCAI', '/proceedings/2024/1', '/proceedings/2023/1'),
            ('ICLR', '/virtual/2024/poster/123', '/virtual/2024/workshop/123'),
        ]
        for venue, good, bad in cases:
            with self.subTest(venue=venue):
                client = Mock()
                client.request.return_value = (f'<html><a href="{good}">Survival <em>&amp;</em> Anomaly</a>'
                                               f'<a href="{good}">Details</a><a href="{bad}">Wrong</a></html>').encode()
                papers, status = Proceedings(client).enumerate_year(venue, 2024)
                self.assertEqual(len(papers), 1)
                self.assertEqual(papers[0].title, 'Survival & Anomaly')
                self.assertEqual(papers[0].venue_raw, venue)
                self.assertTrue(status['pagination_complete'])

    def test_empty_or_truncated_pages_are_not_success(self):
        for raw in (b'<html>Challenge page</html>',
                    b'<a href="/virtual/2024/poster/1">Paper</a>'):
            client = Mock()
            client.request.return_value = raw
            with self.assertRaises(ValueError):
                Proceedings(client).enumerate_year('ICLR', 2024)

    def test_neurips_follows_main_volume_instead_of_creative_track(self):
        client = Mock()
        client.request.side_effect = [
            b'<html><a href="/paper_files/paper/2025/vol38-main-conference">Main Conference</a></html>',
            b'<html><a href="/paper_files/paper/2025/hash/abc123-Abstract-Conference.html">Anomaly detection</a></html>']
        papers, status = Proceedings(client).enumerate_year('NeurIPS', 2025)
        self.assertEqual(len(papers), 1)
        self.assertTrue(status['url'].endswith('/vol38-main-conference'))

    def test_neurips_includes_published_tracks_and_checks_declared_count(self):
        client = Mock()
        raw = '<html><span class="paper-count">3 papers</span>' + ''.join(
            f'<a href="/paper_files/paper/2025/hash/{i}-Abstract-{track}.html">Paper {i}</a>'
            for i, track in enumerate(['Conference', 'Datasets_and_Benchmarks_Track', 'Position_Paper_Track'])) + '</html>'
        client.request.return_value = raw.encode()
        papers, _ = Proceedings(client).enumerate_year('NeurIPS', 2025)
        self.assertEqual(len(papers), 3)
        client.request.return_value = raw.replace('3 papers', '4 papers').encode()
        with self.assertRaisesRegex(ValueError, 'declared proceedings total'):
            Proceedings(client).enumerate_year('NeurIPS', 2025)

    def test_all_venues_continue_after_one_venue_fails(self):
        client = Mock()
        client.json.side_effect = ResponseFormatError('DBLP returned HTML')
        def retrieve(venue, year):
            if venue == 'NeurIPS':
                raise RuntimeError('Proceedings not available')
            return [Paper(title=f'Survival {venue} {year}', year=year, venue_raw=venue)], {
                'venue': venue, 'year': year, 'source': 'official', 'retrieved': 1, 'pagination_complete': True}
        with tempfile.TemporaryDirectory() as tmp, patch(
                'literature_scout.exploration.Proceedings') as factory:
            factory.return_value.enumerate_year.side_effect = retrieve
            result = explore('survival', tmp, since=2023, until=2024, client=client)
            coverage = json.loads((Path(tmp)/'coverage.json').read_text())
            self.assertEqual(len(coverage), 14)
            self.assertEqual(factory.return_value.enumerate_year.call_count, 14)
            self.assertEqual({p.venue_canonical for p in result.papers}, set(STREAMS) - {'NeurIPS'})
            client.json.assert_called_once()  # DBLP outage is not repeatedly retried.

    def test_rate_limit_defers_only_the_affected_source(self):
        client = Mock()
        client.json.side_effect = ResponseFormatError('DBLP unavailable')
        def retrieve(venue, year):
            if venue == 'NeurIPS':
                raise RateLimitError('Retry-After cooldown')
            return [Paper(title=f'Anomaly detection {year}', year=year, venue_raw=venue)], {
                'venue': venue, 'year': year, 'retrieved': 1, 'pagination_complete': True}
        with tempfile.TemporaryDirectory() as tmp, patch(
                'literature_scout.exploration.Proceedings') as factory:
            factory.return_value.enumerate_year.side_effect = retrieve
            result = explore('anomaly', tmp, since=2023, until=2024, client=client, venues=['NeurIPS', 'CVPR'])
            self.assertEqual(factory.return_value.enumerate_year.call_count, 3)
            self.assertEqual(len(result.papers), 2)

    def test_crossref_exhausts_cursor_and_filters_main_proceedings(self):
        def item(doi, container):
            return {'DOI': doi, 'title': ['Anomaly detection'], 'container-title': [container],
                    'published': {'date-parts': [[2024, 10, 28]]}}
        client = Mock()
        client.json.side_effect = [
            {'message': {'total-results': 3, 'next-cursor': 'page2', 'items': [
                item('10.1145/one', 'Proceedings of the 32nd ACM International Conference on Multimedia'),
                item('10.1145/two', 'Proceedings of the 32nd ACM Multimedia Workshop')]}},
            {'message': {'total-results': 3, 'items': [
                item('10.1145/three', 'Companion Proceedings of the 32nd ACM International Conference on Multimedia')]}}]
        papers, status = crossref_year(client, 'ACM MM', 2024)
        self.assertEqual(len(papers), 1)
        self.assertEqual(status['scanned_records'], 3)
        self.assertEqual(client.json.call_args.args[1]['cursor'], 'page2')

    def test_crossref_truncation_is_failure(self):
        client = Mock()
        client.json.return_value = {'message': {'total-results': 10, 'items': []}}
        with self.assertRaises(RuntimeError):
            crossref_year(client, 'AAAI', 2024)
