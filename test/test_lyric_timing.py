import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('analyze_lyric_timing', ROOT / 'scripts' / 'analyze_lyric_timing.py')
analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyzer)


class LyricTimingTest(unittest.TestCase):
    def test_weight_lines_counts_longer_lines_more(self):
        short = analyzer.line_weight('Oh')
        long = analyzer.line_weight('I found a little rhythm in a stranger open hand')
        self.assertGreater(long, short)

    def test_map_lines_to_phrases_is_monotonic_and_in_bounds(self):
        lines = [
            {'index': 0, 'sectionIndex': 0, 'section': 'Verse', 'text': 'Hello world'},
            {'index': 1, 'sectionIndex': 0, 'section': 'Verse', 'text': 'Sing it again'},
            {'index': 2, 'sectionIndex': 1, 'section': 'Chorus', 'text': 'Ring the bell'},
        ]
        sections = [
            {'index': 0, 'label': 'Verse', 'lineStart': 0, 'lineEnd': 1},
            {'index': 1, 'label': 'Chorus', 'lineStart': 2, 'lineEnd': 2},
        ]
        timing = analyzer.map_lines_to_phrases(lines, sections, [(10.0, 20.0), (25.0, 35.0)], 40.0, 'test')
        starts = [line['start'] for line in timing['lines']]
        ends = [line['end'] for line in timing['lines']]
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(10.0 <= x <= 35.0 for x in starts))
        self.assertTrue(all(e > s for s, e in zip(starts, ends)))
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(timing['sections'][0]['start'], timing['lines'][0]['start'])
        self.assertEqual(timing['sections'][1]['end'], timing['lines'][2]['end'])


if __name__ == '__main__':
    unittest.main()
