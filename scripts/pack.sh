#!/usr/bin/env bash
# Pack the checkout, including new source files, without consulting a Git ref.
set -eu
if [[ $# != 2 || $1 != --output || $2 != /* ]]; then
  printf 'Aufruf: bash scripts/pack.sh --output /absoluter/pfad/kienzlefon.tar.gz\n' >&2
  exit 2
fi
cd -P -- "$(dirname -- "$0")/.."
exec python3 - "$2" <<'PY'
import io
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path

root = Path.cwd()
output = Path(sys.argv[1])
inventory = Path("scripts/package-files.txt")
files = {Path(line) for line in inventory.read_text().splitlines()}

# Additional source files may be untracked. Only visit program directories
# and template formats. Runtime trees and arbitrary JSON/TOML are never inputs.
def add_sources(directory, patterns):
    for pattern in patterns:
        for path in directory.glob(pattern):
            if not path.is_file() or path.resolve() != root / path:
                continue
            words = re.split(r"[._-]", path.name.lower())
            if path.name.startswith(".") or any(word in {
                "local", "secret", "secrets", "credential", "credentials", "password",
            } for word in words):
                continue
            if directory.parts[0] == "webinterface" and words[0] in {"config", "settings"}:
                continue
            files.add(path)

def add_modules(directory):
    add_sources(directory, ["*.py"])
    for child in directory.iterdir():
        if (child.name.isidentifier() and not child.is_symlink()
                and (child / "__init__.py").is_file()):
            add_modules(child)

add_modules(Path("kienzlefon"))
add_sources(Path("webinterface"), ["*.php", "*.js", "*.css"])
add_sources(Path("webinterface/assets"), ["*.js", "*.css", "*.svg", "*.png", "*.woff2"])
add_sources(Path("scripts"), ["*.sh", "*.py"])
add_sources(Path("scripts/kokoro"), ["*.py", "*.sh"])
add_sources(Path("config"), ["*.example", "*.example.json", "*.example.toml"])
# These templates belong to the separate Telepraxis SMS demo and its worker.
files.difference_update({Path("config/sms-queue-web.example.json"),
                         Path("config/sms-queue-worker.example.json")})

for path in sorted(files):
    if (path.is_absolute() or path.resolve() != root / path or not path.is_file()
            or (path.stat().st_size == 0 and path.name != "__init__.py")
            or "\n" in str(path) or "\r" in str(path)):
        sys.exit(f"Paketbestandteil fehlt oder ist ungueltig: {path}")
if output.resolve() in {root / path for path in files}:
    sys.exit("Das Ausgabearchiv wuerde einen Paketbestandteil ueberschreiben.")

# Freeze the actual file list in the bundle for preflight on the target.
listing = "".join(f"{path}\n" for path in sorted(files)).encode()
with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".kienzlefon-", delete=False) as tmp:
    staged = Path(tmp.name)
try:
    with tarfile.open(staged, "w:gz", dereference=True) as archive:
        top = tarfile.TarInfo("kienzlefon")
        top.type = tarfile.DIRTYPE
        top.mode = 0o755
        archive.addfile(top)
        for path in sorted(files):
            member = archive.gettarinfo(str(path), arcname=f"kienzlefon/{path}")
            member.uid = member.gid = 0
            member.uname = member.gname = "root"
            member.mode = 0o755 if member.mode & 0o111 else 0o644
            if path == inventory:
                member.size = len(listing)
                archive.addfile(member, io.BytesIO(listing))
            else:
                with path.open("rb") as stream:
                    archive.addfile(member, stream)
    os.replace(staged, output)
finally:
    if staged.exists():
        staged.unlink()
print(f"Kienzlefon-Paket erstellt: {output} ({len(files)} Dateien)")
PY
