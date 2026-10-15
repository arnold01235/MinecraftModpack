import copy
import hashlib
from io import BytesIO, StringIO
from contextlib import redirect_stdout, redirect_stderr
from zipfile import ZipFile
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_pack as importer
from validate_pack import validate
from stage_site import stage


class ImportTests(unittest.TestCase):
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
        self.catalog = {
            "mods": [self.mod], "minecraft": "1.21.1", "loader": "neoforge",
            "name": "Test fixture", "version": "0.1", "disabled": ["disabled.jar.disabled"],
        }
        (self.root / "sources").mkdir()
        importer.write_json(self.root / "sources/mods.json", self.catalog)
        (self.root / "temp-modlist.txt").write_text(self.mod["filename"] + "\n# disabled.jar.disabled\n", encoding="utf-8")

    def build(self):
        importer.build(self.root, self.catalog, {self.mod["filename"]: self.record}, "21.1.219")

    def test_complete_pack_has_correct_hash_chain_and_exact_inventory(self):
        self.build()
        self.assertEqual(validate(self.root, exact=True)["mods"], 1)

    def test_unresolved_mod_does_not_create_consumable_pack(self):
        with self.assertRaises(importer.ResolutionError):
            importer.build(self.root, self.catalog, {}, "21.1.219")
        self.assertFalse((self.root / "pack.toml").exists())
        self.assertFalse((self.root / "mods").exists())

    def test_existing_pack_is_not_overwritten(self):
        self.build()
        original = (self.root / "pack.toml").read_bytes()
        with self.assertRaises(importer.ResolutionError):
            self.build()
        self.assertEqual((self.root / "pack.toml").read_bytes(), original)

    def test_tampered_metadata_fails(self):
        self.build()
        path = self.root / "mods/example.pw.toml"
        path.write_text(path.read_text() + "\n# tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(importer.ResolutionError, "Checksum mismatch"):
            validate(self.root)

    def test_tampered_index_fails(self):
        self.build()
        with (self.root / "index.toml").open("a") as file:
            file.write("\n# tampered")
        with self.assertRaisesRegex(importer.ResolutionError, "Checksum mismatch"):
            validate(self.root)

    def test_newer_version_is_rejected(self):
        newer = dict(self.record, filename="example-2.0-neoforge.jar")
        with self.assertRaisesRegex(importer.ResolutionError, "exactly match"):
            importer.validate_record(self.mod, newer, "1.21.1")

    def test_wrong_loader_and_wrong_game_are_rejected(self):
        for change in ({"loaders": ["forge"]}, {"game_versions": ["1.20.1"]}):
            with self.assertRaises(importer.ResolutionError):
                importer.validate_record(self.mod, dict(self.record, **change), "1.21.1")

    def test_disabled_mods_are_not_in_inventory(self):
        self.assertEqual(importer.inventory(self.root), [self.mod["filename"]])

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

    def test_maven_fallback_saves_record_when_both_metadata_apis_fail(self):
        data = self.maven_fixture()
        self.catalog["mods"] = [self.maven_mod(data)]
        importer.write_json(self.root / "sources/mods.json", self.catalog)
        with patch.object(importer, "ROOT", self.root), \
                patch.object(importer, "resolve_modrinth", side_effect=importer.ResolutionError("404")), \
                patch.object(importer, "resolve_curseforge", side_effect=importer.ResolutionError("No API key")), \
                patch.object(importer.API, "download", return_value=data), redirect_stdout(StringIO()):
            self.assertEqual(importer.main(["--resolve-only"]), 0)
        saved = importer.read_json(self.root / "sources/resolved.json")
        self.assertEqual(saved[self.mod["filename"]]["verification"]["method"], "downloaded-jar")
        self.assertEqual(importer.read_json(self.root / "sources/unresolved.json"), [])
        self.assertFalse((self.root / "pack.toml").exists())

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

    def test_tls_fallback_can_complete_loader_selection_and_pack_creation(self):
        importer.write_json(self.root / "sources/resolved.json", {self.mod["filename"]: self.record})
        with patch.object(importer, "ROOT", self.root), \
                patch.object(importer.sys, "platform", "win32"), \
                patch.object(importer, "urlopen", side_effect=self.certificate_failure()), \
                patch.object(importer, "windows_neoforge_json", side_effect=[{"versions": ["21.1.250", "21.2.1"]}, {}]), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(importer.main(["--neoforge", "latest"]), 0)
        self.assertEqual(validate(self.root, exact=True)["neoforge"], "21.1.250")

    def test_publish_stages_only_indexed_files_and_sets_sync_url(self):
        self.build()
        (self.root / "client").mkdir()
        (self.root / "client/sync-mods.cmd").write_text('set "PACKWIZ_SYNC_URL=https://YOUR-USERNAME.github.io/YOUR-REPO/pack.toml"\n')
        (self.root / "client/visuals").mkdir()
        (self.root / "client/visuals/snow-train.frames.gz").write_bytes(b"frames")
        (self.root / "client/visuals/LICENSE-ascii.rest").write_text("MIT")
        pack_url = stage(self.root, self.root / "dist", "https://example.github.io/pack")
        self.assertEqual(pack_url, "https://example.github.io/pack/pack.toml")
        self.assertFalse((self.root / "dist/sources").exists())
        self.assertFalse((self.root / "dist/temp-modlist.txt").exists())
        self.assertIn(pack_url, (self.root / "dist/sync-mods.cmd").read_text())
        self.assertTrue((self.root / "dist/mods/example.pw.toml").exists())
        self.assertEqual((self.root / "dist/installer/snow-train.frames.gz").read_bytes(), b"frames")
        self.assertTrue((self.root / "dist/installer/LICENSE-ascii.rest.txt").exists())

    def test_publish_refuses_incomplete_pack(self):
        with self.assertRaises(importer.ResolutionError):
            stage(self.root, self.root / "dist", "https://example.github.io/pack")
        self.assertFalse((self.root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
