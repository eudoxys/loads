"""Check that MANIFEST.md covers every tracked file

Usage: python .github/check_manifest.py [MANIFEST.md]

Reads the first column of every table in MANIFEST.md, takes each
backquoted path or glob (`*`, `?`, `**`), and compares them with
`git ls-files`. Reports tracked files no entry covers and entries that
match no file. Exits 1 if either list is non-empty.
"""

import re
import subprocess
import sys
from fnmatch import fnmatchcase

def entries(text:str) -> list[str]:
    """Paths/globs in the first column of the manifest tables"""
    result = []
    for line in text.splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*-+",line):
            continue
        first = line.split("|")[1]
        result.extend(x for x in re.findall(r"`([^`]+)`",first) if x != "Path")
    return result

def matches(pattern:str,path:str) -> bool:
    """Glob match where `*` stays within a folder and `**` crosses folders"""
    regex = re.escape(pattern).replace(r"\*\*/","(?:.*/)?").replace(r"\*\*",".*")
    regex = regex.replace(r"\*","[^/]*").replace(r"\?","[^/]")
    return re.fullmatch(regex,path) is not None or (pattern.endswith("/") and path.startswith(pattern))

def main(manifest:str="MANIFEST.md") -> int:
    """Run the check"""
    with open(manifest,encoding="utf-8") as fh:
        patterns = entries(fh.read())
    files = subprocess.run(["git","ls-files"],capture_output=True,text=True,check=True).stdout.split()
    uncovered = [f for f in files if not any(matches(p,f) for p in patterns)]
    unused = [p for p in patterns if not any(matches(p,f) for f in files)]
    for f in uncovered:
        print(f"not in manifest: {f}")
    for p in unused:
        print(f"matches no file: {p}")
    return 1 if uncovered or unused else 0

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
