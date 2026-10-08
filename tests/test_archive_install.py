import importlib.util
from pathlib import Path
import sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
def package(name, root):
 s=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
 m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m)
package('playlite_plugins.cracktools',ROOT.parent/'playlite-plugin-crack-tools')
package('gcw_test',ROOT)
from gcw_test.archive_install import analyze,install
from gcw_test.backup import restore
class Tests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
  self.game=self.root/'game';self.game.mkdir();(self.game/'game.exe').write_bytes(b'original')
  self.archive=self.root/'fix.zip'
  with zipfile.ZipFile(self.archive,'w') as z:
   z.writestr('Fix/game.exe',b'replacement');z.writestr('Fix/config/new.json',b'config')
  self.request=dict(InstallDirectory=str(self.game),ArchiveFile=str(self.archive),ArchiveMappings=[dict(source='Fix/game.exe',path='game.exe'),dict(source='Fix/config/new.json',path='config/new.json')])
 def test_install_restore(self):
  self.assertTrue(install(self.request)['Success']);self.assertEqual((self.game/'game.exe').read_bytes(),b'replacement')
  (self.game/'user.dat').write_text('user');restore(self.game)
  self.assertEqual((self.game/'game.exe').read_bytes(),b'original');self.assertFalse((self.game/'config').exists());self.assertEqual((self.game/'user.dat').read_text(),'user')
 def test_traversal(self):
  with zipfile.ZipFile(self.archive,'w') as z:z.writestr('../bad.exe',b'bad')
  with self.assertRaisesRegex(ValueError,'Unsafe'):analyze(self.archive)
 def test_links(self):
  with zipfile.ZipFile(self.archive,'w') as z:
   e=zipfile.ZipInfo('link');e.external_attr=0o120777<<16;z.writestr(e,'outside')
  with self.assertRaisesRegex(ValueError,'links'):analyze(self.archive)
 def test_failure_rollback(self):
  from gcw_test import archive_install as a
  copy=a.shutil.copyfile
  def fail(source,target,*args,**kwargs):
   if str(target).endswith('new.json.playlite-install-tmp'):raise OSError('write failure')
   return copy(source,target,*args,**kwargs)
  with patch.object(a.shutil,'copyfile',side_effect=fail):
   with self.assertRaisesRegex(OSError,'write failure'):install(self.request)
  self.assertEqual((self.game/'game.exe').read_bytes(),b'original');self.assertFalse((self.game/'config').exists())
 def test_previous_install_is_restored_before_reinstallation(self):
  install(self.request)
  self.assertTrue(install(self.request)['Success'])
  restore(self.game)
  self.assertEqual((self.game/'game.exe').read_bytes(),b'original')
  self.assertFalse((self.game/'config').exists())

 def test_payload_folder_suggestion_matches_game_files(self):
  from gcw_test.archive_install import suggested_base
  rows=[dict(path='readme.txt'),dict(path='files/game.exe'),dict(path='files/steam_api.dll')]
  self.assertEqual(suggested_base(rows,self.game),'files/')

 def test_invalid_previous_backup_blocks_installation(self):
  install(self.request)
  backup=self.game/'.playlite-steamautocrack'
  (backup/'original-0').write_bytes(b'corrupt')
  with self.assertRaisesRegex(ValueError,'verification failed'):install(self.request)
  self.assertEqual((self.game/'game.exe').read_bytes(),b'replacement')
  self.assertTrue((backup/'manifest.json').exists())
