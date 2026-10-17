import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import io,tempfile,unittest
from unittest.mock import patch
import web_catalogue as web

class Tests(unittest.TestCase):
 def test_game_name_ignores_punctuation(self):
  with patch.object(web,'html',return_value='<a href="pc_game.shtml">A Plague Tale: Innocence</a><a href="pc_other.shtml">Other Game</a>'):
   rows=web.search('A Plague Tale Innocence')
  self.assertEqual(len(rows),1)
 def test_patch_links_decode_entities(self):
  with patch.object(web,'html',return_value="<a name=\"Game Fixed Files\"></a><a onmousedown=\"cbox('https://dl.gamecopyworld.eu/?a=0&amp;f=game-v1!7z')\">"):
   rows=web.patches(web.BASE+'pc_game.shtml')
  self.assertEqual(rows[0]['title'],'game-v1.7z')
  self.assertNotIn('&amp;',rows[0]['url'])
 def test_binary_download_is_saved(self):
  body=b'7z\xbc\xaf\x27\x1c'+b'test archive'
  with tempfile.TemporaryDirectory() as root,patch.object(web,'fetch',side_effect=lambda url:io.BytesIO(body)):
   path=web.download('https://dl.gamecopyworld.eu/',root)
   self.assertEqual(Path(path).read_bytes(),body)
 def test_html_page_is_not_saved_as_archive(self):
  with tempfile.TemporaryDirectory() as root,patch.object(web,'fetch',return_value=io.BytesIO(b'<html>Browser required</html>')):
   with self.assertRaisesRegex(ValueError,'browser'):web.download('https://dl.gamecopyworld.eu/',root)
   self.assertFalse(list(Path(root).iterdir()))
 def test_cancellation_removes_partial_archive(self):
  cancelled=[]
  class Response(io.BytesIO):
   def read(self, size=-1):
    result=super().read(size)
    if size>8:cancelled.append(True)
    return result
  with tempfile.TemporaryDirectory() as root,patch.object(web,'fetch',return_value=Response(b'PK123456payload')):
   with self.assertRaisesRegex(ValueError,'cancelled'):
    web.download('https://dl.gamecopyworld.eu/',root,cancel=lambda:bool(cancelled))
   self.assertFalse(list(Path(root).iterdir()))
 def test_external_links_not_automatically_fetched(self):
  self.assertFalse(web.allowed('https://gamecopyworld.eu.evil.example/file.zip'))
  self.assertFalse(web.allowed('file:///tmp/archive.zip'))

 def test_mirror_page_follows_next_mirror_after_failure(self):
  class Response(io.BytesIO):
   url='https://dl.gamecopyworld.eu/'
  page=Response(b'<a href="https://g1.gamecopyworld.eu/?x=one">MIRROR #01</a><a href="https://g2.gamecopyworld.eu/?x=two">MIRROR #02</a>')
  archive=Response(b'7z\xbc\xaf\x27\x1cdata')
  with tempfile.TemporaryDirectory() as root,patch.object(web,'fetch',side_effect=[page,OSError('Mirror unavailable'),archive]) as fetch:
   target=web.download('https://dl.gamecopyworld.eu/?f=game!7z',root)
   self.assertEqual(Path(target).name,'game.7z')
   self.assertEqual(fetch.call_count,3)

 def test_trainers_and_other_download_sections_are_hidden(self):
  page = """<a name="Game Fixed Files"></a><a onmousedown="cbox('https://dl.gamecopyworld.eu/?f=fix!7z')"></a>
  <a name="Game +3 TRAINER"></a><a onmousedown="cbox('https://dl.gamecopyworld.eu/?f=innocent-name!rar')"></a>
  <a name="Game Unlocker"></a><a onmousedown="cbox('https://dl.gamecopyworld.eu/?f=unlock!zip')"></a>"""
  with patch.object(web, 'html', return_value=page):
   rows=web.patches(web.BASE+'pc_game.shtml')
  self.assertEqual([row['title'] for row in rows], ['fix.7z'])
