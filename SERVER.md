# Kinetic server operations

Last verified: **2026-10-22 (Europe/Oslo)**.

## Installed configuration

| Item | Installed / observed |
| --- | --- |
| Host | Kinetic Hosting, Germany |
| Base pack | All the Mods 10: Aeronautics **0.7.1** |
| Custom add-on | MinecraftModded **0.7.1-1** |
| Minecraft / loader | **1.21.1 / NeoForge 21.1.250** |
| Runtime | Eclipse Adoptium OpenJDK **21.0.12.1**, Linux amd64 |
| Mod files | **395 base jars + 13 extra jars = 408 jars**; bundled dependencies are additional loaded mods |
| World directory | `World/` (case-sensitive on the server) |
| Game port observed in log | `25568`; use the public Minecraft address shown in Kinetic Panel |
| Access | Kinetic Panel for lifecycle/startup settings; SFTP on port **2022** for files |

The server was fresh. The user installed the base pack through Kinetic's Modpack Installer, which also configured the NeoForge launcher. We uploaded the 13 extra jars to `mods/` through SFTP. There were no filename collisions and no custom config overrides to deploy.

The authoritative extra versions are in `sources/pack.json`, `sources/lock.json`, and `mods/*.pw.toml`. The `.pw.toml` files describe downloads; they are **not** Minecraft mod jars. Do not upload those descriptors as mods.

## What was verified

- All 395 installed base jar filenames matched the pinned 0.7.1 client manifest. This was a filename comparison, not a checksum audit of the entire base installation. The server installer omits some files present in the client pack; do not copy the whole client `mods/` directory onto the server.
- All 13 extras were staged from the local CurseForge profile and checked against their pinned download hashes. After upload, each jar was downloaded again and its SHA-256 matched the staged file.
- The startup log detected all 13 extra jars and reported `Done (10.610s)!`. ModernFix reported **55.834 seconds** for the full dedicated-server load; the `Done` timer covers a shorter startup phase.
- A follow-up log read showed no additional lines, crash, or shutdown at that time. This was a startup check, not a sustained load test.
- Java 21 and NeoForge 21.1.250 were confirmed from the running server's log.

**Still unverified:** a player joining with the custom client, gameplay compatibility of the extras, and performance with 4–10 players. The server started successfully, but its log was not error-free.

## Known startup issues

These did not prevent the observed startup. Their gameplay impact still needs checking; do not assume every warning is harmless.

| Log finding | Follow-up |
| --- | --- |
| Create: Power Grid 0.6.2 could not load `powergridNative7`; accelerated solver unavailable | Check the mod's supported Linux native backend and test electrical networks before relying on large builds |
| KubeJS could not parse several Create Nuclear smithing recipes, including anti-radiation armor variants with an empty template ingredient | Check those recipes in game; investigate compatibility before changing pinned versions or recipes |
| Sable rejected a physics block-properties entry with missing `properties` and `selector` keys | Identify the supplying data file before changing it; test affected physics behavior |
| Missing loot-table items, data-map references and an Excessive Utilities tag; invalid `multipiston:multipistonblock` item | Review relevant gameplay features if affected; these occurred among the base pack's data-loading messages |
| Jupiter config errors, Curios example slot error, In Control `areas.json` write error, and client-class mixin errors | Recheck after a normal restart; investigate persistent or gameplay-relevant failures |

No mod upgrades, removals, or speculative fixes were applied after these findings.

## Resume next time

1. Start the existing server from Kinetic Panel. Do **not** reinstall the pack just to resume.
2. Wait for the console to report `Done`, then review `logs/latest.log` for new failures.
3. Launch the client with ATM10: Aeronautics **0.7.1** and the same **13 pinned extras**. The stock base pack alone does not match this server.
4. Join using the **Minecraft connection address in the panel**, not the SFTP URL. Confirm login, movement, chunk loading, and a normal disconnect/reconnect.
5. Test the extra mods, especially the logged Power Grid and Create Nuclear issues, then evaluate performance with the group before tuning settings.

The client updater still needs a published pack URL for a complete distribution test. The local profile already had the extras installed manually; that does not prove the published updater workflow works end to end.

## Stop, back up, and update

- Use **Stop** in Kinetic Panel and wait until the console finishes saving and the panel shows the server offline. Avoid **Kill** for normal shutdown.
- Before updates, take a backup with the server stopped. Prefer a full-server backup, including `World/`, `config/`, `defaultconfigs/`, `kubejs/`, `mods/`, `server.properties`, and player/access-list files. Keep an independently downloadable copy and verify that the backup completed.
- SFTP only transfers files; it does not stop/start Minecraft or set the panel's Java/startup configuration.
- For an extra-mod update, update the source settings, rebuild and validate the add-on, and test a matching client/server combination. With the server stopped and backed up, replace superseded jars rather than leaving two versions of the same mod installed. Keep clients on the same versions.
- For a base-pack update, plan the client and server migration together. A panel reinstall may replace files; review its behavior and preserve backups first. Do not overwrite a live world with a fresh pack installation.

The user planned to stop the server at the end of this session. **Shutdown has not been independently verified.**

## Access and local evidence

Get current connection details from Kinetic Panel. No password or other secret belongs in this repository, chat, command arguments, or logs. The user explicitly requires entering the password directly into a local masked input.

During setup, a local Python SFTP helper accepted the password in a masked dialog. It was not serialized or printed. Host-key verification used a local `known_hosts` file. The helper and temporary Paramiko installation are session tooling under ignored `.cache/sftp/`, not a maintained repository deployment tool. A future session may need fresh local authentication; never paste a password into chat to resume.

Local evidence is under ignored `.cache/server-staging/` and is not available from a fresh clone:

- `extras-inventory.json`: staged extra filenames.
- `upload-verification.json`: SHA-256 checksums verified by downloading the uploaded jars.
- `runtime/latest.log` and `runtime/latest-followup.log`: startup log snapshots, before shutdown.
- `inspection/`: installer metadata and the pre-start log.

## Provider instructions

- [Kinetic modpack installer](https://www.kinetichosting.com/articles/minecraft/basics/how-to-install-a-modpack-on-a-minecraft-server)
- [Kinetic SFTP guide](https://www.kinetichosting.com/articles/kinetic-panel/basics/how-to-connect-and-use-sftp)
- [Kinetic server mod installation](https://www.kinetichosting.com/articles/minecraft/modded/how-to-install-minecraft-server-mods)
