# MinecraftModded packwiz project

Minecraft **1.21.1 / NeoForge**, based on the supplied **134 enabled mod filenames** in `temp-modlist.txt`. The two disabled mods stay excluded. The initial pack pins **NeoForge 21.1.259**. Mod upgrades and full compatibility testing remain pending.

**Status: the pack has been generated and local validation passes for all 134 mods.** `pack.toml`, `index.toml`, and all 134 mod metadata files exist. The user’s online import successfully selected NeoForge 21.1.259 using the Windows HTTPS retry. Next, verify remote downloads and test Minecraft before publishing. Full game compatibility is still untested.

## Files

- `pack.toml`, `index.toml`, `mods/*.pw.toml`: the generated pack, pinned loader, and 134 mod download definitions.
- `sources/mods.json`: all 134 enabled filenames, names, source candidates and client-side settings. Candidate slugs are lookup hints, not proof of a matching release.
- `sources/resolved.json`: verified release IDs, download URLs and checksums; saved as imports progress.
- `sources/unresolved.json`: remaining filenames and the reason each could not be resolved.
- `sources/overrides.json`: explicit verified records for releases the APIs cannot resolve.
- `scripts/import_pack.py`: resumable initial import; never silently substitutes a newer filename.
- `scripts/validate_pack.py`: checks completeness, TOML, paths, client inclusion and the entire hash chain.
- `client/sync-mods.cmd`: completed version of the supplied batch/PowerShell updater.
- `.github/workflows/pages.yml`: manually triggered publishing after validation.
- `pack.toml.in`: reference template, not a consumable pack.

## Validate the generated pack

Use Python 3.11 or newer on a machine with Internet access. No Python packages are needed.

The initial import is complete. Verify every remote mod download:

```powershell
python scripts/validate_pack.py --inventory --downloads
```

Do not rerun initial pack creation in this folder: the importer deliberately refuses to overwrite an existing pack. Use packwiz for subsequent changes. The original creation command was `python scripts/import_pack.py --neoforge latest`.

`latest` reads the live official NeoForge version list, selects the numerically newest stable `21.1.x` release, verifies its release metadata, and pins that exact version in `pack.toml`. It does not upgrade any mods. Create Propulsion’s verified JAR requires NeoForge **21.1.219 or newer**, so older loaders are rejected. This selects a candidate for testing, not a guarantee of compatibility.

The importer reuses all 134 saved records. For Create Propulsion 1.1.2, the [exact CurseForge release](https://www.curseforge.com/minecraft/mc-mods/create-propulsion-simulated/files/8039499) provides a Curse Maven coordinate. If the metadata APIs cannot resolve it, the importer tries that artifact through [Curse Maven](https://www.cursemaven.com/), a third-party service linked by CurseForge. It downloads the JAR into memory, checks the recorded SHA-1 hint, verifies its NeoForge metadata and mod ID/version, and computes SHA-512 from the actual bytes. Only a successful verification creates a record. The resulting pack retains CurseForge project/file IDs for future updates; clients download this one artifact through Curse Maven.

Modrinth lookups need no key. CurseForge's official API requires a key in the `CURSEFORGE_API_KEY` environment variable; never put a key in this repository. Without one, Modrinth matches still resolve and unmatched files are reported. Alternatively add verified records to `sources/overrides.json`, using the shape shown in `sources/resolved.json`. A direct-source record uses `"provider": "direct"`, a public HTTPS URL, an actual file checksum, and verified game/loader metadata. Do not guess a download URL.

The importer checks exact filenames, Minecraft support and loader tags. It saves successful results so you can rerun it after fixing candidates or supplying overrides. It rejects missing public download URLs instead of constructing guessed CDN addresses. If a publisher has renamed the file or removed the release, review that entry explicitly.

If a known working instance uses a specific NeoForge version, pass that exact `21.1.x` value instead of `latest`. The generated `pack.toml` is the source of truth for the loader clients must install.

On Windows, if Python rejects the official NeoForge host’s certificate, the importer automatically retries using the system `curl.exe` with Schannel (Windows certificate validation). Certificate checks remain enabled, redirects stay HTTPS-only, and local curl configuration files are ignored. This can resolve a difference between Python and Windows certificate-chain handling. If Windows also rejects the connection, the importer stops and reports that error; check the system clock, Windows certificate updates, and the server or HTTPS-inspection certificate. The user’s live retry succeeded and generated the pack. Successful retries now print a success message after verification rather than a certificate warning before the request.

The import writes `mods/*.pw.toml`, `index.toml`, then `pack.toml` last. It refuses an existing pack or nonempty mods directory. All 134 enabled mods must resolve before anything consumable is created. Online import confirms that the selected NeoForge release exists; this does not prove the full mod set is compatible. An actual game launch is still needed.

`--offline` uses existing saved records without networking and can create the pack once all records and the selected loader are present. It cannot verify the availability of that loader release.

## Review notes

- The inventory includes Sinytra Connector and Forgified Fabric API. Its LambDynamicLights JAR is treated as a Fabric build through Connector. Preserve those dependencies until the later compatibility pass; no compatibility claim has been made.
- `fabric-api-0.116.11+1.21.1.jar.disabled` and `L_Ender's Cataclysm 1.21.1-3.27.jar.disabled` are excluded.
- The inventory contains both Sophisticated Backpacks and Traveler's Backpack, as well as Accessories and Curios. These are preserved as supplied.
- No config, defaultconfig, shader or resource-pack files were supplied. This project currently describes mods only.
- Metadata checks do not validate every transitive dependency constraint or launch Minecraft. That belongs to the later mod/NeoForge compatibility pass.

## Host the pack

After the import and validation succeed:

1. Push this project, including `pack.toml`, `index.toml`, `mods/` and any pack configs, to your chosen GitHub repository.
2. In repository Settings → Pages, select **GitHub Actions** as the source.
3. Run **Publish packwiz pack** from Actions. Publishing is manual; ordinary pushes do not deploy.
4. Download `sync-mods.cmd` from the published site. The workflow fills in the site's real `pack.toml` URL.

The publishing artifact contains only `pack.toml`, the index and its referenced files, plus the downloadable client script. Source records, tests, caches and scripts are excluded. No GitHub repository or hosting destination has been created in this task.

For another static HTTPS host:

```powershell
python scripts/stage_site.py --base-url https://YOUR-HOST/path
```

Upload the contents of `dist/`. The staging command requires an empty `dist/` directory and refuses an incomplete pack.

## Client use

With the official Minecraft Launcher (started at least once):

1. Download the published `sync-mods.cmd` anywhere (for example Downloads). It installs the pack to `%APPDATA%\.minecraft\modpacks\<pack name>` and puts a copy of itself there. To choose the folder instead, put the script alone in an empty folder (for example `D:\Minecraft\MinecraftModded`); a folder that already contains `packwiz.json` is also used as-is.
2. Close Minecraft and the launcher (including the system tray), then double-click the script.
3. The script installs the pack's NeoForge version (verified against NeoForge's published SHA-256) if missing, creates or updates a launcher profile named after this folder (each folder gets its own profile) whose game directory is this folder, and syncs the mods.
4. Open the launcher, pick the profile with the folder's name and press Play. Run the script again whenever the pack changes; it also moves the profile to a new NeoForge version if the pack changes it.

The profile gets a memory setting based on installed RAM (8 GB with 16 GB or more) on creation; later runs keep any memory/Java arguments the player changed. The script backs up `launcher_profiles.json` as `launcher_profiles.json.bak-packwiz` before writing it, and waits if the launcher is open, because the launcher would overwrite the change.

For other launchers (Prism, CurseForge, ...), create the instance with Minecraft 1.21.1 and the pack's NeoForge version yourself, put the script in the instance's game folder beside `mods/`, and set `PACKWIZ_SYNC_SKIP_LAUNCHER=1` (or just run it; it skips launcher setup when no official launcher is installed).

The first run downloads a portable Java 21 runtime for the updater, which is also used for the NeoForge installer. Keep `packwiz.json` in the folder. The script installs both client and shared mods with `-s client`, and explicitly targets its own folder. It does not change the launcher's Java setting or install Minecraft itself.

Use a clean instance for the first sync. Packwiz manages the files it tracks; old, manually installed JARs with different filenames can remain and cause duplicates. The script does not wipe the mods folder, worlds or launcher settings.

The local source copy still contains `YOUR-USERNAME/YOUR-REPO`. Set `PACKWIZ_SYNC_URL` before sharing it manually, or use the already-configured copy produced by the publishing workflow.

## Maintain the completed pack

Install [packwiz](https://packwiz.infra.link/installation/). Once initial import has produced a real pack:

```powershell
packwiz list
packwiz refresh
python scripts/validate_pack.py
```

For the later upgrade pass, use `packwiz update --all`, select the compatible NeoForge version, test the game, then refresh and validate. The original inventory stays as an audit snapshot; omit `--inventory` validation after intentionally changing mod versions. Keep source metadata filenames stable so the completeness check can identify all originally requested projects.

After adding config files, run `packwiz refresh`. Commit every changed metadata file along with `index.toml` and `pack.toml`; hashes are sensitive to exact file bytes. `.gitattributes` keeps TOML line endings consistent on Windows.

## Local checks

```powershell
python -m unittest discover -s tests -v
python scripts/import_pack.py --offline --resolve-only
```

The second command checks all saved source records without downloading or generating pack files. Client Java downloads and a full Minecraft launch have not been tested here.

Format and installer references: [pack format](https://packwiz.infra.link/reference/pack-format/pack-toml/), [mod metadata](https://packwiz.infra.link/reference/pack-format/mod-toml/), [installer usage](https://packwiz.infra.link/tutorials/installing/packwiz-installer/), [Modrinth API](https://docs.modrinth.com/api/), [CurseForge API](https://docs.curseforge.com/rest-api/).
