# MinecraftModded packwiz project

Minecraft **1.21.1 / NeoForge**, built as an **add-on for the [Craftoria](https://www.curseforge.com/minecraft/modpacks/craftoria) CurseForge modpack**. Players install Craftoria in the CurseForge app, then run `sync-mods.cmd`, which adds our extra mods and config changes to that profile. CurseForge keeps managing Craftoria itself, including the few files whose authors block third-party downloads.

**Status:** the importer, validator, updater and tests are ready (37 tests pass). The pack is built against Craftoria 1.37.0 (NeoForge 21.1.249) with one extra so far: **Create Aeronautics** (plus its dependency Sable). The updater's CurseForge checks were tested against real profiles in Windows PowerShell 5.1. A full sync needs a published pack.

The earlier standalone 134-mod pack is kept in `archive/standalone-134/` (see its README).

## Files

| File | Purpose |
| --- | --- |
| `pack.toml`, `index.toml`, `mods/`, `config/`, … | The generated add-on pack. **Do not edit by hand**: the importer owns these and refuses to overwrite edits |
| `sources/pack.json` | Hand-edited settings: pack name, build number, base modpack, extra mods, files players keep (`preserve`) |
| `sources/overrides.json` | Hand-edited: permitted download sources for extras the APIs cannot provide, keyed by filename |
| `sources/local-overrides/` | Hand-edited: our config changes, copied on top of Craftoria's files (same paths as in the game folder) |
| `sources/lock.json` | Generated: the Craftoria release the pack is built for, its file list, every extra's download record and the hash of every generated file |
| `sources/unresolved.json` | Generated: extras the last import could not resolve |
| `scripts/import_craftoria.py` | Builds the pack from a Craftoria profile plus `sources/` |
| `scripts/import_pack.py` | Shared helpers: exact-file Modrinth/CurseForge/Curse Maven resolution, API cache, NeoForge lookup |
| `scripts/validate_pack.py` | Checks the hash chain, install paths, HTTPS downloads, the base modpack and that the index matches `lock.json`. `--downloads` re-downloads every file |
| `scripts/stage_site.py` | Builds `dist/` for publishing |
| `client/sync-mods.cmd` | The Windows updater players run |
| `.github/workflows/pages.yml` | Manual GitHub Pages publishing |

## Build the pack

Python 3.11+ and no packages. **No API key needed**: install Craftoria in the CurseForge app, then run:

```powershell
python scripts/import_craftoria.py
python scripts/validate_pack.py --downloads
```

The importer looks in `%USERPROFILE%\curseforge\minecraft\Instances` for profiles installed from Craftoria and suggests the newest one:

```
Base modpack profiles found in CurseForge (newest first):

  > 1) Craftoria  (Craftoria-1.37.0.zip, NeoForge 21.1.249)
       C:\Users\...\curseforge\minecraft\Instances\Craftoria

Use Craftoria? [Enter = yes, q = quit]
```

Press Enter to confirm, a number to pick another profile, or q to cancel. `--profile DIR` uses a specific profile folder, and `--yes` takes the suggestion without asking. Use `--instances DIR` if CurseForge's folder was moved. The importer then:

1. Downloads the Craftoria release the profile was installed from (verified by SHA-1, cached in `.cache/export/`). It reads Craftoria's version, NeoForge version, mod list and override files from it, and the file names from the profile.
2. Looks up which Craftoria mods are also on Modrinth (by SHA-1), including jars Craftoria bundles in its overrides, so an extra Craftoria already has is caught whichever site it comes from.
3. Resolves the extra mods and copies `sources/local-overrides/` into the pack. It fails if an extra is a mod Craftoria already has or would replace one of its files, or if a local override would replace a Craftoria mod or resource pack. Config files may be replaced: that is what local overrides are for.
4. Writes the files, then `index.toml`, then `pack.toml` last. The pack version is `<Craftoria version>-<build>` (for example `1.37.0-1`). The description names Craftoria's CurseForge project and file IDs, which the updater checks.

It also prints which mods of the archived 134-mod pack Craftoria lacks: candidates for extras. After changing `sources/`, `python scripts/import_craftoria.py --rebuild` rebuilds from the last import without the profile. It only goes online for new extras.

**Without the CurseForge app**, the CurseForge API works instead. Set a free key from [console.curseforge.com](https://console.curseforge.com) in `CURSEFORGE_API_KEY` (never commit it), then pass `--latest` or `--file-id N`.

### Add an extra mod

Add an entry to `extras` in `sources/pack.json`, then run `--rebuild`:

```json
{ "filename": "exact-file-name-1.0.jar", "name": "Example", "slug": "example", "side": "both", "modrinth": ["example-slug"] }
```

The resolver needs the exact filename. It never picks a newer file. `modrinth`/`curseforge` hold candidate project slugs, and `modrinth_version` pins a version ID. Bump `build` whenever you publish a change that isn't a Craftoria update.

### Change a config

Put the changed file under `sources/local-overrides/` at its game-folder path (for example `sources/local-overrides/config/jei/jei-client.ini`), then run `--rebuild`. Editing `config/` directly is refused on the next build (`--force` discards such edits). If you later drop a local override, packwiz deletes that file from players' profiles. For a Craftoria config, put Craftoria's original in `sources/local-overrides/` instead, or players can repair the profile in CurseForge.

The pack cannot remove Craftoria's mods: CurseForge manages those.

### Craftoria update

Update the Craftoria profile in the CurseForge app, run `python scripts/import_craftoria.py` again, validate, test the game and publish. Players then update Craftoria in CurseForge and run `sync-mods.cmd` again. The updater refuses a profile with an older Craftoria than the pack was built for. With a newer one it warns and continues.

Files matching `preserve` (by default `options.txt`, `servers.dat` and the OptiFine/shader option files) are installed only if a player doesn't have them yet, so a sync never resets their settings.

## Host the pack

1. Commit the generated pack (everything except `.cache/` and `dist/`) and push.
2. In repository Settings → Pages, select **GitHub Actions** as the source.
3. Run **Publish packwiz pack** from Actions. Publishing is manual. With `verify_downloads` on, it downloads every extra first.
4. Download `sync-mods.cmd` from the published site. The workflow fills in the real `pack.toml` URL.

For another static HTTPS host: `python scripts/stage_site.py --base-url https://YOUR-HOST/path`, then upload `dist/`.

`.gitattributes` keeps pack files byte-exact (`-text`), because their hashes are in the index.

## Client use

1. In the CurseForge app, install the modpack **Craftoria** (Browse modpacks → Craftoria → Install) and start it once if you like.
2. Close Minecraft, download the published `sync-mods.cmd` (for example to Downloads) and double-click it. If you have more than one Craftoria profile, it asks:

```
  Which CurseForge profile should get MinecraftModded?
   1)  CurseForge profile 'Craftoria'
        Craftoria-1.37.0.zip  -  C:\Users\...\curseforge\minecraft\Instances\Craftoria
   2)  CurseForge profile 'Craftoria (1)' (update)
        Craftoria-1.37.0.zip  -  C:\Users\...\curseforge\minecraft\Instances\Craftoria (1)
```

3. Open CurseForge, pick the profile and press Play. Give it at least 8 GB of memory (CurseForge settings → Minecraft → Java Settings).

The script lists only profiles installed from the pack's base modpack (read from `pack.toml`), newest first, up to 9 entries. Esc cancels without changes. It puts a copy of itself in the profile folder; running that copy, or any copy inside a CurseForge profile, syncs that profile without asking. If the CurseForge folder was moved, put the script in the profile folder (the profile's menu → Open Folder) and run it there. After updating Craftoria in CurseForge, run the script again: it restores any of the pack's files CurseForge replaced.

The first run downloads a portable Java 21 for the updater. Keep `packwiz.json`. Mods are installed with `-s client`. In a console of at least 120x26 characters, the updater shows the "aurora fjord" scene from [ascii.rest](https://ascii.rest/aurora-fjord/) (MIT, by bas3line), pre-rendered by `client/visuals/render-frames.mjs` (maintainer only, Node 22). Smaller windows or `PACKWIZ_SYNC_PLAIN=1` print plain text. Every run writes `last-run.log`.

The source copy of the script contains `YOUR-USERNAME/YOUR-REPO`. Use the published copy, or set `PACKWIZ_SYNC_URL` first.

## Local checks

```powershell
python -m unittest discover -s tests -v
python scripts/validate_pack.py
```

On Windows, if Python rejects the NeoForge host's certificate, the helpers retry that one host with the system `curl.exe` (Schannel), keeping certificate checks on.

References: [pack format](https://packwiz.infra.link/reference/pack-format/pack-toml/), [mod metadata](https://packwiz.infra.link/reference/pack-format/mod-toml/), [installer](https://packwiz.infra.link/tutorials/installing/packwiz-installer/), [Modrinth API](https://docs.modrinth.com/api/), [CurseForge API](https://docs.curseforge.com/rest-api/).
