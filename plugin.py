from pathlib import Path
from PyQt6.QtCore import Qt, QUrl, QThreadPool, QStandardPaths
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QWizard, QWizardPage, QVBoxLayout, QLabel, QPushButton, QLineEdit, QTreeWidget, QTreeWidgetItem, QComboBox, QListWidget, QHBoxLayout, QGroupBox
from playlite.providers import GenericPlugin
from playlite.lifecycle import run_dialog, choose_file, show_warning
from urllib.parse import urlencode
import threading


class ArchiveProgressMixin:
    plugin_id = 'GameCopyWorld'


class Wizard(QWizard):
    def __init__(self, plugin, window, game):
        super().__init__(window)
        self.plugin, self.window, self.game = plugin, window, dict(game)
        self.rows = []
        self.tasks = set()
        self.lookup_generation = 0
        self.patch_generation = 0
        self.archive_generation = 0
        self.closed = False
        self.cancel_downloads = threading.Event()
        self.finished.connect(self.finish_work)
        self.setWindowTitle('Install from GameCopyWorld')
        self.resize(1000, 650)
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Install selected files')
        self.button(QWizard.WizardButton.FinishButton).setProperty('primary',True)
        source = QWizardPage()
        source.setTitle('Find and download a file')
        layout = QVBoxLayout(source)
        layout.setSpacing(16)
        label = QLabel('Choose a matching game, then download the fixed files for your installed version.')
        label.setWordWrap(True)
        layout.addWidget(label)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(game['Name']), 1)
        search = QPushButton('Search again')
        search.clicked.connect(self.lookup)
        search_row.addWidget(search)
        layout.addLayout(search_row)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        games = QGroupBox('Games')
        games_layout = QVBoxLayout(games)
        games_layout.setSpacing(12)
        self.results = QListWidget()
        self.results.itemActivated.connect(self.select_game)
        games_layout.addWidget(self.results, 1)
        load = QPushButton('Show downloads')
        load.clicked.connect(lambda: self.select_game(self.results.currentItem()))
        games_layout.addWidget(load)
        columns.addWidget(games, 2)
        patches = QGroupBox('Fixed files')
        patches_layout = QVBoxLayout(patches)
        patches_layout.setSpacing(12)
        self.patch_list = QListWidget()
        self.patch_list.itemActivated.connect(self.download_patch)
        patches_layout.addWidget(self.patch_list, 1)
        download = QPushButton('Download selected file')
        download.clicked.connect(lambda: self.download_patch(self.patch_list.currentItem()))
        patches_layout.addWidget(download)
        columns.addWidget(patches, 3)
        layout.addLayout(columns, 1)
        local = QGroupBox('Downloaded archive')
        local_layout = QVBoxLayout(local)
        local_layout.setSpacing(12)
        self.archive = QLineEdit()
        self.archive.setReadOnly(True)
        self.archive.setPlaceholderText('Download a file above or choose an existing ZIP, RAR or 7z archive')
        local_layout.addWidget(self.archive)
        alternatives = QHBoxLayout()
        self.pick = QPushButton('Choose archive…')
        self.pick.clicked.connect(self.choose)
        alternatives.addWidget(self.pick)
        alternatives.addStretch()
        browser = QPushButton('Open website in browser')
        browser.clicked.connect(self.search)
        alternatives.addWidget(browser)
        local_layout.addLayout(alternatives)
        layout.addWidget(local)
        self.message = QLabel('Choose fixed files matching your game version, then review the contents before installing.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        source.isComplete = lambda: bool(self.rows)
        self.source_page = source
        self.addPage(source)
        preview = QWizardPage()
        preview.setTitle('Review the files to install')
        layout = QVBoxLayout(preview)
        target = QLabel('Game folder: ' + game['InstallDirectory'])
        target.setWordWrap(True)
        layout.addWidget(target)
        layout.addWidget(QLabel('Choose the archive folder containing the replacement files:'))
        self.base = QComboBox()
        self.base.currentIndexChanged.connect(self.preview)
        layout.addWidget(self.base)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Archive file', 'Game destination', 'Action'])
        layout.addWidget(self.tree)
        explanation = QLabel('Checked files will be copied to the shown game paths. Existing files are backed up; added files are recorded for removal on restore. Uncheck documentation or files you do not want installed.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        preview.isComplete = lambda: any(self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked for i in range(self.tree.topLevelItemCount()))
        self.review_summary = QLabel()
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)
        def summarize():
            selected = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())
                        if self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
            replaced = sum(item.text(2).lower().startswith(('replace', 'overwrite')) for item in selected)
            self.review_summary.setText(f'{len(selected)} files selected · {replaced} existing files to replace · Backups kept in the game folder')
            preview.completeChanged.emit()
        self.update_review_summary = summarize
        self.tree.itemChanged.connect(summarize)
        self.addPage(preview)

    def search(self):
        QDesktopServices.openUrl(QUrl('https://gamecopyworld.eu/games/search_results.shtml?' + urlencode({'q': self.game['Name']})))

    def finish_work(self, *_):
        self.closed = True
        self.cancel_downloads.set()

    def background(self, work, complete, failed=None, *, current=lambda: True):
        from playlite.tasks import Task
        task = Task(work)
        self.tasks.add(task)
        def success(value):
            self.tasks.discard(task)
            if not self.closed and current():
                complete(value)
        def failure(error):
            self.tasks.discard(task)
            if self.closed or not current():
                return
            if failed:
                failed(error)
            else:
                self.message.setText(str(error) + ' You can use the browser and file picker instead.')
        task.bind(self, success, failure)
        QThreadPool.globalInstance().start(task)

    def lookup(self):
        from .web_catalogue import search
        self.lookup_generation += 1
        self.patch_generation += 1
        generation = self.lookup_generation
        self.results.clear(); self.patch_list.clear()
        self.message.setText('Searching GameCopyWorld’s game index…')
        def complete(rows):
            if generation != self.lookup_generation:
                return
            from PyQt6.QtWidgets import QListWidgetItem
            for row in rows:
                item = QListWidgetItem(row['title']); item.setData(Qt.ItemDataRole.UserRole, row['url']); self.results.addItem(item)
            self.message.setText('Select a game and show its downloads.' if rows else 'No matching games found. Try the browser search.')
            if rows: self.results.setCurrentRow(0)
        self.background(lambda: search(self.game['Name']), complete, current=lambda: generation == self.lookup_generation)

    def select_game(self, item):
        if item is None: return
        from .web_catalogue import patches
        self.patch_generation += 1
        generation = self.patch_generation
        url = item.data(Qt.ItemDataRole.UserRole)
        self.patch_list.clear(); self.message.setText('Loading available downloads…')
        def complete(rows):
            if generation != self.patch_generation:
                return
            from PyQt6.QtWidgets import QListWidgetItem
            for row in rows:
                entry = QListWidgetItem(row['title']); entry.setData(Qt.ItemDataRole.UserRole, row['url']); self.patch_list.addItem(entry)
            self.message.setText('Choose a file matching your game version. Only fixed-file downloads are listed.' if rows else 'No downloads could be read. Use the browser instead.')
            if rows: self.patch_list.setCurrentRow(0)
        self.background(lambda: patches(url), complete, current=lambda: generation == self.patch_generation)

    def download_patch(self, item):
        if item is None: return
        from .web_catalogue import download
        self.archive_generation += 1
        generation = self.archive_generation
        url = item.data(Qt.ItemDataRole.UserRole)
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home() / 'Downloads')
        self.message.setText('Downloading selected archive…')
        def failed(error):
            if generation != self.archive_generation:
                return
            self.message.setText(str(error) + ' Opening the selected download in your browser; select the archive when finished.')
            QDesktopServices.openUrl(QUrl(url))
        def complete(path):
            if generation == self.archive_generation:
                self.analyze_file(path)
        self.background(lambda: download(url, folder, cancel=self.cancel_downloads.is_set), complete, failed)

    def choose(self):
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home() / 'Downloads')
        archive, _ = choose_file(self, 'Choose downloaded archive', downloads, 'Archives (*.zip *.rar *.7z);;All files (*)')
        if not archive:
            return
        self.analyze_file(archive)

    def analyze_file(self, archive):
        self.archive_generation += 1
        generation = self.archive_generation
        self.rows = []
        self.source_page.completeChanged.emit()
        self.archive.setText(archive)
        self.pick.setEnabled(False)
        self.message.setText('Analyzing archive…')
        from .archive_install import analyze
        def complete(rows):
            if generation != self.archive_generation:
                return
            self.rows = rows
            self.pick.setEnabled(True)
            self.message.setText(str(len(rows)) + ' files found. Continue to review the installation paths.')
            prefixes = {''}
            for row in rows:
                parts = Path(row['path']).parts
                prefixes.update('/'.join(parts[:i]) + '/' for i in range(1, len(parts)))
            self.base.blockSignals(True)
            self.base.clear()
            for prefix in sorted(prefixes):
                self.base.addItem(prefix or '(Archive root)', prefix)
            from .archive_install import suggested_base
            suggested = suggested_base(rows, self.game['InstallDirectory'])
            self.base.setCurrentIndex(self.base.findData(suggested))
            self.base.blockSignals(False)
            self.preview()
            self.source_page.completeChanged.emit()
        def failed(error):
            if generation != self.archive_generation:
                return
            self.pick.setEnabled(True)
            self.message.setText(str(error))
        self.background(lambda: analyze(archive), complete, failed)

    def preview(self):
        self.tree.clear()
        base = self.base.currentData() or ''
        root = Path(self.game['InstallDirectory'])
        for row in self.rows:
            if not row['path'].startswith(base):
                continue
            relative = row['path'][len(base):]
            item = QTreeWidgetItem([row['path'], relative, 'Replace' if (root / relative).exists() else 'Add'])
            item.setData(0, Qt.ItemDataRole.UserRole, dict(source=row['source'], path=relative))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked if Path(relative).suffix.lower() in ('.txt', '.nfo', '.pdf', '.html') else Qt.CheckState.Checked)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        self.update_review_summary()

    def accept(self):
        mappings = [self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if not mappings:
            return
        try:
            self.plugin.ensure_stopped(self.window, self.game)
        except ValueError as error:
            show_warning(self, 'GameCopyWorld', str(error))
            return
        self.request = dict(InstallDirectory=self.game['InstallDirectory'], ArchiveFile=self.archive.text(), ArchiveMappings=mappings)
        super().accept()


class Plugin(GenericPlugin):
    def ensure_stopped(self, window, game):
        from playlite_plugins.cracktools.guards import ensure_stopped
        ensure_stopped(window, game)

    def game_actions(self, window, game):
        if not game.get('InstallDirectory') or game.get('ArchivePath'):
            return []
        actions = [('Install from downloaded archive…', lambda: self.run(window, game))]
        if (Path(game['InstallDirectory']) / '.playlite-steamautocrack/manifest.json').is_file():
            actions.append(('Restore originals…', lambda: self.run(window, game, restore=True)))
        return actions

    def run(self, window, game, restore=False):
        from playlite_plugins.cracktools.progress import ToolProgress
        class Progress(ArchiveProgressMixin, ToolProgress):
            pass
        try:
            self.ensure_stopped(window, game)
            if restore:
                request = dict(InstallDirectory=game['InstallDirectory'], Restore=True)
            else:
                wizard = Wizard(self, window, game)
                wizard.lookup()
                if run_dialog(wizard) != QWizard.DialogCode.Accepted:
                    return
                request = wizard.request
            dialog = Progress(request, window)
            dialog.setWindowTitle('GameCopyWorld')
            run_dialog(dialog)
        except (ValueError, OSError) as error:
            show_warning(window, 'GameCopyWorld', str(error))
