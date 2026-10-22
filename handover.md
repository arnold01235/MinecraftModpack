# MinecraftModded handover

Updated: 2026-10-20 (Europe/Oslo). Earlier handovers are in `archive/standalone-134/HANDOVER.txt` and in git history.

## Current status

The pack is an **add-on for All the Mods 10: Aeronautics** (CurseForge, NeoForge 1.21.1, 427 files). Players install ATM10: Aeronautics in the CurseForge app; `sync-mods.cmd` adds our extra mods and config changes to that profile. The official Minecraft Launcher is not supported (decision of 2026-10-18: CurseForge installs the base pack's files whose authors block third-party downloads).

| Item | State |
| --- | --- |
| Repository | `github.com/arnold01235/MinecraftModpack`, local `D:\git\MinecraftModded` |
| Craftoria add-on | Archived in `archive/craftoria-addon/` (Craftoria 1.37.0 with Create Aeronautics, Sable, Distant Horizons, SeedGen); last live at commit `b7ea8ad` |
| Standalone 134-mod pack | Archived in `archive/standalone-134/`; last live at commit `f6ce336` |
| Base | ATM10AERO 0.7.1 (CurseForge project 1644918, file 9022977), NeoForge 21.1.250, imported from the local CurseForge profile without an API key. It already has Create Aeronautics 1.3.2 and Sable 2.0.5 |
| Extras (12) | Distant Horizons 3.3.3, Distant Horizons SeedGen 0.9.1, CC: Tweaked 1.120.2, Advanced Peripherals 0.8.2a, UnlimitedPeripheralWorks 1.9.2, Create: Avionics 0.6.0, CC: Sable 1.3.4, Simulated: ComputerCraft Compat 1.1.2, Create: Teleporters 3.0.1b, Create Nuclear 2.0.0, Create: Power Grid 0.6.2 (all Modrinth) and Create: AeroPortals 1.3.5 (CurseForge only, via Curse Maven with a pinned SHA-1). No local overrides yet. Turtlematic 1.4.10 was dropped on 2026-10-22: on a dedicated-server client, opening the Creative inventory crashes the game (its creative tab looks up registries through the integrated server, which is null there) |
| Tested in game | The extras were installed by hand in a local ATM10A profile. DH + SeedGen launched; the full set of 12 has not had a confirmed clean launch yet |
| Not included | Terralith and Tectonic (being compared with the base terrain), shader packs (extras only install to `mods/`), G.L.A.S.S Remastered (needs Sable 2.0.6; the base pack ships 2.0.5 and the add-on cannot replace base files) |
| `client/sync-mods.cmd` | CurseForge-only. Reads the base project from `pack.toml`. A full run needs a published pack |
| Tests | 37 passing; `validate_pack.py` passes with 12 extras |

## Next steps

1. Choose extras and add them to `sources/pack.json`; put config changes in `sources/local-overrides/`. Run `python scripts/import_craftoria.py --rebuild`, then `python scripts/validate_pack.py --downloads`.
2. Test the extras in a copy of the ATM10: Aeronautics profile (CurseForge can duplicate a profile) before publishing.
3. Commit, push, run the Pages workflow. Then test `sync-mods.cmd` from Downloads with (a) one ATM10: Aeronautics profile, (b) two (menu), (c) no ATM10: Aeronautics profile (clear error), (d) a rerun from the copy inside the profile, and (e) after an ATM10: Aeronautics update in CurseForge: check that removed or overwritten pack files come back. If packwiz says "up to date" without restoring them, the updater needs to force a full check.

## Design notes

- The importer owns every file in `index.toml`. `sources/lock.json` records each generated file's hash, and a rebuild refuses if one was edited by hand.
- `pack.toml`'s `description` is `Add-on for <name> <version> (CurseForge modpack <project>, file <file>). ...`. The updater parses the IDs from it on every run, so it always checks against the current pack. CurseForge file IDs increase with each upload: a lower ID in the profile means an older base pack (refused), a higher one a newer base pack (warning only).
- The updater reads `minecraftinstance.json` (several MB for big modpacks) with .NET's JavaScriptSerializer, because Windows PowerShell's `ConvertFrom-Json` rejects files that size. It only parses files that mention the base project ID.
- Duplicate checks: an extra is refused if the base pack has the same CurseForge project, the same Modrinth project (found by SHA-1 of the base pack's files and bundled jars), or a file at the same path. The pack cannot remove base pack files (`remove` in `sources/pack.json` is rejected).
- Dropping a local override makes packwiz delete that file from players' profiles. To revert a base pack config, ship the base pack's original as the override.
