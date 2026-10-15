#!/usr/bin/env python3
"""Create a Pages artifact containing only verified pack files and the client updater."""
import argparse
from pathlib import Path
import shutil
import tomllib
from urllib.parse import urlparse

from import_pack import ROOT, ResolutionError, https_url
from validate_pack import inside, validate


def stage(root, output, base_url):
    validate(root)
    https_url(base_url)
    uri = urlparse(base_url)
    if uri.query or uri.fragment:
        raise ResolutionError("Use a site base URL without a query or fragment")
    # This is build output, never a source directory or arbitrary external path.
    output = output.resolve()
    if output != (root / "dist").resolve():
        raise ResolutionError("The publishing directory must be this project's dist/")
    if output.exists() and any(output.iterdir()):
        raise ResolutionError("dist/ is not empty. Use a fresh checkout for publishing.")
    output.mkdir(parents=True, exist_ok=True)
    pack = tomllib.loads((root / "pack.toml").read_text(encoding="utf-8"))
    index_name = pack["index"]["file"]
    index = tomllib.loads(inside(root, index_name).read_text(encoding="utf-8"))
    for relative in ["pack.toml", index_name] + [f["file"] for f in index.get("files", [])]:
        source, destination = inside(root, relative), inside(output, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    script = (root / "client/sync-mods.cmd").read_text(encoding="utf-8")
    pack_url = base_url.rstrip("/") + "/pack.toml"
    # Avoid cmd.exe metacharacters, percent expansion and line injection in the assignment.
    if any(c in pack_url for c in '\r\n"%!^&|<>'):
        raise ResolutionError("Site URL contains characters unsafe for the batch updater")
    script = script.replace("https://YOUR-USERNAME.github.io/YOUR-REPO/pack.toml", pack_url)
    (output / "sync-mods.cmd").write_bytes(script.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return pack_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="For example https://USER.github.io/REPO")
    args = parser.parse_args()
    try:
        print(stage(ROOT, ROOT / "dist", args.base_url))
    except (ResolutionError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Staging failed: {exc}\n")
