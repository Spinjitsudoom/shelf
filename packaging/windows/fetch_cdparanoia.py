"""Download cd-paranoia for Windows into a folder (default: dist/Shelf Server/cdparanoia).

Shelf rips CDs with cd-paranoia (libcdio's port of cdparanoia, which re-reads scratched spots
until it gets them right). Linux has it as a package; for Windows this takes MSYS2's UCRT64
build: the libcdio-paranoia package and the packages it needs, resolved from the repository's
index. Only the DLLs cd-paranoia.exe actually loads are kept (found by reading their import
tables), with the licences of the packages they come from and a README saying where each
package's source is.

    python packaging/windows/fetch_cdparanoia.py [dest]
"""

from __future__ import annotations

import io
import re
import struct
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "https://repo.msys2.org/mingw/ucrt64/"
SOURCES = "https://repo.msys2.org/mingw/sources/"
PREFIX = "mingw-w64-ucrt-x86_64-"
WANT = PREFIX + "libcdio-paranoia"
PROGRAM = "cd-paranoia.exe"
# Supplied by Windows itself (the Universal C Runtime), never by a package.
BUILT_IN = {PREFIX + "crt", PREFIX + "crt-git"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "shelf-build"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def _index() -> dict[str, dict[str, list[str]]]:
    """The repository's packages: name -> {FILENAME: [...], DEPENDS: [...], ...}."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(_get(REPO + "ucrt64.db"))) as t:
        for m in t.getmembers():
            if m.name.endswith("/desc"):
                desc = t.extractfile(m).read().decode()
                fields = {k: v.strip().split("\n") for k, v in re.findall(r"%(\w+)%\n(.*?)(?:\n\n|\Z)", desc, re.S)}
                out[fields["NAME"][0]] = fields
                for p in fields.get("PROVIDES", []):
                    out.setdefault(re.split(r"[<>=]", p)[0], fields)
    return out


def needed(index: dict, name: str = WANT) -> list[dict]:
    """The package and everything it depends on, each once."""
    todo, seen, out = [name], set(), []
    while todo:
        n = re.split(r"[<>=]", todo.pop())[0]
        if n in seen or n in BUILT_IN:
            continue
        seen.add(n)
        pkg = index.get(n)
        if pkg is None:
            sys.exit(f"{n} isn't in the MSYS2 repository")
        out.append(pkg)
        todo += pkg.get("DEPENDS", [])
    return out


def pe_imports(data: bytes) -> list[str]:
    """The DLLs a Windows program or DLL loads, from its import table."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    dirs = opt + (112 if struct.unpack_from("<H", data, opt)[0] == 0x20B else 96)
    table_rva = struct.unpack_from("<I", data, dirs + 8)[0]
    if not table_rva:
        return []

    def offset(rva: int) -> int:
        for i in range(sections):
            s = opt + opt_size + 40 * i
            size, va, raw = struct.unpack_from("<I", data, s + 8)[0], struct.unpack_from("<I", data, s + 12)[0], struct.unpack_from("<I", data, s + 20)[0]
            if va <= rva < va + max(size, 1):
                return rva - va + raw
        raise ValueError("import table outside the file's sections")

    out, o = [], offset(table_rva)
    while (name_rva := struct.unpack_from("<I", data, o + 12)[0]):
        n = offset(name_rva)
        out.append(data[n:data.index(b"\0", n)].decode())
        o += 20
    return out


def main() -> None:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Shelf Server/cdparanoia")
    dest.mkdir(parents=True, exist_ok=True)
    files: dict[str, tuple[bytes, str]] = {}  # bin/ file name (lowercase) -> (bytes, package)
    licences: dict[str, dict[str, bytes]] = {}
    packages = {}
    for pkg in needed(_index()):
        name = pkg["NAME"][0]
        packages[name] = pkg
        print("Downloading", pkg["FILENAME"][0])
        with tarfile.open(fileobj=io.BytesIO(_get(REPO + pkg["FILENAME"][0]))) as t:
            for m in t.getmembers():
                parts = m.name.split("/")
                if not m.isfile():
                    continue
                if parts[1:2] == ["bin"] and (parts[-1].endswith(".dll") or parts[-1] == PROGRAM):
                    files[parts[-1].lower()] = (t.extractfile(m).read(), name)
                elif parts[1:3] == ["share", "licenses"]:
                    licences.setdefault(name, {})["/".join(parts[4:])] = t.extractfile(m).read()
    if PROGRAM not in files:
        sys.exit(f"The download didn't contain {PROGRAM}")

    # Keep the program and the DLLs it loads (and they load); Windows supplies the rest.
    keep, todo = {}, [PROGRAM]
    while todo:
        f = todo.pop().lower()
        if f in keep or f not in files:
            continue
        keep[f] = files[f]
        todo += pe_imports(files[f][0])
    used = {}
    for f, (data, pkg) in keep.items():
        (dest / f).write_bytes(data)
        used.setdefault(pkg, []).append(f)

    lines = [
        "cd-paranoia for Windows, as Shelf uses it to rip CDs.",
        "",
        "These programs come from the MSYS2 project's UCRT64 packages (https://www.msys2.org/),",
        "unchanged. libcdio and libcdio-paranoia are free software under the GNU General Public",
        "License, version 3 or later (https://www.gnu.org/licenses/gpl-3.0.html); libiconv is",
        "under the GNU LGPL; winpthreads under the MIT/BSD-style licence in licenses/. The source",
        "code of each package, exactly as built, is at the address given for it:",
        "",
    ]
    for name, fs in sorted(used.items()):
        pkg = packages[name]
        base, version = pkg.get("BASE", [name])[0], pkg["VERSION"][0]
        lines += [f"{name.removeprefix(PREFIX)} {version}: {', '.join(sorted(fs))}",
                  f"    source: {SOURCES}{base}-{version}.src.tar.zst",
                  f"    project: {pkg.get('URL', [''])[0]}"]
        for path, data in licences.get(name, {}).items():
            lic = dest / "licenses" / name.removeprefix(PREFIX) / path
            lic.parent.mkdir(parents=True, exist_ok=True)
            lic.write_bytes(data)
    (dest / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")
    print("cd-paranoia is in", dest, "with", ", ".join(sorted(keep)))


if __name__ == "__main__":
    main()
