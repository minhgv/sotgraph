#!/usr/bin/env python3
"""P4 native-source inventory walk. Read-only. Aggregates bytes by category,
prints exact top-10 largest worktree files and .git breakdown.
Usage: python3 native_inventory_walk.py <repo-root>"""
import hashlib, json, os, subprocess, sys

root = sys.argv[1]
GEN_NAMES = {"parser.c", "parser.h", "node-types.json", "grammar.json"}

def categorize(rel, name):
    # order matters; rel is POSIX relative path
    p = rel.lower()
    if p.endswith((".o", ".a", ".so", ".dylib")) or "/build/" in p or p.startswith("build/"):
        return "build_outputs"
    if name in GEN_NAMES and (
        "/grammars/" in p or "tree-sitter-" in p or "ts_runtime" in p
    ):
        return "generated_grammar_artifacts"
    if "/vendored/" in p or p.startswith("vendored/"):
        return "vendored_thirdparty_source"
    if p.startswith(".git/"):
        return "git_dir"
    ext = os.path.splitext(name)[1].lower()
    if ext in (".c", ".h"):
        return "handwritten_c_source"
    if ext == ".py":
        return "python_source"
    if ext in (".js", ".ts", ".tsx", ".jsx", ".css", ".html"):
        return "ui_web_source"
    if ext in (".md", ".txt", ".rst"):
        return "docs_text"
    if ext in (".json", ".toml", ".yml", ".yaml", ".nix", ".lock", ".mk") or name.startswith("Makefile") or name == "Makefile":
        return "config_build_meta"
    return "other_misc"

cats = {}
top = []
git_total = git_objs = 0
n_files = 0
for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        fp = os.path.join(dirpath, fn)
        rel = os.path.relpath(fp, root)
        try:
            st = os.lstat(fp)
        except OSError:
            continue
        sz = st.st_size
        n_files += 1
        if rel == ".git" or rel.startswith(".git" + os.sep):
            git_total += sz
            if rel.startswith(".git" + os.sep + "objects" + os.sep):
                git_objs += sz
            continue
        top.append((sz, rel))
        c = cats.setdefault(categorize(rel.replace(os.sep, "/"), fn), {"bytes": 0, "files": 0})
        c["bytes"] += sz
        c["files"] += 1

worktree_total = sum(c["bytes"] for c in cats.values())
commit = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
archive = subprocess.check_output(["git", "-C", root, "archive", "HEAD"])
out = {
    "commit": commit,
    "n_files_incl_git": n_files,
    "worktree_total_bytes": worktree_total,
    "git_dir_bytes": git_total,
    "git_objects_bytes": git_objs,
    "categories": dict(sorted(cats.items(), key=lambda kv: -kv[1]["bytes"])),
    "top10_worktree": sorted(top, reverse=True)[:10],
}
print(json.dumps(out, indent=1))
print("TREE_ARCHIVE_SHA256: " + hashlib.sha256(archive).hexdigest(), file=sys.stderr)
