"""Reviewed archive overlays using the shared verified backup manifest."""
import fcntl
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import zipfile
from .backup import BACKUP, LOCK, checked_path, digest, directories, files, finalize, restore, write_json

LIMIT = 2 * 1024**3


def member_path(name):
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or not path.parts or any(':' in part or part in (BACKUP, LOCK) for part in path.parts):
        raise ValueError('Unsafe archive path: ' + name)
    return path.as_posix()


def analyze(archive):
    archive = Path(archive)
    rows = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                name = member_path(entry.filename)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError('Archive links are not supported.')
                if not entry.is_dir():
                    rows.append(dict(source=entry.filename, path=name, size=entry.file_size))
    else:
        binary = shutil.which('7zz') or shutil.which('7z')
        if not binary:
            raise ValueError('Install 7-Zip to open RAR and 7z archives.')
        result = subprocess.run([binary, 'l', '-slt', '-ba', '-p', '--', str(archive)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError('Cannot read archive. Password-protected archives are not supported.')
        for block in result.stdout.split('\n\n'):
            values = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
            if 'Path' not in values:
                continue
            name = member_path(values['Path'])
            if any(values.get(key) for key in ('Symbolic Link', 'Hard Link')) or 'l' in values.get('Attributes', ''):
                raise ValueError('Archive links are not supported.')
            if values.get('Folder') == '+' or values.get('Attributes', '').startswith('D'):
                continue
            rows.append(dict(source=values['Path'], path=name, size=int(values.get('Size', '0'))))
    if not rows or len(rows) > 5000 or sum(row['size'] for row in rows) > LIMIT:
        raise ValueError('Archive is empty or exceeds the 2 GiB / 5000 file limit.')
    if len({row['path'].casefold() for row in rows}) != len(rows):
        raise ValueError('Archive contains duplicate file paths.')
    return rows


def suggested_base(rows, game_directory):
    root = Path(game_directory)
    prefixes = {''}
    for row in rows:
        parts = Path(row['path']).parts
        prefixes.update('/'.join(parts[:index]) + '/' for index in range(1, len(parts)))
    def score(prefix):
        matches = [row['path'][len(prefix):] for row in rows if row['path'].startswith(prefix)]
        return sum(10 if Path(relative).suffix.lower() == '.exe' else 1
                   for relative in matches if (root / relative).is_file())
    best = max(sorted(prefixes, key=lambda value: (len(value), value)), key=score)
    return best


def install(request, cancel=lambda: False, status=lambda text: None):
    root = Path(request['InstallDirectory']).expanduser()
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('Choose an installed game folder.')
    root = root.resolve()
    archive = Path(request['ArchiveFile'])
    def check():
        if cancel():
            raise ValueError('Cancelled.')
    rows = analyze(archive)
    available = {row['source']: row for row in rows}
    selected = request['ArchiveMappings']
    if not selected:
        raise ValueError('Select files to install.')
    targets = set()
    for row in selected:
        if row['source'] not in available:
            raise ValueError('Archive changed after analysis. Analyze it again.')
        relative = member_path(row['path'])
        row['path'] = relative
        if relative.casefold() in targets:
            raise ValueError('Multiple files map to the same destination.')
        targets.add(relative.casefold())
        checked_path(root, relative)
    if (root / LOCK).is_symlink():
        raise ValueError('Game lock cannot be a symlink.')
    with (root / LOCK).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backup = root / BACKUP
        with tempfile.TemporaryDirectory(prefix='playlite-archive-') as temporary:
            staging = Path(temporary)
            is_zip = zipfile.is_zipfile(archive)
            bundle = zipfile.ZipFile(archive) if is_zip else None
            try:
                for index, row in enumerate(selected):
                    check()
                    status('Preparing ' + row['path'])
                    output = staging / str(index)
                    if bundle:
                        with bundle.open(row['source']) as source, output.open('wb') as target:
                            total = 0
                            while chunk := source.read(1024 * 1024):
                                check(); total += len(chunk)
                                if total > available[row['source']]['size']:
                                    raise ValueError('Archive file exceeds its declared size.')
                                target.write(chunk)
                    else:
                        binary = shutil.which('7zz') or shutil.which('7z')
                        with output.open('wb') as target:
                            result = subprocess.run([binary, 'e', '-so', '-spd', '-p', '--', str(archive), row['source']], stdout=target, stderr=subprocess.PIPE, timeout=120)
                        if result.returncode:
                            raise ValueError('Cannot extract ' + row['source'])
                    if output.stat().st_size != available[row['source']]['size']:
                        raise ValueError('Extracted file size does not match archive.')
            finally:
                if bundle: bundle.close()
            check()
            if (backup / 'manifest.json').is_file():
                status('Restoring the previous installation before applying this archive…')
                restore(root, check, status)
            elif backup.exists() and any(p.name != 'recovery' for p in backup.iterdir()):
                raise ValueError('The previous backup has no manifest; review it before installing.')
            existing = files(root)
            original_dirs = directories(root)
            backup.mkdir(mode=0o700, exist_ok=True)
            entries = []
            try:
                for index, row in enumerate(selected):
                    check()
                    target = checked_path(root, row['path'])
                    if target.exists():
                        if not target.is_file():
                            raise ValueError('Destination is not a file: ' + row['path'])
                        saved = 'original-' + str(index)
                        expected = digest(target)
                        shutil.copy2(target, backup / saved)
                        if digest(backup / saved) != expected or digest(target) != expected:
                            raise ValueError('Original file changed during backup.')
                        entries.append(dict(path=row['path'], backup=saved, original=expected, applied=expected))
                write_json(backup / 'manifest.json', dict(Backend='archive', FileSet=list(existing), OriginalDirectories=original_dirs, Status='Applying', files=entries))
            except Exception:
                from .backup import clear_backup
                clear_backup(backup)
                raise
            try:
                for index, row in enumerate(selected):
                    check()
                    status('Installing ' + row['path'])
                    target = checked_path(root, row['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    staged = target.with_name(target.name + '.playlite-install-tmp')
                    if staged.exists():
                        raise ValueError('Temporary destination already exists.')
                    try:
                        shutil.copyfile(staging / str(index), staged)
                        if digest(staged) != digest(staging / str(index)):
                            raise ValueError('Installed file verification failed.')
                        staged.replace(target)
                    finally:
                        staged.unlink(missing_ok=True)
                finalize(root)
            except Exception:
                finalize(root)
                restore(root, status=status)
                raise
    return dict(Success=True, Message='Archive installed. Originals are backed up for restoration.')


def process(request, cancel=lambda: False, status=lambda text: None):
    if request.get('Restore'):
        from playlite_plugins.cracktools.guards import restore_game as recover
        return recover(request, cancel, status)
    return install(request, cancel, status)
