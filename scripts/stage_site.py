#!/usr/bin/env python3
"""Create a Pages artifact containing only verified pack files and the client updater."""
import argparse
import html
from pathlib import Path
import shutil
import tomllib
from urllib.parse import urlparse

from import_pack import ROOT, ResolutionError, https_url, read_json
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
    # The updater's optional animation (ascii.rest "aurora fjord", MIT) and its licence.
    (output / "installer").mkdir()
    for name, published in [("scene.frames.gz",) * 2, ("scene-blocks.frames.gz",) * 2,
                           ("LICENSE-ascii.rest", "LICENSE-ascii.rest.txt")]:
        shutil.copyfile(root / "client/visuals" / name, output / "installer" / published)
    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "index.html").write_text(home_page(root, pack, index), encoding="utf-8", newline="\n")
    return pack_url


def mod_link(mod):
    """The extra's project page, from its packwiz update section."""
    update = mod.get("update", {})
    if "modrinth" in update:
        return f"https://modrinth.com/mod/{update['modrinth']['mod-id']}"
    if "curseforge" in update:
        return f"https://www.curseforge.com/projects/{update['curseforge']['project-id']}"
    return None


def home_page(root, pack, index):
    """A landing page with the install steps and the list of extras."""
    base = read_json(root / "sources/lock.json", {}).get("base", {})
    base_name = base.get("name", "the base modpack")
    mods = []
    for item in index.get("files", []):
        if item.get("metafile") and item["file"].startswith("mods/"):
            mods.append(tomllib.loads(inside(root, item["file"]).read_text(encoding="utf-8")))
    rows = []
    for mod in sorted(mods, key=lambda m: m["name"].casefold()):
        name, link = html.escape(mod["name"]), mod_link(mod)
        title = f'<a href="{html.escape(link)}">{name}</a>' if link else name
        rows.append(f"<li>{title}<span>{html.escape(mod['filename'])}</span></li>")
    mod_list = (f'<ul class="mods">{"".join(rows)}</ul>' if rows
                else '<p class="note">None yet: the pack only changes configs.</p>')
    e = html.escape
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(pack["name"])}</title>
<meta name="description" content="{e(pack.get("description", ""))}">
<style>
:root {{ --bg: #f6f7f9; --card: #ffffff; --text: #1d232b; --muted: #5d6773; --line: #dde2e8; --accent: #2f7d4f; --accent-text: #ffffff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #12161b; --card: #1b2128; --text: #e6eaef; --muted: #9aa5b1; --line: #2c343e; --accent: #4fb07a; --accent-text: #0d1a12; }} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 40px 16px 64px; }}
h1 {{ margin: 0 0 4px; font-size: 2rem; }}
h2 {{ margin: 0 0 12px; font-size: 1.15rem; }}
.sub {{ margin: 0 0 28px; color: var(--muted); }}
section {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
ol {{ margin: 0; padding-left: 1.3em; }} ol li {{ margin-bottom: 8px; }}
.button {{ display: inline-block; margin-top: 4px; padding: 10px 18px; border-radius: 8px; background: var(--accent); color: var(--accent-text); font-weight: 600; text-decoration: none; }}
a {{ color: var(--accent); }}
ul.mods {{ list-style: none; margin: 0; padding: 0; }}
ul.mods li {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px; padding: 8px 0; border-top: 1px solid var(--line); }}
ul.mods li:first-child {{ border-top: 0; }}
ul.mods span {{ color: var(--muted); font-size: 0.85rem; overflow-wrap: anywhere; }}
.note {{ color: var(--muted); font-size: 0.9rem; }}
</style>
</head>
<body>
<main>
<h1>{e(pack["name"])}</h1>
<p class="sub">Version {e(pack["version"])}: an add-on for {e(base_name)} {e(base.get("version", ""))}, Minecraft {e(pack["versions"]["minecraft"])}, NeoForge {e(pack["versions"]["neoforge"])}.</p>
<section>
<h2>Install</h2>
<ol>
<li>In the CurseForge app, install the modpack <strong>{e(base_name)}</strong> (Browse modpacks, search {e(base_name)}, Install).</li>
<li>Close Minecraft, then download and run the updater. If you have several {e(base_name)} profiles, it asks which one to use.<br>
<a class="button" href="sync-mods.cmd" download>Download sync-mods.cmd</a></li>
<li>Open CurseForge, pick the profile and press Play. Give Minecraft at least 8 GB of memory (CurseForge settings, Minecraft, Java Settings).</li>
</ol>
<p class="note">After {e(base_name)} updates in CurseForge, run the updater again. Windows may warn about a downloaded script: choose More info, then Run anyway.</p>
</section>
<section>
<h2>Extra mods ({len(rows)})</h2>
{mod_list}
</section>
</main>
</body>
</html>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="For example https://USER.github.io/REPO")
    args = parser.parse_args()
    try:
        print(stage(ROOT, ROOT / "dist", args.base_url))
    except (ResolutionError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Staging failed: {exc}\n")
