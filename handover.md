# MinecraftModded handover

Updated: 2026-10-18 (Europe/Oslo). Earlier handovers are in `archive/standalone-134/HANDOVER.txt` and in git history.

## Current status

The pack is an **add-on for Craftoria** (CurseForge, NeoForge 1.21.1, about 560 files). Players install Craftoria in the CurseForge app; `sync-mods.cmd` adds our extra mods and config changes to that profile. The official Minecraft Launcher is no longer supported, by decision on 2026-10-18: a full pack could not ship the 8 Craftoria files whose authors block third-party downloads (Apothic Nerf and 7 resource packs). CurseForge installs those itself.

| Item | State |
| --- | --- |
| Repository | `github.com/arnold01235/MinecraftModpack`, local `D:\git\MinecraftModded` |
| Standalone 134-mod pack | Archived in `archive/standalone-134/`; last live at commit `f6ce336` |
| Base | Craftoria 1.37.0 (CurseForge project 1039252, file 8874369), NeoForge 21.1.249, imported from the local CurseForge profile without an API key |
| Extras / local overrides | Create Aeronautics 1.3.2 (bundled jar: Aeronautics, Simulated, Offroad) and its dependency Sable 2.0.6 (needs Create 6.0.10+, which Craftoria has); Distant Horizons 3.3.3 and Distant Horizons SeedGen 0.9.1 (needs DH 3.2+). All from Modrinth. No local overrides yet |
| `client/sync-mods.cmd` | CurseForge-only. Profile detection and the version check were tested against the real profiles in Windows PowerShell 5.1. A full run needs a published pack |
| Tests | 37 passing |
| Published pack | The old Pages deployment (if any) is unchanged. Nothing is committed yet |

## Next steps

1. Choose extras and add them to `sources/pack.json`; put config changes in `sources/local-overrides/`. Run `python scripts/import_craftoria.py --rebuild`, then `python scripts/validate_pack.py --downloads`.
2. Test the extras in a copy of the Craftoria profile (CurseForge can duplicate a profile) before publishing.
3. Commit, push, run the Pages workflow. Then test `sync-mods.cmd` from Downloads with (a) one Craftoria profile, (b) two (menu), (c) no Craftoria profile (clear error), (d) a rerun from the copy inside the profile, and (e) after a Craftoria update in CurseForge: check that removed or overwritten pack files come back. If packwiz says "up to date" without restoring them, the updater needs to force a full check.

## Design notes

- The importer owns every file in `index.toml`. `sources/lock.json` records each generated file's hash, and a rebuild refuses if one was edited by hand.
- `pack.toml`'s `description` is `Add-on for <name> <version> (CurseForge modpack <project>, file <file>). ...`. The updater parses the IDs from it on every run, so it always checks against the current pack. CurseForge file IDs increase with each upload: a lower ID in the profile means an older Craftoria (refused), a higher one a newer Craftoria (warning only).
- The updater reads `minecraftinstance.json` (several MB for big modpacks) with .NET's JavaScriptSerializer, because Windows PowerShell's `ConvertFrom-Json` rejects files that size. It only parses files that mention the base project ID.
- Duplicate checks: an extra is refused if Craftoria has the same CurseForge project, the same Modrinth project (found by SHA-1 of Craftoria's files and bundled jars), or a file at the same path. The pack cannot remove Craftoria files (`remove` in `sources/pack.json` is rejected).
- Dropping a local override makes packwiz delete that file from players' profiles. To revert a Craftoria config, ship Craftoria's original as the override.
