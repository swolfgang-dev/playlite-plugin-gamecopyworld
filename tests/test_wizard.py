import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QWidget

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gcw_ui_source', ROOT / '__init__.py',
                                             submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from gcw_ui_source.plugin import Wizard

APP = QApplication.instance() or QApplication([])


class WizardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.window = QWidget()
        self.wizard = Wizard(Mock(), self.window, dict(Id='one', Name='Example', InstallDirectory=temporary.name))
        self.addCleanup(self.window.close)
        self.addCleanup(self.wizard.reject)

    def test_picker_unpacks_filename_and_cancel_does_not_analyze(self):
        with patch('gcw_ui_source.plugin.choose_file', return_value=('', '')), \
                patch.object(self.wizard, 'analyze_file') as analyze:
            self.wizard.choose()
            analyze.assert_not_called()
        with patch('gcw_ui_source.plugin.choose_file', return_value=('/tmp/chosen.zip', 'Archives')), \
                patch.object(self.wizard, 'analyze_file') as analyze:
            self.wizard.choose()
            analyze.assert_called_once_with('/tmp/chosen.zip')

    def test_slow_previous_game_result_cannot_replace_current_downloads(self):
        pool = Mock()
        with patch('gcw_ui_source.plugin.QThreadPool.globalInstance', return_value=pool), \
                patch('gcw_ui_source.web_catalogue.patches', side_effect=lambda url: [{'title': url, 'url': url}]):
            for url in ('first', 'second'):
                item = QListWidgetItem(url)
                item.setData(Qt.ItemDataRole.UserRole, url)
                self.wizard.select_game(item)
            first, second = [call.args[0] for call in pool.start.call_args_list]
            second.run()
            first.run()
        self.assertEqual(self.wizard.patch_list.count(), 1)
        self.assertEqual(self.wizard.patch_list.item(0).text(), 'second')
        self.assertFalse(self.wizard.tasks)

    def test_closed_wizard_drops_late_results_and_cancels_downloads(self):
        pool = Mock()
        with patch('gcw_ui_source.plugin.QThreadPool.globalInstance', return_value=pool):
            self.wizard.background(lambda: 'late', Mock(side_effect=AssertionError('Closed view callback')))
        self.wizard.reject()
        self.assertTrue(self.wizard.cancel_downloads.is_set())
        pool.start.call_args.args[0].run()
        self.assertFalse(self.wizard.tasks)
