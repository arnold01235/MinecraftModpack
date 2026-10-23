# MinecraftModded packwiz project

Minecraft **1.21.1 / NeoForge**, built as an **add-on for the [All the Mods 10: Aeronautics](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10-aeronautics) CurseForge modpack**. Players install ATM10: Aeronautics in the CurseForge app, then run `sync-mods.cmd`, which adds our extra mods and config changes to that profile. CurseForge keeps managing ATM10: Aeronautics itself, including the few files whose authors block third-party downloads.

**Status:** the importer, validator, updater and tests are ready (37 tests pass). The pack is built against ATM10: Aeronautics 0.7.1 (NeoForge 21.1.250) with 18 extras: **Distant Horizons** and **Distant Horizons SeedGen**; **CC: Tweaked**, **Advanced Peripherals** and **UnlimitedPeripheralWorks**; the Aeronautics/ComputerCraft add-ons **Create: Avionics**, **CC: Sable**, **Simulated: ComputerCraft Compat** and **CC:C Bridge**; and **Create: AeroPortals**, **Create: Teleporters**, **Create Nuclear**, **Create: Power Grid** and **Create: Copycats+**; **Simple Voice Chat** for proximity voice chat; **ProjectE** (EMC transmutation, the modern Equivalent Exchange); and **Exposure** (film cameras and photographs; its Interplanar Projector turns a local image file or URL into a photo). Players also get the client-only **Euphoria Patches**, an add-on for Complementary Shaders. A full sync needs a published pack.

**Server:** ATM10: Aeronautics 0.7.1 plus all 13 extras is installed on Kinetic Hosting; Turtlematic has since been dropped from the pack and still has to be removed from the server. Uploaded extras passed checksum verification and the dedicated server completed startup on 2026-10-22 (Europe/Oslo). A player join and group performance are still untested; the startup log contains nonfatal mod/data errors. See [server operations and known issues](SERVER.md) and the [handover](handover.md).

Earlier versions are archived: the Craftoria add-on in `archive/craftoria-addon/` and the standalone 134-mod pack in `archive/standalone-134/` (see their READMEs).

## Files

| File | Purpose |
| --- | --- |
| `pack.toml`, `index.toml`, `mods/`, `config/`, … | The generated add-on pack. **Do not edit by hand**: the importer owns these and refuses to overwrite edits |
| `sources/pack.json` | Hand-edited settings: pack name, build number, base modpack, extra mods, files players keep (`preserve`) |
| `sources/overrides.json` | Hand-edited: permitted download sources for extras the APIs cannot provide, keyed by filename |
| `sources/local-overrides/` | Hand-edited: our config changes, copied on top of ATM10: Aeronautics' files (same paths as in the game folder) |
| `sources/lock.json` | Generated: the ATM10: Aeronautics release the pack is built for, its file list, every extra's download record and the hash of every generated file |
| `sources/unresolved.json` | Generated: extras the last import could not resolve |
| `scripts/import_craftoria.py` | Builds the pack from an ATM10: Aeronautics profile plus `sources/` |
| `scripts/import_pack.py` | Shared helpers: exact-file Modrinth/CurseForge/Curse Maven resolution, API cache, NeoForge lookup |
| `scripts/validate_pack.py` | Checks the hash chain, install paths, HTTPS downloads, the base modpack and that the index matches `lock.json`. `--downloads` re-downloads every file |
| `scripts/stage_site.py` | Builds `dist/` for publishing, including a landing page (`index.html`) with the install steps and the extras |
| `client/sync-mods.cmd` | The Windows updater players run |
| `.github/workflows/pages.yml` | Manual GitHub Pages publishing |
| `SERVER.md` | Kinetic server setup, verified state, known issues, backups, and restart/update steps |

## Build the pack

Python 3.11+ and no packages. **No API key needed**: install ATM10: Aeronautics in the CurseForge app, then run:

```powershell
python scripts/import_craftoria.py
python scripts/validate_pack.py --downloads
```

The importer looks in `%USERPROFILE%\curseforge\minecraft\Instances` for profiles installed from ATM10: Aeronautics and suggests the newest one:

```
Base modpack profiles found in CurseForge (newest first):

  > 1) ATM10 Aeronautics  (ATM10AERO-0.7.1.zip, NeoForge 21.1.250)
       C:\Users\...\curseforge\minecraft\Instances\ATM10 Aeronautics

Use ATM10 Aeronautics? [Enter = yes, q = quit]
```

Press Enter to confirm, a number to pick another profile, or q to cancel. `--profile DIR` uses a specific profile folder, and `--yes` takes the suggestion without asking. Use `--instances DIR` if CurseForge's folder was moved. The importer then:

1. Downloads the ATM10: Aeronautics release the profile was installed from (verified by SHA-1, cached in `.cache/export/`). It reads ATM10: Aeronautics' version, NeoForge version, mod list and override files from it, and the file names from the profile.
2. Looks up which ATM10: Aeronautics mods are also on Modrinth (by SHA-1), including jars ATM10: Aeronautics bundles in its overrides, so an extra that ATM10: Aeronautics already has is caught whichever site it comes from.
3. Resolves the extra mods and copies `sources/local-overrides/` into the pack. It fails if an extra is a mod ATM10: Aeronautics already has or would replace one of its files, or if a local override would replace an ATM10: Aeronautics mod or resource pack. Config files may be replaced: that is what local overrides are for.
4. Writes the files, then `index.toml`, then `pack.toml` last. The pack version is `<ATM10: Aeronautics version>-<build>` (for example `0.7.1-1`). The description names ATM10: Aeronautics' CurseForge project and file IDs, which the updater checks.

It also prints which mods of the archived 134-mod pack ATM10: Aeronautics lacks: candidates for extras. After changing `sources/`, `python scripts/import_craftoria.py --rebuild` rebuilds from the last import without the profile. It only goes online for new extras.

**Without the CurseForge app**, the CurseForge API works instead. Set a free key from [console.curseforge.com](https://console.curseforge.com) in `CURSEFORGE_API_KEY` (never commit it), then pass `--latest` or `--file-id N`.

### Add an extra mod

Add an entry to `extras` in `sources/pack.json`, then run `--rebuild`:

```json
{ "filename": "exact-file-name-1.0.jar", "name": "Example", "slug": "example", "side": "both", "modrinth": ["example-slug"] }
```

The resolver needs the exact filename. It never picks a newer file. `modrinth`/`curseforge` hold candidate project slugs, and `modrinth_version` pins a version ID. Bump `build` whenever you publish a change that isn't an ATM10: Aeronautics update.

### Change a config

Put the changed file under `sources/local-overrides/` at its game-folder path (for example `sources/local-overrides/config/jei/jei-client.ini`), then run `--rebuild`. Editing `config/` directly is refused on the next build (`--force` discards such edits). If you later drop a local override, packwiz deletes that file from players' profiles. For an ATM10: Aeronautics config, put ATM10: Aeronautics' original in `sources/local-overrides/` instead, or players can repair the profile in CurseForge.

The pack cannot remove ATM10: Aeronautics' mods: CurseForge manages those.

### ATM10: Aeronautics update

Update the ATM10: Aeronautics profile in the CurseForge app, run `python scripts/import_craftoria.py` again, validate, test the game and publish. Players then update ATM10: Aeronautics in CurseForge and run `sync-mods.cmd` again. The updater refuses a profile with an older ATM10: Aeronautics than the pack was built for. With a newer one it warns and continues.

Files matching `preserve` (by default `options.txt`, `servers.dat` and the OptiFine/shader option files) are installed only if a player doesn't have them yet, so a sync never resets their settings.

## Host the pack

1. Commit the generated pack (everything except `.cache/` and `dist/`) and push.
2. In repository Settings → Pages, select **GitHub Actions** as the source.
3. Run **Publish packwiz pack** from Actions. Publishing is manual. With `verify_downloads` on, it downloads every extra first.
4. Download `sync-mods.cmd` from the published site. The workflow fills in the real `pack.toml` URL.

For another static HTTPS host: `python scripts/stage_site.py --base-url https://YOUR-HOST/path`, then upload `dist/`.

`.gitattributes` keeps pack files byte-exact (`-text`), because their hashes are in the index.

## Client use

1. In the CurseForge app, install the modpack **ATM10: Aeronautics** (Browse modpacks → ATM10: Aeronautics → Install) and start it once if you like.
2. Close Minecraft, download the published `sync-mods.cmd` (for example to Downloads) and double-click it. If you have more than one ATM10: Aeronautics profile, it asks:

```
  Which CurseForge profile should get MinecraftModded?
   1)  CurseForge profile 'ATM10 Aeronautics'
        ATM10AERO-0.7.1.zip  -  C:\Users\...\curseforge\minecraft\Instances\ATM10 Aeronautics
   2)  CurseForge profile 'ATM10 Aeronautics (1)' (update)
        ATM10AERO-0.7.1.zip  -  C:\Users\...\curseforge\minecraft\Instances\ATM10 Aeronautics (1)
```

3. Open CurseForge, pick the profile and press Play. Give it at least 8 GB of memory (CurseForge settings → Minecraft → Java Settings).

The script lists only profiles installed from the pack's base modpack (read from `pack.toml`), newest first, up to 9 entries. Esc cancels without changes. It puts a copy of itself in the profile folder; running that copy, or any copy inside a CurseForge profile, syncs that profile without asking. If the CurseForge folder was moved, put the script in the profile folder (the profile's menu → Open Folder) and run it there. After updating ATM10: Aeronautics in CurseForge, run the script again: it restores any of the pack's files CurseForge replaced.

The first run downloads a portable Java 21 for the updater. Keep `packwiz.json`. Mods are installed with `-s client`. In a console of at least 120x26 characters, the updater shows the "aurora fjord" scene from [ascii.rest](https://ascii.rest/aurora-fjord/) (MIT, by bas3line), pre-rendered by `client/visuals/render-frames.mjs` (maintainer only, Node 22). Smaller windows or `PACKWIZ_SYNC_PLAIN=1` print plain text. Every run writes `last-run.log`.

The source copy of the script points at the `atm10-aeronautics-base` branch on GitHub (for testing before publishing). Publishing replaces that URL with the site's.

## Local checks

```powershell
python -m unittest discover -s tests -v
python scripts/validate_pack.py
```

On Windows, if Python rejects the NeoForge host's certificate, the helpers retry that one host with the system `curl.exe` (Schannel), keeping certificate checks on.

References: [pack format](https://packwiz.infra.link/reference/pack-format/pack-toml/), [mod metadata](https://packwiz.infra.link/reference/pack-format/mod-toml/), [installer](https://packwiz.infra.link/tutorials/installing/packwiz-installer/), [Modrinth API](https://docs.modrinth.com/api/), [CurseForge API](https://docs.curseforge.com/rest-api/).
