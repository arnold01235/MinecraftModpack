#!/usr/bin/env python3
"""Shared resolution helpers for the pack importer (scripts/import_craftoria.py).

Python 3.11+, standard library only. Resolves exact mod files on Modrinth or
CurseForge (or a reviewed Curse Maven artifact) without silently upgrading them.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import tomllib
from zipfile import BadZipFile, ZipFile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MR = "https://api.modrinth.com/v2"
CF = "https://api.curseforge.com/v1"
USER_AGENT = "MinecraftModded-pack-import/1.0"
HASH_LENGTHS = {"sha512": 128, "sha256": 64, "sha1": 40}
CLIENT_ENVIRONMENTS = {"client_only", "client_only_server_optional", "singleplayer_only"}


class ResolutionError(Exception):
    pass


def read_json(path: Path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, content: str):
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def write_json(path: Path, value):
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(data: bytes, algorithm="sha256"):
    return hashlib.new(algorithm, data).hexdigest()


def https_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ResolutionError("Expected a public HTTPS URL without credentials")
    return url


def safe_filename(name: str):
    if not name or name in {".", ".."} or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
        raise ResolutionError(f"Unsafe filename: {name!r}")
    if name.endswith((" ", ".")):
        raise ResolutionError(f"Unsafe filename: {name!r}")
    return name


def windows_neoforge_json(url: str):
    """Retry public NeoForge metadata using Windows' certificate-chain engine."""
    https_url(url)
    if sys.platform != "win32" or urlparse(url).netloc != "maven.neoforged.net":
        raise ResolutionError("Windows TLS retry is restricted to public NeoForge metadata")
    # Use the OS binary, not an executable in the project or PATH.
    curl = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "curl.exe"
    if not curl.is_file():
        raise ResolutionError("Windows curl.exe is unavailable; Python could not verify the NeoForge certificate")
    common = {"capture_output": True, "timeout": 45, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        version = subprocess.run([str(curl), "--disable", "--version"], **common)
        if version.returncode != 0 or b"Schannel" not in version.stdout:
            raise ResolutionError("Windows TLS retry requires the system curl with Schannel support")
        result = subprocess.run([
            str(curl), "--disable", "--fail", "--silent", "--show-error", "--location",
            "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2",
            "--connect-timeout", "10", "--max-time", "30", "--max-filesize", "4194304",
            "--header", "Accept: application/json", "--user-agent", USER_AGENT, "--url", url,
        ], **common)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResolutionError(f"Windows HTTPS retry failed: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:1200]
        raise ResolutionError(
            f"Windows HTTPS retry failed (curl exit {result.returncode}): {detail}. "
            "Certificate verification remains enabled. Check the clock, Windows certificate updates, "
            "and the server or HTTPS-inspection certificate; no pack was generated.")
    if not result.stdout or len(result.stdout) > 4 * 1024 * 1024:
        raise ResolutionError("Windows HTTPS retry returned empty or oversized metadata")
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ResolutionError("Windows HTTPS retry returned invalid JSON metadata") from exc


def fetch_metadata_json(url: str, headers, body=None):
    try:
        data = None if body is None else json.dumps(body).encode()
        with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
            https_url(response.url)
            return json.load(response)
    except (URLError, ssl.SSLCertVerificationError) as exc:
        reason = getattr(exc, "reason", exc)
        if (body is not None or sys.platform != "win32" or urlparse(url).netloc != "maven.neoforged.net" or
                not isinstance(reason, ssl.SSLCertVerificationError)):
            raise
        # No insecure flags, trust-store edits, API credentials or HTTP fallback.
        data = windows_neoforge_json(url)
        print("NeoForge metadata verified successfully using Windows HTTPS.")
        return data


class API:
    def __init__(self, cache: Path, cf_key: str = "", offline=False):
        self.cache, self.cf_key, self.offline = cache, cf_key, offline

    def get(self, url: str, *, curseforge=False, fresh=False, body=None):
        """GET a JSON document, or POST `body` as JSON (batch lookups). Responses are cached."""
        https_url(url)
        key = url if body is None else url + " " + json.dumps(body, sort_keys=True)
        cached = self.cache / (digest(key.encode()) + ".json")
        if cached.exists() and not fresh:
            return read_json(cached)
        if self.offline:
            raise ResolutionError("Metadata is not cached (offline mode)")
        if curseforge and not self.cf_key:
            raise ResolutionError("CurseForge API lookup needs CURSEFORGE_API_KEY or a verified override")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if curseforge:
            if urlparse(url).netloc != "api.curseforge.com":
                raise ResolutionError("Refusing to send the CurseForge key to a different host")
            headers["x-api-key"] = self.cf_key
        for attempt in range(3):
            try:
                data = fetch_metadata_json(url, headers, body)
                write_json(cached, data)
                return data
            except HTTPError as exc:
                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt < 2:
                        time.sleep(2 ** (attempt + 1))
                        continue
                raise ResolutionError(f"HTTP {exc.code} from {urlparse(url).netloc}") from exc
            except (URLError, OSError, ValueError) as exc:
                raise ResolutionError(f"Cannot read metadata from {urlparse(url).netloc}: {exc}") from exc
        raise ResolutionError("Metadata request failed")


    def download(self, url: str, limit=16 * 1024 * 1024):
        https_url(url)
        if self.offline:
            raise ResolutionError("Download verification needs an online run")
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                https_url(response.url)
                data = response.read(limit + 1)
            if not data or len(data) > limit:
                raise ResolutionError("Download is empty or exceeds the verification size limit")
            return data
        except (URLError, OSError) as exc:
            raise ResolutionError(f"Cannot verify download from {urlparse(url).netloc}: {exc}") from exc


def validate_extras(mods):
    """Check hand-written mod entries (the pack's extra mods)."""
    names = [m["filename"] for m in mods]
    if len(set(n.casefold() for n in names)) != len(names):
        raise ResolutionError("Duplicate extra mod filenames")
    for mod in mods:
        safe_filename(mod["filename"])
        if not re.fullmatch(r"[a-z0-9-]+", mod["slug"]):
            raise ResolutionError(f"Unsafe source slug: {mod['slug']}")
        if mod["side"] not in {"client", "both"}:
            raise ResolutionError("Extra mods must be included on the client")
        mod.setdefault("allowed_loaders", ["neoforge"])
    if len({m["slug"] for m in mods}) != len(mods):
        raise ResolutionError("Duplicate source slugs")


def validate_record(mod, record, minecraft):
    if record.get("filename") != mod["filename"]:
        raise ResolutionError("Download filename does not exactly match the inventory")
    https_url(record.get("url", ""))
    algorithm, value = record.get("hash_format"), record.get("hash", "")
    if algorithm not in HASH_LENGTHS or not re.fullmatch(f"[a-fA-F0-9]{{{HASH_LENGTHS[algorithm]}}}", value):
        raise ResolutionError("Missing or invalid download checksum")
    if minecraft not in record.get("game_versions", []):
        raise ResolutionError(f"Release does not declare Minecraft {minecraft}")
    if not set(mod["allowed_loaders"]).intersection(record.get("loaders", [])):
        raise ResolutionError("Release does not declare the expected loader")
    if record.get("side", mod["side"]) not in {"client", "both"}:
        raise ResolutionError("Release would exclude an enabled mod from the client")
    if record.get("provider") not in {"modrinth", "curseforge", "direct"}:
        raise ResolutionError("Unknown download provider")
    if record["provider"] in {"modrinth", "curseforge"}:
        if not record.get("project_id") or not record.get("version_id"):
            raise ResolutionError("Missing immutable provider project/version IDs")
    return record


def from_modrinth(mod, version, project, minecraft):
    matching = [f for f in version.get("files", []) if f["filename"] == mod["filename"]]
    if not matching:
        raise ResolutionError("No exact filename in this release")
    f = matching[0]
    algorithm = next((a for a in HASH_LENGTHS if f.get("hashes", {}).get(a)), None)
    environment = version.get("environment")
    side = "client" if (environment in CLIENT_ENVIRONMENTS or project.get("server_side") == "unsupported") else mod["side"]
    record = {
        "filename": f["filename"], "name": project.get("title", mod["name"]), "side": side,
        "provider": "modrinth", "project_id": version["project_id"], "version_id": version["id"],
        "url": f["url"], "hash_format": algorithm, "hash": f.get("hashes", {}).get(algorithm, ""),
        "game_versions": version.get("game_versions", []), "loaders": version.get("loaders", []),
        "dependencies": version.get("dependencies", []),
        "source": f"https://modrinth.com/mod/{version['project_id']}/version/{version['id']}",
    }
    return validate_record(mod, record, minecraft)


def resolve_modrinth(mod, api, minecraft):
    errors = []
    candidates = list(mod.get("modrinth", []))
    if mod.get("modrinth_version"):
        try:
            v = api.get(f"{MR}/version/{quote(mod['modrinth_version'])}")
            p = api.get(f"{MR}/project/{v['project_id']}")
            return from_modrinth(mod, v, p, minecraft)
        except ResolutionError as exc:
            errors.append(str(exc))
    # Exact releases can be unlisted and absent from the project's version list.
    direct_urls = []
    if mod.get("modrinth_version_number"):
        number = quote(mod["modrinth_version_number"], safe="")
        direct_urls.extend(f"{MR}/project/{quote(candidate, safe='')}/version/{number}" for candidate in candidates)
    file_hash = mod.get("modrinth_file_hash")
    if file_hash:
        algorithm, value = file_hash["algorithm"], file_hash["value"]
        if algorithm not in {"sha1", "sha512"} or not re.fullmatch(f"[a-fA-F0-9]{{{HASH_LENGTHS[algorithm]}}}", value):
            raise ResolutionError("Invalid Modrinth lookup hash")
        direct_urls.append(f"{MR}/version_file/{value.lower()}?algorithm={algorithm}")
    for url in direct_urls:
        try:
            v = api.get(url)
            p = api.get(f"{MR}/project/{v['project_id']}")
            record = from_modrinth(mod, v, p, minecraft)
            if file_hash and not any(
                f["filename"] == mod["filename"] and
                f.get("hashes", {}).get(file_hash["algorithm"], "").lower() == file_hash["value"].lower()
                for f in v.get("files", [])):
                raise ResolutionError("Resolved release does not match the supplied file hash")
            return record
        except ResolutionError as exc:
            errors.append(str(exc))
    # Candidate slugs are just hints: release filename, game and loader must all match.
    # Search results are only additional candidates and never select a newer release.
    checked = set()
    for search_pass in (False, True):
        if search_pass:
            try:
                query = urlencode({"query": mod["name"], "limit": 5})
                hits = api.get(f"{MR}/search?{query}").get("hits", [])
                candidates.extend(h["project_id"] for h in hits)
            except ResolutionError as exc:
                errors.append(str(exc))
        for candidate in candidates:
            if candidate in checked:
                continue
            checked.add(candidate)
            try:
                p = api.get(f"{MR}/project/{quote(candidate)}")
                versions = api.get(f"{MR}/project/{p['id']}/version?" + urlencode({
                    "game_versions": json.dumps([minecraft]), "loaders": json.dumps(mod["allowed_loaders"])}))
                matches = []
                for v in versions:
                    if any(f["filename"] == mod["filename"] for f in v.get("files", [])):
                        matches.append(from_modrinth(mod, v, p, minecraft))
                if matches:
                    if len({r["hash"] for r in matches}) != 1:
                        raise ResolutionError("Ambiguous releases: same filename has different hashes")
                    return matches[0]
            except ResolutionError as exc:
                errors.append(str(exc))
    detail = "; ".join(dict.fromkeys(errors))[:400]
    raise ResolutionError("Modrinth: no compatible exact filename" + ("; " + detail if detail else ""))


def from_curseforge(mod, file, project, minecraft):
    if file.get("fileName") != mod["filename"]:
        raise ResolutionError("CurseForge file does not match the inventory")
    if not file.get("downloadUrl"):
        raise ResolutionError("Publisher has no automatic download URL; needs a permitted direct source")
    hashes = {h["algo"]: h["value"] for h in file.get("hashes", [])}
    if 1 not in hashes:
        raise ResolutionError("CurseForge file has no SHA-1 checksum")
    tags = file.get("gameVersions", [])
    record = {
        "filename": file["fileName"], "name": project.get("name", mod["name"]), "side": mod["side"],
        "provider": "curseforge", "project_id": project["id"], "version_id": file["id"],
        "url": file["downloadUrl"], "hash_format": "sha1", "hash": hashes[1],
        "game_versions": tags, "loaders": [v.lower() for v in tags if v.lower() in {"neoforge", "fabric", "forge", "quilt"}],
        "dependencies": file.get("dependencies", []),
        "source": f"https://www.curseforge.com/minecraft/mc-mods/{project['slug']}/files/{file['id']}",
    }
    return validate_record(mod, record, minecraft)


def resolve_curseforge(mod, api, minecraft):
    if not api.cf_key and not api.offline:
        raise ResolutionError("CurseForge API lookup needs CURSEFORGE_API_KEY or a verified override")
    if mod.get("curseforge_project_id"):
        p = api.get(f"{CF}/mods/{mod['curseforge_project_id']}", curseforge=True)["data"]
        if mod.get("curseforge_file_id"):
            f = api.get(f"{CF}/mods/{p['id']}/files/{mod['curseforge_file_id']}", curseforge=True)["data"]
            return from_curseforge(mod, f, p, minecraft)
        projects = [p]
    else:
        projects = []
        for slug in mod.get("curseforge", []):
            query = urlencode({"gameId": 432, "classId": 6, "slug": slug, "pageSize": 50})
            projects.extend(api.get(f"{CF}/mods/search?{query}", curseforge=True)["data"])
    for p in projects:
        offset = 0
        while offset < 10000:
            query = urlencode({"gameVersion": minecraft, "pageSize": 50, "index": offset})
            page = api.get(f"{CF}/mods/{p['id']}/files?{query}", curseforge=True)
            files = page["data"]
            for f in files:
                if f.get("fileName") == mod["filename"]:
                    return from_curseforge(mod, f, p, minecraft)
            offset += len(files)
            if not files or offset >= page.get("pagination", {}).get("totalCount", offset):
                break
    raise ResolutionError("CurseForge: no compatible exact filename")


def from_maven_download(mod, data, minecraft):
    """Verify an explicitly reviewed Curse Maven artifact before making metadata."""
    source = mod["curseforge_maven"]
    expected_hash = source.get("sha1", "")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", expected_hash) or digest(data, "sha1") != expected_hash.lower():
        raise ResolutionError("Curse Maven download does not match the expected file checksum")
    try:
        with ZipFile(BytesIO(data)) as jar:
            entry = jar.getinfo("META-INF/neoforge.mods.toml")
            if entry.file_size > 1024 * 1024:
                raise ResolutionError("JAR mod metadata is unexpectedly large")
            info = tomllib.loads(jar.read(entry).decode("utf-8"))
            installed = next((m for m in info.get("mods", []) if m.get("modId") == source["mod_id"]), None)
            if installed is None:
                raise ResolutionError("JAR does not contain the expected mod ID")
            version = installed.get("version")
            if version == "$" + "{file.jarVersion}":
                manifest_entry = jar.getinfo("META-INF/MANIFEST.MF")
                if manifest_entry.file_size > 1024 * 1024:
                    raise ResolutionError("JAR manifest is unexpectedly large")
                manifest = jar.read(manifest_entry).decode("utf-8").replace("\r\n", "\n").replace("\n ", "")
                attributes = dict(line.split(": ", 1) for line in manifest.split("\n\n", 1)[0].splitlines() if ": " in line)
                version = attributes.get("Implementation-Version")
            if version != source["version"]:
                raise ResolutionError("JAR does not contain the expected mod version")
            if jar.testzip() is not None:
                raise ResolutionError("JAR contains a corrupt entry")
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ResolutionError(f"Invalid NeoForge JAR: {exc}") from exc
    record = {
        "filename": mod["filename"], "name": mod["name"], "side": mod["side"],
        "provider": "curseforge", "project_id": mod["curseforge_project_id"], "version_id": mod["curseforge_file_id"],
        "url": source["url"], "hash_format": "sha512", "hash": digest(data, "sha512"),
        "game_versions": source["game_versions"], "loaders": source["loaders"],
        "source": mod["source_reference"],
        "verification": {"method": "downloaded-jar", "sha1": digest(data, "sha1"),
                         "mod_id": source["mod_id"], "version": version, "size": len(data)},
        "jar_dependencies": info.get("dependencies", {}).get(source["mod_id"], []),
    }
    return validate_record(mod, record, minecraft)


def resolve_maven(mod, api, minecraft):
    source = mod.get("curseforge_maven")
    if not source:
        raise ResolutionError("No reviewed Curse Maven source configured")
    return from_maven_download(mod, api.download(source["url"]), minecraft)


def metadata(mod, record):
    # JSON string escaping is valid for the basic TOML strings used here.
    q = lambda value: json.dumps(value, ensure_ascii=False)
    text = (f"name = {q(record.get('name', mod['name']))}\nfilename = {q(record['filename'])}\n"
            f"side = {q(record.get('side', mod['side']))}\n\n[download]\n"
            f"url = {q(record['url'])}\nhash-format = {q(record['hash_format'])}\nhash = {q(record['hash'])}\n")
    if record["provider"] == "modrinth":
        text += f"\n[update.modrinth]\nmod-id = {q(record['project_id'])}\nversion = {q(record['version_id'])}\n"
    elif record["provider"] == "curseforge":
        text += f"\n[update.curseforge]\nproject-id = {int(record['project_id'])}\nfile-id = {int(record['version_id'])}\n"
    tomllib.loads(text)
    return text


def select_neoforge(api, requested, minimum=None):
    if requested == "latest":
        if api.offline:
            raise ResolutionError("Selecting the latest NeoForge requires an online run; use an exact version offline")
        info = api.get("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge", fresh=True)
        versions = info.get("versions", []) if isinstance(info, dict) else []
        if not isinstance(versions, list):
            raise ResolutionError("Unexpected NeoForge version list")
        stable = [v for v in versions if isinstance(v, str) and re.fullmatch(r"21\.1\.\d+", v)]
        if not stable:
            raise ResolutionError("NeoForge metadata contains no stable Minecraft 1.21.1 releases")
        requested = max(stable, key=lambda v: int(v.rsplit(".", 1)[1]))
    if not re.fullmatch(r"21\.1\.\d+", requested or ""):
        raise ResolutionError("Use --neoforge latest or an exact stable 21.1.x version")
    if minimum:
        if not re.fullmatch(r"21\.1\.\d+", minimum):
            raise ResolutionError("Invalid minimum NeoForge version in the source catalog")
        if int(requested.rsplit(".", 1)[1]) < int(minimum.rsplit(".", 1)[1]):
            raise ResolutionError(f"The imported mods require NeoForge {minimum} or newer")
    if not api.offline:
        api.get(f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{requested}/neoforge-{requested}-moddev-config.json")
    return requested


def resolve_mod(mod, api, minecraft, overrides, cached):
    """Resolve one exact file: verified override, saved record, Modrinth, CurseForge, then Curse Maven."""
    filename = mod["filename"]
    if filename in overrides:
        return validate_record(mod, overrides[filename], minecraft)
    if filename in cached:
        return validate_record(mod, cached[filename], minecraft)
    try:
        return resolve_modrinth(mod, api, minecraft)
    except ResolutionError as mr_error:
        try:
            return resolve_curseforge(mod, api, minecraft)
        except ResolutionError as cf_error:
            if not mod.get("curseforge_maven"):
                raise ResolutionError(f"{mr_error}; {cf_error}") from cf_error
            try:
                return resolve_maven(mod, api, minecraft)
            except ResolutionError as maven_error:
                raise ResolutionError(f"{mr_error}; {cf_error}; {maven_error}") from maven_error
