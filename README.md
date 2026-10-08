# GameCopyWorld for Playlite

Use **Crack Tools → GameCopyWorld → Install from downloaded archive…**.
The wizard opens GameCopyWorld search using the selected game's name. Download
an archive in your browser, choose it from Downloads, and review its files.
Select the archive folder whose contents belong in the game installation root,
then check the files to install. Programs from the archive are never executed.

ZIP works with Python; RAR and 7z require `7zz` or `7z` on the host. Passworded
archives, links, unsafe paths, duplicate paths, archives over 2 GiB unpacked or
5000 files are rejected. Archive compatibility with your game version is a user
choice; the preview shows each destination and whether it replaces a file.

Requires Crack Tools 0.1.0 for shared progress, backup and restoration code. GameCopyWorld works independently of SteamAutoCrack and Steam Downloader.
No VM or VPN is needed for archive installation. Existing destination files are
verified and saved in the game's `.playlite-steamautocrack/` folder. New files
and directories are tracked. Failure/cancellation restores the pre-run files.
Use **Restore originals…** to undo installation; changed files are preserved in
`recovery/`. A previous operation is restored automatically before installing another archive.

Build: `python3 tools/build_release.py`. Install `dist/plugin.zip` in Playlite
and restart. Tests: `python3 -m unittest discover -s tests -q`.

## In-window catalogue and downloads

The wizard searches GameCopyWorld's static game index with the game name,
ignoring punctuation, and displays matching games and their download entries.
Choose a matching game/version and download. Direct archive responses and
simple archive links on GameCopyWorld mirrors are saved in Downloads and passed
to the preview automatically. Pages requiring browser interaction or unavailable
mirrors open in the browser; the Downloads file picker remains available.
Only fixed-file and fixed-executable sections are listed; trainers and unlockers are hidden.
