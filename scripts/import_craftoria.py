#!/usr/bin/env python3
"""Build the add-on pack that players sync on top of Craftoria (a CurseForge modpack).

    python scripts/import_craftoria.py                  find Craftoria in the CurseForge app and confirm it
    python scripts/import_craftoria.py --profile DIR    use this CurseForge profile folder
    python scripts/import_craftoria.py --rebuild        rebuild from the last import (after editing sources/)

Players install Craftoria itself in the CurseForge app, which also fetches the files whose authors
block third-party downloads. The pack holds only what we add on top: the extra mods in
sources/pack.json and the config changes in sources/local-overrides/. The importer reads Craftoria's
version, NeoForge version and file list (to catch extras Craftoria already has) from a CurseForge
profile, so no API key is needed. Without the app, a CurseForge API key (CURSEFORGE_API_KEY, free at
https://console.curseforge.com) works with --latest or --file-id.
The importer owns every file in index.toml and refuses to overwrite one that was edited by hand.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib
from zipfile import BadZipFile, ZipFile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from import_pack import (CF, MR, ROOT, USER_AGENT, API, ResolutionError, atomic_write, atomic_write_bytes, digest,
                         https_url, metadata, read_json, resolve_mod, select_neoforge, validate_extras, write_json)
from validate_pack import check_install_path, inside

MODPACK_CLASS = 4471
# CurseForge project classes a modpack lists, and the folder each installs to.
CLASS_FOLDERS = {6: "mods", 12: "resourcepacks", 6552: "shaderpacks"}
EXPORT_LIMIT = 2 * 1024 * 1024 * 1024
DEFAULT_SETTINGS = {
    "name": "MinecraftModded", "minecraft": "1.21.1", "build": 1,
    "base": {"curseforge_slug": "craftoria", "curseforge_project_id": None},
    "preserve": ["options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat"],
    "extras": [],
}


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60] or "file"


def load_settings(root):
    settings = dict(DEFAULT_SETTINGS, **read_json(root / "sources/pack.json", {}))
    if not re.fullmatch(r"[\w.()+-][\w .()+-]{0,63}", settings["name"]) or settings["name"].endswith("."):
        raise ResolutionError("sources/pack.json: invalid pack name")
    if settings["minecraft"] != "1.21.1":
        raise ResolutionError("sources/pack.json: this pack targets Minecraft 1.21.1")
    if not isinstance(settings["build"], int) or settings["build"] < 1:
        raise ResolutionError("sources/pack.json: build must be a positive number")
    if settings.get("remove"):
        raise ResolutionError("sources/pack.json: 'remove' is not supported. The pack is installed on top of the "
                              "base modpack, which CurseForge manages, so it cannot remove the base pack's files.")
    validate_extras(settings["extras"])
    return settings


# --- The CurseForge export -------------------------------------------------------

def read_export(path, minecraft):
    """Return the export's manifest and its override files as {install path: SHA-1 for jars in mods/, else None}."""
    try:
        with ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("manifestType") != "minecraftModpack":
                raise ResolutionError("Not a CurseForge modpack export (manifest.json)")
            if manifest.get("minecraft", {}).get("version") != minecraft:
                raise ResolutionError(f"The export is not for Minecraft {minecraft}")
            prefix = str(manifest.get("overrides") or "overrides").strip("/") + "/"
            files = {}
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or not name.startswith(prefix):
                    continue
                relative = name[len(prefix):]
                jar = relative.startswith("mods/") and relative.endswith(".jar")
                files[relative] = hashlib.sha1(archive.read(info)).hexdigest() if jar else None
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ResolutionError(f"Cannot read the export {path}: {exc}") from exc
    if not re.fullmatch(r"[\w.+-]{1,40}", str(manifest.get("version", ""))):
        raise ResolutionError("The export has no usable version number")
    loaders = [l.get("id", "") for l in manifest.get("minecraft", {}).get("modLoaders", [])]
    neoforge = [l.removeprefix("neoforge-") for l in loaders if l.startswith("neoforge-")]
    if len(neoforge) != 1:
        raise ResolutionError(f"The export must use exactly one NeoForge loader, found {loaders}")
    manifest["neoforge"] = neoforge[0]
    return manifest, files


def find_base_project(api, settings):
    base = settings["base"]
    if base.get("curseforge_project_id"):
        return api.get(f"{CF}/mods/{int(base['curseforge_project_id'])}", curseforge=True)["data"]
    query = urlencode({"gameId": 432, "classId": MODPACK_CLASS, "slug": base["curseforge_slug"]})
    hits = api.get(f"{CF}/mods/search?{query}", curseforge=True, fresh=True)["data"]
    if len(hits) != 1:
        raise ResolutionError(f"CurseForge has {len(hits)} modpacks with slug {base['curseforge_slug']!r}")
    return hits[0]


def download(url, sha1, cache, label):
    """Download to cache/download.tmp and verify the SHA-1."""
    url = https_url(url)
    cache.mkdir(parents=True, exist_ok=True)
    temp = cache / "download.tmp"
    print(f"Downloading {label}...")
    h, total = hashlib.sha1(), 0
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as response, temp.open("wb") as out:
        https_url(response.url)
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > EXPORT_LIMIT:
                raise ResolutionError("The export download is unexpectedly large")
            h.update(chunk)
            out.write(chunk)
    if h.hexdigest() != sha1.lower():
        temp.unlink()
        raise ResolutionError("The export download does not match CurseForge's checksum")
    return temp


def download_export(api, settings, file_id, cache):
    """Download a release of the base modpack from CurseForge (API key route)."""
    project = find_base_project(api, settings)
    if file_id is None:
        query = urlencode({"gameVersion": settings["minecraft"], "pageSize": 50})
        candidates = [f for f in api.get(f"{CF}/mods/{project['id']}/files?{query}", curseforge=True, fresh=True)["data"]
                      if f.get("releaseType") == 1 and not f.get("isServerPack")]
        if not candidates:
            raise ResolutionError(f"{project['name']} has no release for Minecraft {settings['minecraft']}")
        file = max(candidates, key=lambda f: f["fileDate"])
    else:
        file = api.get(f"{CF}/mods/{project['id']}/files/{int(file_id)}", curseforge=True)["data"]
    sha1 = next((h["value"] for h in file.get("hashes", []) if h.get("algo") == 1), "")
    if not file.get("downloadUrl") or not re.fullmatch(r"[a-fA-F0-9]{40}", sha1):
        raise ResolutionError(f"{file.get('fileName')} has no automatic download; use the CurseForge app route")
    return download(file["downloadUrl"], sha1, cache, file["fileName"]), project["id"], file["id"]


def cache_export(path, cache):
    """Keep a copy of the export by content hash so later rebuilds need no download."""
    sha256 = digest(Path(path).read_bytes())
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / f"{sha256}.zip"
    if Path(path).resolve() != cached.resolve():
        shutil.copyfile(path, cached)
    return cached, sha256


# --- A CurseForge app profile (no API key) ---------------------------------------
# The CurseForge app saves every installed file's name and SHA-1 in the profile's
# minecraftinstance.json, and the modpack export's own download URL.

def default_instances_dir():
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "curseforge" / "minecraft" / "Instances"


def read_profile(folder):
    """Return the parts of a CurseForge profile the importer uses, or None if it is not a modpack install."""
    path = Path(folder) / "minecraftinstance.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    modpack = data.get("installedModpack") or {}
    file = modpack.get("installedFile") or {}
    if not file:
        return None
    return {
        "folder": Path(folder), "name": data.get("name") or Path(folder).name,
        "minecraft": data.get("gameVersion"), "loader": (data.get("baseModLoader") or {}).get("name", ""),
        "modpack_id": modpack.get("addonID"), "modpack_name": modpack.get("name", ""),
        "export": file, "addons": data.get("installedAddons") or [],
        "updated": path.stat().st_mtime,
    }


def find_profiles(instances, settings):
    """CurseForge profiles installed from the base modpack, newest first."""
    base = settings["base"]
    found = []
    if Path(instances).is_dir():
        for folder in Path(instances).iterdir():
            profile = read_profile(folder) if folder.is_dir() else None
            if not profile or profile["minecraft"] != settings["minecraft"]:
                continue
            if base.get("curseforge_project_id"):
                match = profile["modpack_id"] == int(base["curseforge_project_id"])
            else:
                match = slugify(profile["modpack_name"]).startswith(base["curseforge_slug"])
            if match:
                found.append(profile)
    return sorted(found, key=lambda p: p["updated"], reverse=True)


def describe(profile):
    loader = profile["loader"].replace("neoforge-", "NeoForge ")
    return f"{profile['name']}  ({profile['export'].get('fileName', '?')}, {loader})"


def choose_profile(profiles, assume_yes=False, read=input, write=print):
    """Suggest the newest profile and let the maintainer confirm it or pick another."""
    if not profiles:
        return None
    if assume_yes or len(profiles) == 1 and not sys.stdin.isatty():
        return profiles[0]
    if not sys.stdin.isatty() and read is input:
        raise ResolutionError("Several profiles match; pass --profile PATH or --yes to use the newest")
    write("")
    write("Base modpack profiles found in CurseForge (newest first):")
    write("")
    for number, profile in enumerate(profiles, 1):
        marker = ">" if number == 1 else " "
        write(f"  {marker} {number}) {describe(profile)}")
        write(f"       {profile['folder']}")
    write("")
    while True:
        prompt = (f"Use {profiles[0]['name']}? [Enter = yes, 1-{len(profiles)} = choose, q = quit] "
                  if len(profiles) > 1 else f"Use {profiles[0]['name']}? [Enter = yes, q = quit] ")
        answer = read(prompt).strip().lower()
        if answer in ("", "y", "yes"):
            return profiles[0]
        if answer in ("q", "n", "no", "quit"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(profiles):
            return profiles[int(answer) - 1]
        write("Please answer with Enter, a number from the list, or q.")


def check_profile(profile, settings):
    if profile["minecraft"] != settings["minecraft"]:
        raise ResolutionError(f"{profile['name']} is for Minecraft {profile['minecraft']}, not {settings['minecraft']}")
    if not profile["loader"].startswith("neoforge-"):
        raise ResolutionError(f"{profile['name']} does not use NeoForge ({profile['loader'] or 'no loader'})")


def fetch_profile_export(profile, cache):
    """Download (or reuse) the modpack export the profile was installed from, verified by its SHA-1."""
    file = profile["export"]
    sha1 = next((h["value"].lower() for h in file.get("hashes", []) if h.get("type", h.get("algo")) == 1), "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha1):
        raise ResolutionError(f"{profile['name']}: the modpack file has no SHA-1 checksum")
    cache.mkdir(parents=True, exist_ok=True)
    known = cache / f"sha1-{sha1}.txt"
    if known.exists():
        cached = cache / f"{known.read_text().strip()}.zip"
        if cached.exists() and hashlib.sha1(cached.read_bytes()).hexdigest() == sha1:
            return cached, cached.stem
    temp = download(file.get("downloadUrl") or "", sha1, cache, file.get("fileName", "the modpack export"))
    path, sha256 = cache_export(temp, cache)
    temp.unlink()
    known.write_text(sha256)
    return path, sha256


def profile_lookup(profile):
    """The profile's installed files as API-shaped project and file data ({id: data})."""
    projects, files = {}, {}
    for addon in profile["addons"]:
        file = addon.get("installedFile") or {}
        if not addon.get("addonID") or not file.get("id"):
            continue
        website = addon.get("webSiteURL") or ""
        projects[addon["addonID"]] = {
            "id": addon["addonID"], "name": addon.get("name", file.get("fileName")),
            "slug": website.rstrip("/").rsplit("/", 1)[-1] if website else str(addon["addonID"]),
            "classId": addon.get("categoryClassID"),
        }
        files[file["id"]] = {"id": file["id"], "modId": addon["addonID"], "fileName": file.get("fileName"),
                             "hashes": [{"algo": h.get("type"), "value": h.get("value")} for h in file.get("hashes", [])]}
    return projects, files


def curseforge_lookup(api, wanted):
    """Read the export's projects and files from the CurseForge API (needs CURSEFORGE_API_KEY)."""
    projects, files = {}, {}
    for batch in chunks(sorted({int(f["projectID"]) for f in wanted}), 100):
        for p in api.get(f"{CF}/mods", curseforge=True, body={"modIds": batch})["data"]:
            projects[p["id"]] = p
    for batch in chunks([int(f["fileID"]) for f in wanted], 100):
        for f in api.get(f"{CF}/mods/files", curseforge=True, body={"fileIds": batch})["data"]:
            files[f["id"]] = f
    return projects, files


def base_files(manifest, export_files, api, lookup):
    """Describe the base pack's mods (install path, project IDs) to catch extras it already has.

    Each file's Modrinth project is found by its SHA-1, so an extra from Modrinth that the base pack
    ships from CurseForge (or bundles in its overrides) is caught too. Files missing from the lookup
    keep their IDs only."""
    projects, files = lookup
    found = []
    for entry in manifest.get("files", []):
        project, file = projects.get(int(entry["projectID"]), {}), files.get(int(entry["fileID"]), {})
        sha1 = next((h["value"].lower() for h in file.get("hashes", []) if h.get("algo") == 1), "")
        folder = CLASS_FOLDERS.get(project.get("classId"), "mods")
        found.append({"name": project.get("name") or file.get("fileName") or str(entry["projectID"]),
                      "slug": project.get("slug", ""), "curseforge_project_id": int(entry["projectID"]),
                      "curseforge_file_id": int(entry["fileID"]),
                      "path": f"{folder}/{file['fileName']}" if file.get("fileName") else None,
                      "sha1": sha1 if re.fullmatch(r"[a-f0-9]{40}", sha1) else None})
    for relative, sha1 in sorted(export_files.items()):
        if sha1:
            found.append({"name": relative.rsplit("/", 1)[-1], "slug": "", "curseforge_project_id": None,
                          "curseforge_file_id": None, "path": relative, "sha1": sha1})
    on_modrinth = {}
    for batch in chunks(sorted({f["sha1"] for f in found if f["sha1"]}), 200):
        on_modrinth.update(api.get(f"{MR}/version_files", body={"hashes": batch, "algorithm": "sha1"}))
    for item in found:
        version = on_modrinth.get(item.pop("sha1") or "")
        item["modrinth_project_id"] = version["project_id"] if version else None
    return found


# --- Building the pack --------------------------------------------------------------

def plan_pack(base, base_overrides, extras, local_files, preserve):
    """Return {path: (bytes, flags)} for every pack file, checking it does not clash with the base pack.

    Local overrides may replace the base pack's config files (that is their purpose), but nothing
    may replace one of its mods or resource packs."""
    base_paths = {item["path"].casefold(): item["name"] for item in base if item["path"]}
    base_paths.update({p.casefold(): "the base pack" for p in base_overrides if p.startswith("mods/")})
    base_projects = {("curseforge", str(item["curseforge_project_id"])): item["name"]
                     for item in base if item["curseforge_project_id"]}
    base_projects.update({("modrinth", item["modrinth_project_id"]): item["name"]
                          for item in base if item["modrinth_project_id"]})
    plan, paths, claimed, extra_projects = {}, {}, {}, {}

    def claim(destination, owner):
        key = destination.casefold()
        if key in base_paths:
            raise ResolutionError(f"{owner} would replace {base_paths[key]}'s file {destination}")
        if key in claimed:
            raise ResolutionError(f"{owner} and {claimed[key]} would both install {destination}")
        claimed[key] = owner

    for record in extras:
        owner = f"extra mod {record['name']}"
        keys = {(record["provider"], str(record.get("project_id")))}
        if record.get("curseforge_project_id"):
            keys.add(("curseforge", str(record["curseforge_project_id"])))
        for key in keys:
            if key in base_projects:
                raise ResolutionError(f"{owner} is the same project as {base_projects[key]}, which the base pack "
                                      "already includes")
            if key in extra_projects:
                raise ResolutionError(f"{owner} is the same project as {extra_projects[key]}")
            extra_projects[key] = owner
        claim(f"mods/{record['filename']}", owner)
        path = f"mods/{record['slug']}.pw.toml"
        if path in plan:
            raise ResolutionError(f"Two extras use the slug {record['slug']!r}")
        plan[path] = (metadata({"name": record["name"], "side": record.get("side", "both")}, record).encode(),
                      {"metafile": True})
        paths[path] = record
    for relative, data in sorted(local_files.items()):
        if relative.endswith(".pw.toml"):
            raise ResolutionError(f"sources/local-overrides cannot contain mod metadata: {relative}")
        claim(relative, "sources/local-overrides")
        plan[relative] = (data, {})
    for relative, (data, flags) in plan.items():
        if not flags.get("metafile") and any(fnmatch.fnmatchcase(relative, p) for p in preserve):
            flags["preserve"] = True
    replaced = {p.casefold() for p in base_overrides}
    changed = sorted(r for r in local_files if r.casefold() in replaced)
    return plan, paths, changed


def read_local_overrides(root):
    base = root / "sources/local-overrides"
    files = {}
    if base.is_dir():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            relative = path.relative_to(base).as_posix()
            inside(root, relative)
            check_install_path(relative)
            files[relative] = path.read_bytes()
    return files


def check_hand_edits(root, lock):
    """Refuse to overwrite files that changed since the importer last wrote them."""
    generated = lock.get("generated", {})
    problems = []
    if (root / "index.toml").exists():
        index = tomllib.loads((root / "index.toml").read_text(encoding="utf-8"))
        problems += [f"index.toml lists {f['file']}, which the importer did not generate"
                     for f in index.get("files", []) if f["file"] not in generated]
    for relative, expected in generated.items():
        path = inside(root, relative)
        if path.exists() and digest(path.read_bytes()) != expected:
            problems.append(f"{relative} was edited by hand")
    if problems:
        raise ResolutionError("; ".join(problems[:10]) + ". Put config changes in sources/local-overrides/ and extra "
                              "mods in sources/pack.json, then rerun (or pass --force to discard the edits).")


def description(base):
    """The pack's description. The updater reads the base modpack's project and file IDs from it."""
    return (f"Add-on for {base['name']} {base['version']} (CurseForge modpack {base['project_id']}, "
            f"file {base['file_id']}). Install {base['name']} in the CurseForge app first.")


def write_pack(root, settings, base, plan, paths, force=False):
    lock_path = root / "sources/lock.json"
    old = read_json(lock_path, {})
    if not force:
        check_hand_edits(root, old)
    old_generated = old.get("generated", {})
    for relative in plan:
        path = inside(root, relative)
        if path.exists() and relative not in old_generated and not force:
            raise ResolutionError(f"{relative} already exists and was not generated by the importer")
    # Remove what the previous build generated and this one does not, then write the new files.
    for relative in sorted(set(old_generated) - set(plan)):
        path = inside(root, relative)
        if path.exists():
            path.unlink()
        parent = path.parent
        while parent != root.resolve() and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    for relative, (data, _) in plan.items():
        path = inside(root, relative)
        if not path.exists() or path.read_bytes() != data:
            atomic_write_bytes(path, data)
    index = 'hash-format = "sha256"\n'
    for relative, (data, flags) in sorted(plan.items()):
        index += f"\n[[files]]\nfile = {json.dumps(relative, ensure_ascii=False)}\nhash = \"{digest(data)}\"\n"
        index += "".join(f"{flag} = true\n" for flag in ("metafile", "preserve") if flags.get(flag))
    tomllib.loads(index)
    version = f"{base['version']}-{settings['build']}"
    pack = (f"name = {json.dumps(settings['name'])}\nversion = {json.dumps(version)}\n"
            f"description = {json.dumps(description(base), ensure_ascii=False)}\n"
            'pack-format = "packwiz:1.1.0"\n\n[index]\nfile = "index.toml"\nhash-format = "sha256"\n'
            f'hash = "{digest(index.encode())}"\n\n[versions]\nminecraft = "{settings["minecraft"]}"\n'
            f'neoforge = "{base["neoforge"]}"\n')
    tomllib.loads(pack)
    write_json(lock_path, {
        "base": base, "pack_version": version,
        "records": {path: record for path, record in sorted(paths.items())},
        "generated": {relative: digest(data) for relative, (data, _) in sorted(plan.items())},
    })
    atomic_write(root / "index.toml", index)
    # Written last so an interrupted build never looks complete.
    atomic_write(root / "pack.toml", pack)
    return version


def archived_candidates(root, base, extras=()):
    """List mods of the archived standalone pack that neither the base pack nor the extras contain."""
    archived = read_json(root / "archive/standalone-134/sources/resolved.json", {})
    have_ids = ({str(f["curseforge_project_id"]) for f in base if f["curseforge_project_id"]} |
                {f["modrinth_project_id"] for f in base if f["modrinth_project_id"]} |
                {str(r["project_id"]) for r in extras if r.get("project_id")})
    have_names = ({slugify(f["name"]) for f in base} | {f["slug"] for f in base if f["slug"]} |
                  {slugify(r["name"]) for r in extras} | {r["slug"] for r in extras})
    return sorted(r.get("name", name) for name, r in archived.items()
                  if str(r.get("project_id")) not in have_ids and slugify(r.get("name", "")) not in have_names)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--profile", type=Path, help="CurseForge profile folder installed from the base modpack")
    source.add_argument("--rebuild", action="store_true", help="Reuse the last import's base pack (no profile or API)")
    source.add_argument("--latest", action="store_true", help="API key route: download the newest release")
    source.add_argument("--file-id", type=int, help="API key route: download this CurseForge file")
    parser.add_argument("--yes", action="store_true", help="Use the newest matching profile without asking")
    parser.add_argument("--instances", type=Path, help="CurseForge Instances folder, if not the default")
    parser.add_argument("--offline", action="store_true", help="Use cached API responses only")
    parser.add_argument("--force", action="store_true", help="Overwrite generated files that were edited by hand")
    args = parser.parse_args(argv)

    settings = load_settings(root)
    overrides = read_json(root / "sources/overrides.json", {})
    lock = read_json(root / "sources/lock.json", {})
    api = API(root / ".cache/api", os.environ.get("CURSEFORGE_API_KEY", ""), args.offline)
    cache = root / ".cache/export"
    profile = None
    if args.latest or args.file_id:
        downloaded, project_id, file_id = download_export(api, settings, args.file_id, cache)
        path, sha256 = cache_export(downloaded, cache)
        downloaded.unlink()
    elif args.rebuild:
        previous = lock.get("base", {})
        path, sha256 = cache / f"{previous.get('sha256', 'none')}.zip", previous.get("sha256")
        project_id, file_id = previous.get("project_id"), previous.get("file_id")
        if not sha256 or not path.exists() or "files" not in previous:
            raise ResolutionError("Nothing to rebuild from: run an import first.")
    else:
        if args.profile:
            profile = read_profile(args.profile)
            if profile is None:
                raise ResolutionError(f"{args.profile} is not a CurseForge profile installed from a modpack")
        else:
            instances = args.instances or default_instances_dir()
            profile = choose_profile(find_profiles(instances, settings), assume_yes=args.yes)
            if profile is None:
                if not find_profiles(instances, settings):
                    raise ResolutionError(
                        f"No CurseForge profile installed from {settings['base']['curseforge_slug']} was found in "
                        f"{instances}. Install it in the CurseForge app (or pass --profile / --instances).")
                print("Cancelled; nothing was changed.")
                return 1
        check_profile(profile, settings)
        print(f"Using {describe(profile)}")
        path, sha256 = fetch_profile_export(profile, cache)
        project_id, file_id = profile["modpack_id"], profile["export"].get("id")
    manifest, export_files = read_export(path, settings["minecraft"])
    if not project_id or not file_id:
        raise ResolutionError("The base modpack's CurseForge project and file IDs are unknown")
    neoforge = select_neoforge(api, manifest["neoforge"])
    print(f"{manifest.get('name')} {manifest['version']}: {len(manifest.get('files', []))} files, "
          f"{len(export_files)} override files, NeoForge {neoforge}.")

    if args.rebuild:
        base_list = lock["base"]["files"]
    else:
        wanted = manifest.get("files", [])
        lookup = profile_lookup(profile) if profile is not None else curseforge_lookup(api, wanted)
        base_list = base_files(manifest, export_files, api, lookup)
    cached_extras = {r["filename"]: r for r in lock.get("records", {}).values()}
    extras, unresolved = [], []
    for mod in settings["extras"]:
        try:
            record = resolve_mod(mod, api, settings["minecraft"], overrides, cached_extras)
            extras.append(dict(record, slug=mod["slug"]))
        except ResolutionError as exc:
            unresolved.append({"filename": mod["filename"], "name": mod["name"], "reason": str(exc)})
    write_json(root / "sources/unresolved.json", unresolved)
    if unresolved:
        for item in unresolved:
            print(f"Unresolved: {item['filename']}: {item['reason']}", file=sys.stderr)
        print(f"{len(unresolved)} extras are unresolved; the pack was not changed. See sources/unresolved.json.",
              file=sys.stderr)
        return 1

    plan, paths, changed = plan_pack(base_list, export_files, extras, read_local_overrides(root), settings["preserve"])
    base = {"name": manifest.get("name") or settings["base"]["curseforge_slug"], "version": manifest["version"],
            "neoforge": neoforge, "project_id": int(project_id), "file_id": int(file_id), "sha256": sha256,
            "source": lock.get("base", {}).get("source", "rebuild") if args.rebuild else "profile" if profile else "api",
            "files": base_list}
    version = write_pack(root, settings, base, plan, paths, args.force)
    print(f"Built {settings['name']} {version} for {base['name']} {base['version']}: {len(extras)} extra mods, "
          f"{len(plan) - len(extras)} config files ({len(changed)} replace the base pack's). "
          "Run scripts/validate_pack.py next.")
    candidates = archived_candidates(root, base_list, extras)
    if candidates:
        print(f"{len(candidates)} mods of the archived standalone pack are in neither the base pack nor the extras "
              "(candidates for extras): " + ", ".join(candidates))
    return 0


if __name__ == "__main__":
    # Mod names can contain characters the Windows console code page lacks.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    try:
        sys.exit(main())
    except (ResolutionError, KeyError, ValueError, OSError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        sys.exit(1)
