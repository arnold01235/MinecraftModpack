# MinecraftModded handover

Updated: 2026-10-15 (Europe/Oslo). This is the current handover; `HANDOVER.txt` is an earlier snapshot.

## Current status

The pack is built and all **134 mod downloads passed checksum verification**. The user ran `python scripts/validate_pack.py --inventory --downloads` successfully (exit code 0, about 128 seconds). This verifies the files and exact inventory; it does not prove that Minecraft launches or that every mod is compatible.

| Item | State |
| --- | --- |
| Source workspace | `D:\git\MinecraftModded` |
| Minecraft | **1.21.1** |
| NeoForge | **21.1.259**, pinned in `pack.toml` |
| Java | **21** |
| Enabled mods | **134**, original versions preserved |
| Generated files | `pack.toml`, `index.toml`, 134 `mods/*.pw.toml` files |
| Source resolution | Complete; `sources/unresolved.json` is empty |
| Tooling tests | **34 passing** at the last run |
| Remote downloads | All 134 verified successfully in the user’s terminal |
| Actual game launch / world loading | Not tested yet |
| Full client updater synchronization | Not tested yet |
| GitHub repository / Pages | Not created or published in this task |

No mod upgrades have been performed. No config files, default configs, shaders, or resource packs were supplied. The source updater still contains its hosting URL placeholder.

## Start the pack with the official Minecraft Launcher

The user selected the official launcher as the setup example. These steps have been provided but have **not** been carried out or verified on a playable instance yet.

Use two separate folders:

- Pack source: `D:\git\MinecraftModded`.
- Suggested game instance: `D:\Minecraft\MinecraftModded`.

### 1. Install Java and NeoForge

Install Java 21 for running the NeoForge installer and the packwiz bootstrap. Check the Java available in PowerShell:

```powershell
java -version
```

The reported major version should be 21. If Java is missing, follow the [NeoForge Java setup guide](https://docs.neoforged.net/user/docs/).

Close Minecraft and its launcher. Download the **NeoForge 21.1.259** installer JAR from the [NeoForged website](https://neoforged.net/), run it, and choose **Install client**. Select this exact version, rather than whichever release the website initially displays.

### 2. Create the launcher installation

Open **Minecraft Launcher → Java Edition → Installations → New installation** and set:

| Setting | Value |
| --- | --- |
| Name | `MinecraftModded` |
| Version | The installed NeoForge **21.1.259** profile for Minecraft **1.21.1** |
| Game Directory | `D:\Minecraft\MinecraftModded` |

Save it, launch the installation once, and then close Minecraft. Ensure the game uses Java 21. Keep this instance separate from the source repository and other Minecraft instances.

See the [official NeoForge client installation instructions](https://docs.neoforged.net/user/docs/client/).

### 3. Serve the pack locally for the first test

GitHub hosting is not required for this local test. Open a PowerShell window and run:

```powershell
cd D:\git\MinecraftModded
python -m http.server 8080 --bind 127.0.0.1
```

Leave that window open. The pack is served at `http://127.0.0.1:8080/pack.toml`, accessible only on this computer.

### 4. Install the mods into the game instance

Download [packwiz-installer-bootstrap.jar](https://github.com/packwiz/packwiz-installer-bootstrap/releases/download/v0.0.3/packwiz-installer-bootstrap.jar) into:

```text
D:\Minecraft\MinecraftModded
```

With Minecraft closed, open a **second** PowerShell window and run:

```powershell
cd D:\Minecraft\MinecraftModded
java -jar packwiz-installer-bootstrap.jar -g -s client http://127.0.0.1:8080/pack.toml
```

Run this command from the game instance folder exactly as shown. It installs client and shared mods there and creates `packwiz.json` to track managed files. Keep that tracking file.

This invokes the packwiz bootstrap directly. The production `sync-mods.cmd` requires a public HTTPS URL and is not used for this localhost test. Local HTTP serving is supported by [packwiz’s installer instructions](https://packwiz.infra.link/tutorials/installing/packwiz-installer/).

### 5. Launch and check the game

After installation finishes successfully, select **MinecraftModded** in the official launcher and click **Play**. Check that the main menu loads and that a new test world can be created and loaded.

You can stop the local HTTP server with **Ctrl+C** after the mod installation finishes. The game does not need that server running.

If Minecraft fails, inspect the instance’s `logs/latest.log`, `logs/debug.log` if present, and `crash-reports/`. The current pack has passed download verification, but its dependency and runtime compatibility still need this launch test.

## Publishing and client updates

After the launch test, obtain the user’s intended GitHub repository or other public HTTPS hosting URL. The local folder currently has no `.git` repository or configured remote.

For GitHub Pages:

1. Create the intended public repository and push the project, including `pack.toml`, `index.toml`, `mods/`, source tooling, and the workflow.
2. In repository **Settings → Pages**, select **GitHub Actions** as the publishing source.
3. Manually run **Publish packwiz pack** from the Actions tab. Ordinary pushes do not deploy automatically.
4. Download the generated `sync-mods.cmd` from the published site. The workflow fills in its real `pack.toml` URL.
5. Put that script in each game instance folder beside `mods/`. Close Minecraft, run the script, then launch the matching NeoForge profile.

For another static HTTPS host:

```powershell
python scripts/stage_site.py --base-url https://YOUR-HOST/path
```

Replace the example URL with the real site root. The staging command requires an empty `dist/` and copies only the indexed pack files plus the configured client script. Upload the contents of `dist/`.

The client script downloads portable Java 21 for the updater, uses an instance lock, and preserves `packwiz.json`. It does not install Minecraft or NeoForge, change launcher Java settings, or remove unrelated manually installed mods. Use a clean instance for the first synchronization.

## Certificate issue: recovered successfully

Python initially failed to read NeoForge metadata with `CERTIFICATE_VERIFY_FAILED: certificate has expired`. The importer now retries certificate-verification failures for `maven.neoforged.net` through Windows’ system `curl.exe`, requiring its Schannel backend.

Certificate and revocation checks remain enabled. Transfers and redirects are HTTPS-only, curl configuration files are disabled, and no trust stores were changed. Other hosts and network-denied failures do not use this retry.

The user’s live retry succeeded, selected NeoForge **21.1.259**, and created the pack with exit code 0. The earlier warning appeared alongside successful output and caused confusion. Logging now prints this only after a successful native request:

```text
NeoForge metadata verified successfully using Windows HTTPS.
```

The difference between Python and Windows certificate-chain handling has not been fully diagnosed, but the working retry and full mod-download validation are confirmed. **Do not rerun the initial importer to fix this:** it deliberately refuses to overwrite the existing pack.

## Files and maintenance

| File or folder | Purpose |
| --- | --- |
| `pack.toml` | Pack metadata, pinned Minecraft/NeoForge versions, index checksum |
| `index.toml`, `mods/*.pw.toml` | Index and exact mod download definitions |
| `temp-modlist.txt` | Original inventory; preserve as an audit snapshot |
| `sources/mods.json` | Source mappings, loader hints, sides, known minimum loader |
| `sources/resolved.json` | All 134 resolved records; preserve them |
| `sources/unresolved.json` | Empty after successful resolution |
| `sources/overrides.json` | Optional verified overrides |
| `scripts/import_pack.py` | Resumable, exact-filename initial import; Python 3.11+ |
| `scripts/validate_pack.py` | Pack integrity, exact inventory, optional remote binary checks |
| `scripts/stage_site.py` | Static-host artifact and client URL configuration |
| `client/sync-mods.cmd` | Windows client updater |
| `.github/workflows/pages.yml` | Manual Pages build and deployment |
| `.packwizignore`, `.gitignore` | Exclude source documents/tools from installation and caches/JARs from Git |
| `tests/test_pack.py` | 34 passing tooling tests |
| `README.md` | General setup and maintenance guide |

The project’s `mods/` contains packwiz metadata, not an installed game’s JAR files. The download validator streams and checks binaries without installing or retaining them as a playable instance.

Use packwiz for changes after initial creation:

```powershell
packwiz refresh
python scripts/validate_pack.py
```

Commit changed metadata, `index.toml`, and `pack.toml` together. Keep TOML line endings consistent. After intentionally upgrading mod filenames, omit `--inventory`; it compares against the original inventory.

The user wants a later pass to update mods and find the newest compatible loader. That work is still pending. Keep source metadata paths stable because completeness validation expects the original catalog’s project paths.

## Source and compatibility details

- 133 mods use Modrinth records. Create Propulsion: Simulated 1.1.2 uses CurseForge project **1522736**, file **8039499**, downloaded through the Curse Maven coordinate supplied by its release page.
- The Create Propulsion fallback verified the actual JAR’s checksum, mod ID, version, and NeoForge metadata before saving the record. The subsequent full download-validation run also passed for this file.
- Corrected source identities include Camera Mod, Cave Dweller ReEvolved, Moog’s Structure Lib, and Create Propulsion: Simulated. The exact mappings are saved; source discovery does not need to be repeated.
- Create Propulsion’s internal metadata requires NeoForge **21.1.219+**, Minecraft **1.21.1**, Create **6.0.6+**, Sable, and `sablecompanion`. Check bundled components before adding dependencies. This lower bound is not a full dependency audit of all mods.
- Sinytra Connector and Forgified Fabric API are present. LambDynamicLights is a Fabric build intended to run through Connector. Verify this combination at runtime.
- Both Sophisticated Backpacks and Traveler’s Backpack, and both Accessories and Curios, are preserved from the original list.
- The disabled `fabric-api-0.116.11+1.21.1.jar.disabled` and `L_Ender's Cataclysm 1.21.1-3.27.jar.disabled` remain excluded.

## Local launch setup (2026-10-15 session)

- Installed for the user: NeoForge 21.1.259 in `%APPDATA%\.minecraft`, and the 134 mods in `D:\Minecraft\MinecraftModded` (packwiz bootstrap from a local server). Python's `http.server` refuses packwiz's parallel connections on Windows (listen backlog 5); serve with a `ThreadingHTTPServer` subclass using a larger `request_queue_size`.
- `sablecompanion` (required by Create Propulsion) is provided inside the Sable and Create Propulsion JARs.
- The launcher overwrites `launcher_profiles.json` on exit; edits must happen while it is fully closed.
- `client/sync-mods.cmd` now installs the pack's NeoForge version and creates/updates a launcher profile named after its folder (key `packwiz-<hash of folder path>`) pointing to that folder. Run from a non-empty folder (Downloads), it installs to `%APPDATA%.minecraftmodpacks<pack>`. Tested end-to-end in a sandbox APPDATA on D: (fresh install + rerun from the copied script). Note: the user's C: drive is almost full. Its functions were tested against a sandbox `.minecraft`; the full script has not run end-to-end because it requires a public HTTPS pack URL.

- The updater has an animated console UI (ascii.rest snow train, MIT; frames pre-rendered to `client/visuals/snow-train.frames.gz`, published as `installer/snow-train.frames.gz`) with boot-log status lines and a plain-text fallback. It exits 0 (done) or 2 (handled failure); the `.cmd` pauses only for other codes. `PACKWIZ_SYNC_NO_PAUSE=1` skips the final key press (used for automated tests). Verified: full fresh install in a hidden 120x30 conhost (UI mode, exit 0, 152 s) and plain-mode reruns.

## Notes for the next agent

Agent-side networking previously failed with WinError 10013 / EACCES, while user-shell commands successfully resolved, generated, and verified the pack. Do not confuse those environment restrictions with the recovered Python certificate error.

The standard command tool previously failed during process setup. The available Node REPL tool worked for local filesystem access and `child_process` calls. Python 3.13 was available. The writable project root is `D:\git\MinecraftModded`.

No GitHub credentials or hosting destination have been supplied. The next useful work is installing the local test instance as described above, confirming game startup, then publishing and testing the shared updater.
