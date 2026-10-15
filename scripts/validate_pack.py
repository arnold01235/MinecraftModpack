#!/usr/bin/env python3
"""Validate a complete packwiz pack and optionally verify every remote mod download."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys
import tomllib
from urllib.request import Request, urlopen

from import_pack import ROOT, HASH_LENGTHS, ResolutionError, https_url, inventory, read_json


def inside(root, relative):
    if not relative or "\\" in relative or ":" in relative:
        raise ResolutionError(f"Invalid pack path: {relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ResolutionError(f"Invalid pack path: {relative!r}")
    result = root.joinpath(*path.parts).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ResolutionError(f"Pack path escapes its root: {relative!r}")
    return result


def check_hash(data, algorithm, expected, label):
    if algorithm not in HASH_LENGTHS or not re.fullmatch(f"[a-fA-F0-9]{{{HASH_LENGTHS[algorithm]}}}", expected or ""):
        raise ResolutionError(f"Invalid checksum for {label}")
    if hashlib.new(algorithm, data).hexdigest() != expected.lower():
        raise ResolutionError(f"Checksum mismatch: {label}")


def validate(root=ROOT, exact=False, downloads=False):
    if not (root / "pack.toml").exists():
        raise ResolutionError("Pack is not ready: resolve all downloads and select NeoForge using scripts/import_pack.py.")
    pack = tomllib.loads((root / "pack.toml").read_text(encoding="utf-8"))
    if pack.get("pack-format") != "packwiz:1.1.0":
        raise ResolutionError("Unsupported pack format")
    versions = pack.get("versions", {})
    if versions.get("minecraft") != "1.21.1" or not re.fullmatch(r"21\.1\.\d+", versions.get("neoforge", "")):
        raise ResolutionError("Expected Minecraft 1.21.1 and an exact stable NeoForge 21.1.x version")
    info = pack["index"]
    index_path = inside(root, info["file"])
    raw_index = index_path.read_bytes()
    check_hash(raw_index, info["hash-format"], info["hash"], info["file"])
    index = tomllib.loads(raw_index.decode("utf-8"))
    default_hash = index["hash-format"]
    files = index.get("files", [])
    indexed, destinations, names = set(), set(), []
    for item in files:
        path = inside(root, item["file"])
        key = item["file"].casefold()
        if key in indexed:
            raise ResolutionError(f"Duplicate index entry: {item['file']}")
        indexed.add(key)
        if PurePosixPath(item["file"]).parts[0] not in {"mods", "config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks"}:
            raise ResolutionError(f"Source/updater files must not be installed: {item['file']}")
        content = path.read_bytes()
        check_hash(content, item.get("hash-format", default_hash), item["hash"], item["file"])
        if not item.get("metafile"):
            if path.suffix == ".toml" and path.name.endswith(".pw.toml"):
                raise ResolutionError(f"Missing metafile flag: {item['file']}")
            destination = path
        else:
            mod = tomllib.loads(content.decode("utf-8"))
            destination = inside(root, str(PurePosixPath(item["file"]).parent / mod["filename"]))
            if "alias" in item:
                raise ResolutionError("Metafiles cannot have aliases")
            if mod.get("side", "both") not in {"both", "client", "server"}:
                raise ResolutionError(f"Invalid side: {item['file']}")
            download = mod["download"]
            https_url(download["url"])
            algorithm, value = download["hash-format"], download["hash"]
            if algorithm not in HASH_LENGTHS or not re.fullmatch(f"[a-fA-F0-9]{{{HASH_LENGTHS[algorithm]}}}", value):
                raise ResolutionError(f"Invalid mod checksum: {item['file']}")
            if item["file"].startswith("mods/"):
                names.append(mod["filename"])
                if mod.get("side") == "server":
                    raise ResolutionError(f"Enabled inventory mod would be omitted on clients: {item['file']}")
            if downloads:
                print(f"Verifying download: {mod['filename']}")
                h = hashlib.new(algorithm)
                total = 0
                with urlopen(Request(download["url"], headers={"User-Agent": "MinecraftModded-pack-validate/1.0"}), timeout=120) as response:
                    https_url(response.url)
                    while chunk := response.read(1024 * 1024):
                        h.update(chunk)
                        total += len(chunk)
                if not total or h.hexdigest() != value.lower():
                    raise ResolutionError(f"Download checksum mismatch: {mod['filename']}")
        target = str(destination).casefold()
        if target in destinations:
            raise ResolutionError(f"Duplicate installed filename: {destination.name}")
        destinations.add(target)
    catalog = read_json(root / "sources/mods.json")
    expected_paths = {f"mods/{m['slug']}.pw.toml" for m in catalog["mods"]}
    missing = expected_paths - indexed
    if missing:
        raise ResolutionError(f"Missing {len(missing)} enabled inventory entries: {', '.join(sorted(missing))}")
    if exact and sorted(names) != sorted(inventory(root)):
        raise ResolutionError("Installed filenames do not exactly match the original enabled inventory")
    if any(name.endswith(".disabled") for name in names):
        raise ResolutionError("Disabled inventory files must not be installed")
    return {"mods": len(names), "files": len(files), "minecraft": versions["minecraft"], "neoforge": versions["neoforge"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Also require original exact mod filenames (before upgrades)")
    parser.add_argument("--downloads", action="store_true", help="Download each mod and verify its checksum without installing")
    args = parser.parse_args()
    result = validate(exact=args.inventory, downloads=args.downloads)
    print(f"Valid pack: {result['mods']} mods, Minecraft {result['minecraft']}, NeoForge {result['neoforge']}.")


if __name__ == "__main__":
    try:
        main()
    except (ResolutionError, OSError, ValueError, KeyError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
