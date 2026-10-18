import copy
import hashlib
from io import BytesIO, StringIO
from contextlib import redirect_stdout, redirect_stderr
from zipfile import ZipFile
import json
import os
import re
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_pack as importer
import import_craftoria as craftoria
from validate_pack import validate
from stage_site import stage


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mod = {
            "filename": "example-1.0-neoforge.jar", "name": "Example", "slug": "example",
            "side": "both", "modrinth": ["example"], "curseforge": ["example"],
            "allowed_loaders": ["neoforge"],
        }
        self.record = {
            "filename": self.mod["filename"], "name": "Example", "side": "both",
            "url": "https://cdn.modrinth.com/data/example/versions/version/example-1.0-neoforge.jar",
            "hash_format": "sha512", "hash": hashlib.sha512(b"fixture-only").hexdigest(),
            "provider": "modrinth", "project_id": "example", "version_id": "version",
            "game_versions": ["1.21.1"], "loaders": ["neoforge"],
        }

    def test_newer_version_is_rejected(self):
        newer = dict(self.record, filename="example-2.0-neoforge.jar")
        with self.assertRaisesRegex(importer.ResolutionError, "exactly match"):
            importer.validate_record(self.mod, newer, "1.21.1")

    def test_wrong_loader_and_wrong_game_are_rejected(self):
        for change in ({"loaders": ["forge"]}, {"game_versions": ["1.20.1"]}):
            with self.assertRaises(importer.ResolutionError):
                importer.validate_record(self.mod, dict(self.record, **change), "1.21.1")

    def test_incomplete_or_invalid_checksum_is_rejected(self):
        with self.assertRaises(importer.ResolutionError):
            importer.validate_record(self.mod, dict(self.record, hash="not-a-hash"), "1.21.1")

    def test_unsafe_destinations_are_rejected(self):
        from validate_pack import inside
        for path in ("../pack.toml", "/pack.toml", "D:/secret", "mods/../../secret", "mods\\..\\secret"):
            with self.assertRaises(importer.ResolutionError):
                inside(self.root, path)

    def test_offline_mode_does_not_make_network_requests(self):
        with patch.object(importer, "urlopen", side_effect=AssertionError("network called")):
            with self.assertRaisesRegex(importer.ResolutionError, "offline mode"):
                importer.API(self.root / ".cache", offline=True).get("https://api.modrinth.com/v2/project/example")

    def test_modrinth_selects_exact_file_instead_of_primary_file(self):
        version = {
            "id": "version", "project_id": "example", "game_versions": ["1.21.1"], "loaders": ["neoforge"],
            "files": [
                {"filename": "other.jar", "primary": True, "url": "https://example.com/other.jar", "hashes": {"sha512": "f" * 128}},
                {"filename": self.mod["filename"], "primary": False, "url": self.record["url"], "hashes": {"sha512": self.record["hash"]}},
            ],
        }
        result = importer.from_modrinth(self.mod, version, {"id": "example", "title": "Example"}, "1.21.1")
        self.assertEqual(result["filename"], self.mod["filename"])
        self.assertEqual(result["hash"], self.record["hash"])

    def exact_release_api(self, responses):
        class FakeAPI:
            def __init__(inner):
                inner.calls = []

            def get(inner, url):
                inner.calls.append(url)
                if url not in responses:
                    raise importer.ResolutionError("Release not available")
                return copy.deepcopy(responses[url])
        return FakeAPI()

    def exact_release(self):
        return {
            "id": "version", "project_id": "example", "game_versions": ["1.21.1"], "loaders": ["neoforge"],
            "files": [{"filename": self.mod["filename"], "url": self.record["url"],
                       "hashes": {"sha512": self.record["hash"], "sha1": "a" * 40}}],
        }

    def test_pinned_version_id_resolves_without_search(self):
        mod = dict(self.mod, modrinth_version="version")
        version_url = f"{importer.MR}/version/version"
        project_url = f"{importer.MR}/project/example"
        api = self.exact_release_api({version_url: self.exact_release(), project_url: {"id": "example", "title": "Example"}})
        self.assertEqual(importer.resolve_modrinth(mod, api, "1.21.1")["version_id"], "version")
        self.assertEqual(api.calls, [version_url, project_url])

    def test_unlisted_release_resolves_by_exact_version_number(self):
        mod = dict(self.mod, modrinth_version_number="1.0")
        version_url = f"{importer.MR}/project/example/version/1.0"
        project_url = f"{importer.MR}/project/example"
        api = self.exact_release_api({version_url: self.exact_release(), project_url: {"id": "example", "title": "Example"}})
        record = importer.resolve_modrinth(mod, api, "1.21.1")
        self.assertEqual(record["filename"], mod["filename"])
        self.assertEqual(api.calls, [version_url, project_url])

    def test_hash_lookup_recovers_release_missing_from_version_number_endpoint(self):
        mod = dict(self.mod, modrinth_version_number="1.0", modrinth_file_hash={"algorithm": "sha1", "value": "a" * 40})
        hash_url = f"{importer.MR}/version_file/{'a' * 40}?algorithm=sha1"
        project_url = f"{importer.MR}/project/example"
        api = self.exact_release_api({hash_url: self.exact_release(), project_url: {"id": "example", "title": "Example"}})
        self.assertEqual(importer.resolve_modrinth(mod, api, "1.21.1")["hash"], self.record["hash"])
        self.assertEqual(api.calls, [f"{importer.MR}/project/example/version/1.0", hash_url, project_url])

    def test_direct_release_lookup_rejects_wrong_file_game_loader_or_hash(self):
        mod = dict(self.mod, modrinth_version_number="1.0", modrinth_file_hash={"algorithm": "sha1", "value": "a" * 40})
        for invalid in ("filename", "game", "loader", "hash"):
            with self.subTest(invalid=invalid):
                version = self.exact_release()
                if invalid == "filename":
                    version["files"][0]["filename"] = "newer.jar"
                elif invalid == "game":
                    version["game_versions"] = ["1.20.1"]
                elif invalid == "loader":
                    version["loaders"] = ["fabric"]
                else:
                    version["files"][0]["hashes"]["sha1"] = "b" * 40
                api = self.exact_release_api({
                    f"{importer.MR}/project/example/version/1.0": version,
                    f"{importer.MR}/version_file/{'a' * 40}?algorithm=sha1": version,
                    f"{importer.MR}/project/example": {"id": "example", "title": "Example"},
                })
                with self.assertRaises(importer.ResolutionError):
                    importer.resolve_modrinth(mod, api, "1.21.1")

    def test_invalid_lookup_hash_is_rejected_before_network(self):
        mod = dict(self.mod, modrinth_file_hash={"algorithm": "sha1", "value": "bad-hash"})
        api = self.exact_release_api({})
        with self.assertRaisesRegex(importer.ResolutionError, "Invalid Modrinth lookup hash"):
            importer.resolve_modrinth(mod, api, "1.21.1")
        self.assertEqual(api.calls, [])

    def test_curseforge_paginates_to_find_older_exact_release(self):
        class FakeAPI:
            cf_key, offline = "fixture", False

            def get(inner, url, **kwargs):
                if "/mods/search?" in url:
                    return {"data": [{"id": 123, "slug": "example", "name": "Example"}]}
                if "index=0" in url:
                    return {"data": [{"fileName": "newer.jar"}], "pagination": {"totalCount": 2}}
                return {"data": [{
                    "id": 456, "fileName": self.mod["filename"], "downloadUrl": self.record["url"],
                    "hashes": [{"algo": 1, "value": "a" * 40}], "gameVersions": ["1.21.1", "NeoForge"],
                }], "pagination": {"totalCount": 2}}
        record = importer.resolve_curseforge(self.mod, FakeAPI(), "1.21.1")
        self.assertEqual(record["version_id"], 456)

    def test_missing_download_url_is_not_replaced_with_guessed_url(self):
        with self.assertRaisesRegex(importer.ResolutionError, "no automatic download"):
            importer.from_curseforge(self.mod, {"fileName": self.mod["filename"]}, {"id": 1}, "1.21.1")

    def maven_fixture(self, mod_id="example", version="1.0", manifest=False):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as jar:
            jar.writestr("META-INF/neoforge.mods.toml",
                         '[[mods]]\nmodId = "' + mod_id + '"\nversion = "' + version + '"\n')
            if manifest:
                jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nImplementation-Version: 1.0\r\n\r\n")
        return buffer.getvalue()

    def maven_mod(self, data):
        return dict(self.mod, curseforge_project_id=123, curseforge_file_id=456,
                    source_reference="https://www.curseforge.com/minecraft/mc-mods/example/files/456",
                    curseforge_maven={
                        "url": "https://cursemaven.com/curse/maven/example-123/456/example-123-456.jar",
                        "sha1": hashlib.sha1(data).hexdigest(), "mod_id": "example", "version": "1.0",
                        "game_versions": ["1.21.1"], "loaders": ["neoforge"],
                    })

    def test_maven_download_is_verified_and_hashed_from_actual_jar(self):
        for manifest in (False, True):
            with self.subTest(manifest=manifest):
                data = self.maven_fixture(version=("$" + "{file.jarVersion}") if manifest else "1.0", manifest=manifest)
                mod = self.maven_mod(data)
                result = importer.from_maven_download(mod, data, "1.21.1")
                self.assertEqual(result["hash"], hashlib.sha512(data).hexdigest())
                self.assertEqual(result["verification"]["version"], "1.0")
                self.assertEqual(result["version_id"], 456)
                self.assertIn("[update.curseforge]", importer.metadata(mod, result))

    def test_maven_rejects_changed_bytes_wrong_mod_wrong_version_and_html(self):
        good = self.maven_fixture()
        cases = [
            (self.maven_mod(good), good + b"changed", "checksum"),
            (self.maven_mod(self.maven_fixture(mod_id="unrelated")), self.maven_fixture(mod_id="unrelated"), "mod ID"),
            (self.maven_mod(self.maven_fixture(version="2.0")), self.maven_fixture(version="2.0"), "mod version"),
            (self.maven_mod(b"<html>error</html>"), b"<html>error</html>", "Invalid NeoForge JAR"),
        ]
        for mod, data, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(importer.ResolutionError, error):
                importer.from_maven_download(mod, data, "1.21.1")

    def test_binary_download_preserves_offline_mode(self):
        with patch.object(importer, "urlopen", side_effect=AssertionError("network called")):
            with self.assertRaisesRegex(importer.ResolutionError, "online run"):
                importer.API(self.root / ".cache", offline=True).download("https://cursemaven.com/example.jar")

    def test_latest_loader_filters_other_minecraft_versions_and_beta_and_sorts_numerically(self):
        api = Mock(offline=False)
        api.get.side_effect = [{"versions": ["21.1.99", "21.2.500", "21.1.253-beta", "21.1.219", "21.1.250", "26.1.1"]}, {}]
        self.assertEqual(importer.select_neoforge(api, "latest", "21.1.219"), "21.1.250")
        self.assertEqual(api.get.call_args_list[0].kwargs, {"fresh": True})
        self.assertIn("21.1.250-moddev-config.json", api.get.call_args_list[1].args[0])

    def test_latest_loader_rejects_offline_mode_or_missing_stable_releases(self):
        offline_api = Mock(offline=True)
        with self.assertRaisesRegex(importer.ResolutionError, "online run"):
            importer.select_neoforge(offline_api, "latest")
        offline_api.get.assert_not_called()
        api = Mock(offline=False)
        api.get.return_value = {"versions": ["21.1.300-beta", "21.2.1"]}
        with self.assertRaisesRegex(importer.ResolutionError, "no stable"):
            importer.select_neoforge(api, "latest")

    def test_loader_rejects_versions_below_the_known_mod_requirement(self):
        api = Mock(offline=False)
        with self.assertRaisesRegex(importer.ResolutionError, "21.1.219 or newer"):
            importer.select_neoforge(api, "21.1.218", "21.1.219")
        api.get.assert_not_called()
        self.assertEqual(importer.select_neoforge(Mock(offline=True), "21.1.219", "21.1.219"), "21.1.219")

    def test_fresh_metadata_lookup_does_not_reuse_an_old_cached_response(self):
        url = "https://example.com/versions"
        api = importer.API(self.root / ".cache")
        importer.write_json(api.cache / (importer.digest(url.encode()) + ".json"), {"versions": ["21.1.219"]})
        response = BytesIO(b'{"versions": ["21.1.250"]}')
        response.url = url
        with patch.object(importer, "urlopen", return_value=response) as download:
            self.assertEqual(api.get(url, fresh=True), {"versions": ["21.1.250"]})
            download.assert_called_once()

    def certificate_failure(self):
        return importer.URLError(importer.ssl.SSLCertVerificationError(1, "certificate has expired"))

    def test_neoforge_certificate_failure_retries_windows_validation_and_caches_success(self):
        url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        api = importer.API(self.root / ".cache")
        responses = [Mock(returncode=0, stdout=b"curl Schannel", stderr=b""),
                     Mock(returncode=0, stdout=b'{"versions":["21.1.250"]}', stderr=b"")]
        with patch.object(importer.sys, "platform", "win32"), \
                patch.object(importer.Path, "is_file", return_value=True), \
                patch.object(importer, "urlopen", side_effect=self.certificate_failure()), \
                patch.object(importer.subprocess, "run", side_effect=responses) as native, redirect_stderr(StringIO()):
            self.assertEqual(api.get(url), {"versions": ["21.1.250"]})
        args = native.call_args.args[0]
        self.assertEqual(args[1], "--disable")
        self.assertEqual(args[args.index("--proto") + 1], "=https")
        self.assertEqual(args[args.index("--proto-redir") + 1], "=https")
        for unsafe in ("--insecure", "-k", "--ssl-no-revoke", "--proxy-insecure"):
            self.assertNotIn(unsafe, args)
        self.assertNotIn("shell", native.call_args.kwargs)
        self.assertEqual(importer.read_json(api.cache / (importer.digest(url.encode()) + ".json")), {"versions": ["21.1.250"]})

    def test_windows_rejection_and_bad_responses_are_not_cached(self):
        url = "https://maven.neoforged.net/example.json"
        api = importer.API(self.root / ".cache")
        for response in (Mock(returncode=60, stdout=b"", stderr=b"certificate expired"),
                         Mock(returncode=22, stdout=b"", stderr=b"HTTP 404"),
                         Mock(returncode=0, stdout=b"<html>error</html>", stderr=b"")):
            with self.subTest(code=response.returncode), \
                    patch.object(importer.sys, "platform", "win32"), \
                    patch.object(importer.Path, "is_file", return_value=True), \
                    patch.object(importer, "urlopen", side_effect=self.certificate_failure()), \
                    patch.object(importer.subprocess, "run", side_effect=[Mock(returncode=0, stdout=b"curl Schannel"), response]), \
                    redirect_stderr(StringIO()):
                with self.assertRaises(importer.ResolutionError):
                    api.get(url)
            self.assertFalse((api.cache / (importer.digest(url.encode()) + ".json")).exists())

    def test_windows_retry_requires_native_schannel_backend(self):
        with patch.object(importer.sys, "platform", "win32"), \
                patch.object(importer.Path, "is_file", return_value=True), \
                patch.object(importer.subprocess, "run", return_value=Mock(returncode=0, stdout=b"curl OpenSSL")) as native:
            with self.assertRaisesRegex(importer.ResolutionError, "Schannel"):
                importer.windows_neoforge_json("https://maven.neoforged.net/example.json")
        self.assertEqual(native.call_count, 1)

    def test_certificate_retry_does_not_handle_network_denials_or_other_hosts(self):
        cases = [
            ("https://maven.neoforged.net/example.json", importer.URLError(PermissionError("network denied")), "win32"),
            ("https://api.modrinth.com/v2/project/example", self.certificate_failure(), "win32"),
            ("https://maven.neoforged.net/example.json", self.certificate_failure(), "linux"),
        ]
        for url, error, platform in cases:
            with self.subTest(url=url, platform=platform), \
                    patch.object(importer.sys, "platform", platform), \
                    patch.object(importer, "urlopen", side_effect=error), \
                    patch.object(importer, "windows_neoforge_json") as retry:
                with self.assertRaises(importer.ResolutionError):
                    importer.API(self.root / ".cache").get(url)
                retry.assert_not_called()

    def test_post_lookups_send_json_and_cache_per_body(self):
        api = importer.API(self.root / ".cache")
        sent = []

        def fake_urlopen(request, timeout):
            sent.append(json.loads(request.data))
            response = BytesIO(json.dumps({"n": len(sent)}).encode())
            response.url = request.full_url
            return response
        with patch.object(importer, "urlopen", side_effect=fake_urlopen):
            first = api.get("https://api.modrinth.com/v2/version_files", body={"hashes": ["a"]})
            again = api.get("https://api.modrinth.com/v2/version_files", body={"hashes": ["a"]})
            other = api.get("https://api.modrinth.com/v2/version_files", body={"hashes": ["b"]})
        self.assertEqual((first, again, other), ({"n": 1}, {"n": 1}, {"n": 2}))
        self.assertEqual(sent, [{"hashes": ["a"]}, {"hashes": ["b"]}])


SHA_A, SHA_B = "a" * 40, "b" * 40
BUNDLED_JAR = b"bundled jar bytes"
SHA_BUNDLED = hashlib.sha1(BUNDLED_JAR).hexdigest()
EXTRA = {"filename": "extra-1.0.jar", "name": "Extra", "slug": "extra", "side": "both"}


def extra_record(filename="extra-1.0.jar", project="PX", provider="modrinth"):
    return {"filename": filename, "name": "Extra", "side": "both", "provider": provider, "project_id": project,
            "version_id": "VX", "url": f"https://cdn.modrinth.com/data/{project}/versions/VX/{filename}",
            "hash_format": "sha512", "hash": "e" * 128, "game_versions": ["1.21.1"], "loaders": ["neoforge"]}


class FakeAPI:
    """Answers the Modrinth hash lookup (and, for the API key route, the CurseForge lookups)."""

    def __init__(self):
        self.projects = {1: {"id": 1, "slug": "alpha", "name": "Alpha", "classId": 6},
                         2: {"id": 2, "slug": "beta", "name": "Beta", "classId": 6},
                         3: {"id": 3, "slug": "shiny", "name": "Shiny", "classId": 12},
                         999: {"id": 999, "slug": "craftoria", "name": "Craftoria"}}
        self.files = {
            11: {"id": 11, "modId": 1, "fileName": "alpha-1.0.jar", "hashes": [{"algo": 1, "value": SHA_A}]},
            22: {"id": 22, "modId": 2, "fileName": "beta-1.0.jar", "hashes": [{"algo": 1, "value": SHA_B}]},
            33: {"id": 33, "modId": 3, "fileName": "shiny.zip", "hashes": [{"algo": 1, "value": "d" * 40}]},
        }
        self.export_files = []

    def get(self, url, curseforge=False, fresh=False, body=None):
        if url == f"{importer.MR}/version_files":
            known = {SHA_A: "PA", SHA_BUNDLED: "PJ"}
            return {h: {"id": "V" + known[h], "project_id": known[h]} for h in body["hashes"] if h in known}
        if url == f"{importer.CF}/mods":
            return {"data": [self.projects[i] for i in body["modIds"] if i in self.projects]}
        if url == f"{importer.CF}/mods/files":
            return {"data": [self.files[i] for i in body["fileIds"] if i in self.files]}
        if url == f"{importer.CF}/mods/999":
            return {"data": self.projects[999]}
        if url.startswith(f"{importer.CF}/mods/999/files?"):
            return {"data": self.export_files}
        raise importer.ResolutionError(f"unexpected lookup {url}")


class ModrinthOnlyAPI(FakeAPI):
    """The profile route must not call the CurseForge API."""

    def get(self, url, curseforge=False, fresh=False, body=None):
        if curseforge or url.startswith(importer.CF):
            raise AssertionError("CurseForge API called")
        return super().get(url, curseforge, fresh, body)


class AddonPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "sources").mkdir()
        self.settings = copy.deepcopy(craftoria.DEFAULT_SETTINGS)
        self.settings["base"]["curseforge_project_id"] = 999
        self.save_settings()
        self.downloads = {}
        self.api = ModrinthOnlyAPI()

    def save_settings(self):
        importer.write_json(self.root / "sources/pack.json", self.settings)

    def export_zip(self, version="1.0.0", files=(11, 22, 33), overrides=None):
        overrides = {"config/alpha.toml": b"a = 1\n", "mods/bundled.jar": BUNDLED_JAR} if overrides is None else overrides
        buffer = BytesIO()
        projects = {11: 1, 22: 2, 33: 3}
        with ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps({
                "manifestType": "minecraftModpack", "name": "Craftoria", "version": version, "overrides": "overrides",
                "minecraft": {"version": "1.21.1", "modLoaders": [{"id": "neoforge-21.1.200", "primary": True}]},
                "files": [{"projectID": projects[f], "fileID": f, "required": True} for f in files],
            }))
            for relative, data in overrides.items():
                archive.writestr("overrides/" + relative, data)
        return buffer.getvalue()

    def make_profile(self, name="Craftoria", modpack_id=999, minecraft="1.21.1", files=(11, 22, 33), blocked=(),
                     age=0, version="1.0.0", file_id=5000):
        data = self.export_zip(version, files)
        source = FakeAPI()
        addons = []
        for f in files:
            file, project = source.files[f], source.projects[source.files[f]["modId"]]
            addons.append({
                "addonID": project["id"], "name": project["name"], "categoryClassID": project["classId"],
                "webSiteURL": f"https://www.curseforge.com/minecraft/mc-mods/{project['slug']}",
                "allowModDistribution": f not in blocked,
                "installedFile": {"id": f, "fileName": file["fileName"], "downloadUrl": "https://edge.forgecdn.net/x",
                                  "hashes": [{"type": 1, "value": file["hashes"][0]["value"]}]},
            })
        folder = self.root / "Instances" / name
        folder.mkdir(parents=True, exist_ok=True)
        url = f"https://edge.forgecdn.net/files/5/0/{name}-{version}.zip"
        stamp = folder / "minecraftinstance.json"
        stamp.write_text(json.dumps({
            "name": name, "gameVersion": minecraft, "baseModLoader": {"name": "neoforge-21.1.200"},
            "installedModpack": {"addonID": modpack_id, "name": "Craftoria" if modpack_id == 999 else "Other",
                                 "installedFile": {"id": file_id, "fileName": f"Craftoria-{version}.zip",
                                                   "downloadUrl": url,
                                                   "hashes": [{"type": 1, "value": hashlib.sha1(data).hexdigest()}]}},
            "installedAddons": addons,
        }), encoding="utf-8")
        if age:
            os.utime(stamp, (stamp.stat().st_mtime - age,) * 2)
        self.downloads[url] = data
        return folder

    def run_import(self, *args):
        def fake_urlopen(request, timeout):
            response = BytesIO(self.downloads[request.full_url])
            response.url = request.full_url
            response.__enter__ = lambda: response
            return response
        with patch.object(craftoria, "API", return_value=self.api), \
                patch.object(craftoria, "select_neoforge", side_effect=lambda api, version: version), \
                patch.object(craftoria, "urlopen", side_effect=fake_urlopen), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return craftoria.main([str(a) for a in args], root=self.root)

    def add_extra(self, mod=EXTRA, record=None):
        self.settings["extras"].append(dict(mod))
        self.save_settings()
        overrides = importer.read_json(self.root / "sources/overrides.json", {})
        overrides[mod["filename"]] = record or extra_record(mod["filename"])
        importer.write_json(self.root / "sources/overrides.json", overrides)

    def add_local(self, relative, data=b"a = 2\n"):
        path = self.root / "sources/local-overrides" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def index(self):
        return {f["file"]: f for f in tomllib.loads((self.root / "index.toml").read_text(encoding="utf-8"))["files"]}

    def test_pack_holds_only_extras_and_config_changes(self):
        self.add_extra()
        self.add_local("config/alpha.toml")
        self.add_local("options.txt", b"fov:70\n")
        # Craftoria's blocked files are CurseForge's business now: they do not stop the build.
        folder = self.make_profile(blocked={22})
        self.assertEqual(self.run_import("--profile", folder), 0)
        self.assertEqual(sorted(self.index()), ["config/alpha.toml", "mods/extra.pw.toml", "options.txt"])
        self.assertTrue(self.index()["options.txt"].get("preserve"))
        self.assertFalse((self.root / "mods/alpha.pw.toml").exists())
        result = validate(self.root)
        self.assertEqual((result["mods"], result["neoforge"]), (1, "21.1.200"))
        pack = (self.root / "pack.toml").read_text()
        self.assertIn('version = "1.0.0-1"', pack)
        self.assertIn("Add-on for Craftoria 1.0.0 (CurseForge modpack 999, file 5000)", pack)
        lock = importer.read_json(self.root / "sources/lock.json")
        self.assertEqual(lock["base"]["source"], "profile")
        by_name = {f["name"]: f for f in lock["base"]["files"]}
        self.assertEqual(by_name["Alpha"]["modrinth_project_id"], "PA")
        self.assertEqual(by_name["Shiny"]["path"], "resourcepacks/shiny.zip")
        self.assertEqual(by_name["bundled.jar"]["modrinth_project_id"], "PJ")
        # A second import reuses the cached export instead of downloading it again.
        self.downloads.clear()
        self.assertEqual(self.run_import("--profile", folder), 0)

    def test_extras_the_base_pack_already_has_are_rejected(self):
        cases = {
            "Modrinth copy of a base mod": (dict(EXTRA), extra_record(project="PA")),
            "CurseForge base mod": (dict(EXTRA), extra_record(project="2", provider="curseforge")),
            "mod bundled in the overrides": (dict(EXTRA), extra_record(project="PJ")),
            "same file name as a base mod": (dict(EXTRA, filename="alpha-1.0.jar"), extra_record("alpha-1.0.jar")),
            "same file name as a bundled jar": (dict(EXTRA, filename="bundled.jar"), extra_record("bundled.jar")),
        }
        folder = self.make_profile()
        for name, (mod, record) in cases.items():
            with self.subTest(case=name):
                self.settings["extras"] = []
                importer.write_json(self.root / "sources/overrides.json", {})
                self.add_extra(mod, record)
                with self.assertRaisesRegex(importer.ResolutionError, "already includes|would replace"):
                    self.run_import("--profile", folder)
                self.assertFalse((self.root / "pack.toml").exists())

    def test_local_overrides_may_change_configs_but_not_base_mods(self):
        folder = self.make_profile()
        jar = self.add_local("mods/alpha-1.0.jar", b"jar")
        with self.assertRaisesRegex(importer.ResolutionError, "would replace"):
            self.run_import("--profile", folder)
        jar.unlink()
        for relative in ("scripts/evil.py", "pack.toml"):
            with self.subTest(path=relative):
                local = self.add_local(relative, b"x")
                with self.assertRaises(importer.ResolutionError):
                    self.run_import("--profile", folder)
                local.unlink()

    def test_base_update_keeps_extras_and_drops_removed_overrides(self):
        self.add_extra()
        old = self.add_local("config/old.toml")
        self.assertEqual(self.run_import("--profile", self.make_profile()), 0)
        old.unlink()
        self.add_local("config/alpha.toml")
        folder = self.make_profile(version="1.1.0", file_id=5001, files=(11, 33))
        self.assertEqual(self.run_import("--profile", folder), 0)
        self.assertFalse((self.root / "config/old.toml").exists())
        self.assertEqual((self.root / "config/alpha.toml").read_bytes(), b"a = 2\n")
        self.assertTrue((self.root / "mods/extra.pw.toml").exists())
        self.assertIn("Craftoria 1.1.0 (CurseForge modpack 999, file 5001)", (self.root / "pack.toml").read_text())
        validate(self.root)

    def test_rebuild_needs_no_profile_and_refuses_hand_edits(self):
        self.add_local("config/alpha.toml")
        self.assertEqual(self.run_import("--profile", self.make_profile()), 0)
        self.api = Mock(get=Mock(side_effect=AssertionError("no lookups on rebuild")))
        self.assertEqual(self.run_import("--rebuild"), 0)
        (self.root / "config/alpha.toml").write_bytes(b"edited\n")
        with self.assertRaisesRegex(importer.ResolutionError, "edited by hand"):
            self.run_import("--rebuild")
        self.assertEqual(self.run_import("--rebuild", "--force"), 0)
        self.assertEqual((self.root / "config/alpha.toml").read_bytes(), b"a = 2\n")

    def test_remove_setting_is_rejected(self):
        self.settings["remove"] = ["beta"]
        self.save_settings()
        with self.assertRaisesRegex(importer.ResolutionError, "not supported"):
            self.run_import("--profile", self.make_profile())

    def test_api_key_route_reads_the_release_from_curseforge(self):
        self.api = FakeAPI()
        data = self.export_zip()
        self.downloads["https://edge.forgecdn.net/files/5/0/c.zip"] = data
        self.api.export_files = [{"id": 5000, "fileName": "Craftoria-1.0.0.zip", "releaseType": 1,
                                  "fileDate": "2026-01-01", "downloadUrl": "https://edge.forgecdn.net/files/5/0/c.zip",
                                  "hashes": [{"algo": 1, "value": hashlib.sha1(data).hexdigest()}]}]
        self.assertEqual(self.run_import("--latest"), 0)
        self.assertIn("(CurseForge modpack 999, file 5000)", (self.root / "pack.toml").read_text())
        self.assertEqual(importer.read_json(self.root / "sources/lock.json")["base"]["source"], "api")

    def test_tampered_files_index_or_base_fail_validation(self):
        self.add_extra()
        self.add_local("options.txt", b"fov:70\n")
        self.assertEqual(self.run_import("--profile", self.make_profile()), 0)
        for path in ("mods/extra.pw.toml", "index.toml"):
            with self.subTest(path=path):
                target = self.root / path
                original = target.read_bytes()
                target.write_bytes(original + b"\n# tampered\n")
                with self.assertRaisesRegex(importer.ResolutionError, "Checksum mismatch"):
                    validate(self.root)
                target.write_bytes(original)
        index = (self.root / "index.toml").read_text()
        pack = (self.root / "pack.toml").read_text()
        (self.root / "config").mkdir()
        (self.root / "config/extra.toml").write_bytes(b"x\n")
        extra_hash = hashlib.sha256(b"x\n").hexdigest()
        cases = {"preserve": (index.replace("preserve = true", 'preserve = "yes"'), pack),
                 "did not generate": (index + f'\n[[files]]\nfile = "config/extra.toml"\nhash = "{extra_hash}"\n', pack),
                 "base modpack": (index, pack.replace("file 5000", "file 4999"))}
        for expected, (index_text, pack_text) in cases.items():
            with self.subTest(case=expected):
                new_hash = hashlib.sha256(index_text.encode()).hexdigest()
                (self.root / "index.toml").write_text(index_text, newline="\n")
                (self.root / "pack.toml").write_text(re.sub(r'(?m)^hash = ".*"$', f'hash = "{new_hash}"', pack_text),
                                                     newline="\n")
                with self.assertRaisesRegex(importer.ResolutionError, expected):
                    validate(self.root)

    def test_publish_stages_only_indexed_files_and_sets_sync_url(self):
        self.add_extra()
        self.add_local("config/alpha.toml")
        self.assertEqual(self.run_import("--profile", self.make_profile()), 0)
        (self.root / "client/visuals").mkdir(parents=True)
        (self.root / "client/sync-mods.cmd").write_text('set "PACKWIZ_SYNC_URL=https://YOUR-USERNAME.github.io/YOUR-REPO/pack.toml"\n')
        (self.root / "client/visuals/scene.frames.gz").write_bytes(b"frames")
        (self.root / "client/visuals/scene-blocks.frames.gz").write_bytes(b"blocks")
        (self.root / "client/visuals/LICENSE-ascii.rest").write_text("MIT")
        pack_url = stage(self.root, self.root / "dist", "https://example.github.io/pack")
        self.assertEqual(pack_url, "https://example.github.io/pack/pack.toml")
        self.assertFalse((self.root / "dist/sources").exists())
        self.assertIn(pack_url, (self.root / "dist/sync-mods.cmd").read_text())
        for path in ("mods/extra.pw.toml", "config/alpha.toml", "pack.toml", "index.toml"):
            self.assertTrue((self.root / "dist" / path).exists(), path)
        self.assertEqual((self.root / "dist/installer/scene.frames.gz").read_bytes(), b"frames")
        self.assertTrue((self.root / "dist/installer/LICENSE-ascii.rest.txt").exists())
        home = (self.root / "dist/index.html").read_text(encoding="utf-8")
        self.assertIn('href="sync-mods.cmd"', home)
        self.assertIn("Extra mods (1)", home)

    def test_publish_refuses_incomplete_pack(self):
        with self.assertRaises(importer.ResolutionError):
            stage(self.root, self.root / "dist", "https://example.github.io/pack")
        self.assertFalse((self.root / "dist").exists())

    def test_default_run_finds_the_newest_base_modpack_profile(self):
        self.make_profile(name="Old Craftoria", age=3600)
        self.make_profile(name="Craftoria Fresh")
        self.make_profile(name="ATM10", modpack_id=123)
        self.make_profile(name="Craftoria Legacy", minecraft="1.20.1")
        found = craftoria.find_profiles(self.root / "Instances", craftoria.load_settings(self.root))
        self.assertEqual([p["name"] for p in found], ["Craftoria Fresh", "Old Craftoria"])
        self.assertEqual(self.run_import("--instances", self.root / "Instances", "--yes"), 0)
        validate(self.root)

    def test_prompt_confirms_the_suggestion_or_picks_another(self):
        profiles = [{"name": n, "folder": Path(n), "loader": "neoforge-21.1.200", "export": {"fileName": n + ".zip"}}
                    for n in ("Newest", "Older")]
        quiet = lambda *a: None
        for answers, expected in (([""], "Newest"), (["y"], "Newest"), (["2"], "Older"),
                                  (["7", "maybe", "2"], "Older"), (["q"], None)):
            with self.subTest(answers=answers):
                replies = iter(answers)
                chosen = craftoria.choose_profile(profiles, read=lambda prompt: next(replies), write=quiet)
                self.assertEqual(chosen and chosen["name"], expected)
        self.assertEqual(craftoria.choose_profile(profiles, assume_yes=True)["name"], "Newest")
        self.assertIsNone(craftoria.choose_profile([]))


if __name__ == "__main__":
    unittest.main()
