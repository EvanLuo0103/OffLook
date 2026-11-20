import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offlook.cli import main
from offlook.core import conversion as cv
from offlook.core.errors import ConversionError
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO


class ConversionPreflight(unittest.TestCase):
    def test_shared_format_contract_and_priority(self):
        with patch.object(cv._BackendProbes, '_probe', side_effect=lambda name: name == 'openpyxl'):
            self.assertEqual(cv.reachable_targets(['ledger.xlsx']), ('.pdf', '.txt', '.csv'))
            auto = dict(cv.conversion_options(['ledger.xlsx']))
            self.assertEqual(auto['.pdf'].code, 'libreoffice')
            self.assertIsNone(auto['.csv'])
            self.assertIsNone(auto['.txt'])
            blocked = dict(cv.conversion_options(['slides.pptx', 'ledger.xlsx'], 'text'))['.pdf']
            self.assertEqual((blocked.code, blocked.source.name), ('excel_pdf_mode', 'ledger.xlsx'))
            self.assertEqual(dict(cv.conversion_options(['slides.pptx'], 'office'))['.docx'].code,
                             'slides_docx_mode')

    def test_backend_fallback_matrix(self):
        probes = cv._BackendProbes
        with patch.object(probes, '_probe', side_effect=lambda name: name in ('pptx', 'docx2pdf')):
            self.assertIsNone(dict(cv.conversion_options(['slides.pptx']))['.pdf'])
            self.assertIsNone(dict(cv.conversion_options(['page.html']))['.pdf'])
            self.assertIsNone(dict(cv.conversion_options(['note.txt'], 'office'))['.pdf'])
            self.assertEqual(dict(cv.conversion_options(['letter.docx']))['.pdf'].code, 'word')
            self.assertEqual(dict(cv.conversion_options(['legacy.xls'], 'text'))['.pdf'].code,
                             'legacy_pdf_mode')
            with self.assertRaisesRegex(ConversionError, 'LibreOffice is required'):
                cv.convert_file('legacy.xls', 'pdf', mode='text')
        with patch.object(probes, '_probe', return_value=False):
            self.assertEqual(dict(cv.conversion_options(['letter.docx']))['.pdf'].code, 'docx2pdf')

    def test_cli_checks_batch_before_writing_and_csv_remains_usable(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp, patch.object(cv, '_find_soffice', return_value=None):
            root = Path(tmp)
            sheet, note = root / 'ledger.xlsx', root / 'note.txt'
            wb = Workbook()
            wb.active['A1'] = 'sample'
            wb.save(sheet)
            wb.close()
            note.write_text('Note', encoding='utf-8')

            def command(*args):
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    status = main(['convert', *map(str, args)])
                return status, out.getvalue(), err.getvalue()

            code, out, err = command(note, sheet, '--to', 'pdf')
            self.assertEqual((code, out), (2, ''))
            self.assertIn('ledger.xlsx: LibreOffice is required', err)
            self.assertEqual(list(root.glob('*.pdf')), [])
            self.assertIn('unavailable in Text mode', command(sheet, '--to', 'pdf', '--mode', 'text')[2])
            self.assertEqual(command(sheet, '--list-targets')[1].splitlines(), ['pdf', 'txt', 'csv'])
            self.assertEqual(command(sheet, '--to', 'csv')[0], 0)
            self.assertEqual((root / 'ledger.csv').read_text(encoding='utf-8').strip(), 'sample')
