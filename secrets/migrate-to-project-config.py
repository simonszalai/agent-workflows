#!/usr/bin/env python3
"""Generate each project's secrets.yaml from the legacy split sources, and PROVE
the migration is lossless.

Legacy layout (three mechanisms, duplicated):
  agent-workflows/config/secret-rotation.json   rotation policy + health_urls
                                                + consumers[] (a hand-maintained
                                                partial COPY of the routes)
  <repo>/scripts/secrets/manifest               the real routes, one TSV row each

New layout (one file per project, in the project's primary repo):
  <primary-repo>/secrets.yaml                   project, repos, health, rotation,
                                                routes — joined on the op:// ref

consumers[] does not survive: routes and rotation entries now live in the same
file, so a rotation entry's consumer set is DERIVED (routes where ref matches)
instead of copied. At migration time 58 of 93 entries disagreed with the routes
they were copying, every one of them an under-count.

The primary repo of a project is the repo owning the most rotation entries.
Repo references are bare sibling names, never absolute paths, so a checked-in
config does not encode one machine's directory layout.

usage:
  migrate-to-project-config.py --dev-root ~/dev [--out DIR] [--check]

--out writes elsewhere (staging/review) instead of into the repos.
--check verifies only; it writes nothing. Exit 1 if the migration would lose or
alter any route.
"""
import argparse, collections, json, os, sys

try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML required (pip install pyyaml)")

CONFIG_NAME = "secrets.yaml"
LEGACY_REGISTRY = "agent-workflows/config/secret-rotation.json"
LEGACY_MANIFEST = "scripts/secrets/manifest"


def repo_name(path):
    return os.path.basename(path.rstrip("/"))


def load_legacy(dev):
    reg_path = os.path.join(dev, LEGACY_REGISTRY)
    if not os.path.isfile(reg_path):
        sys.exit(f"ERROR: legacy registry not found: {reg_path}")
    reg = json.load(open(reg_path))
    entries = reg["secrets"]
    # "$comment" keys are a JSON-can't-hold-comments workaround; YAML drops them.
    health = {k: v for k, v in reg.get("health_urls", {}).items() if not k.startswith("$")}

    repo_project = {}
    for e in entries:
        repo_project.setdefault(e["owner_repo"], e["project"])
        for c in e.get("consumers") or []:
            repo_project.setdefault(c["repo"], e["project"])

    routes = collections.defaultdict(list)
    flat = {}
    for name in sorted(os.listdir(dev)):
        path = os.path.join(dev, name, LEGACY_MANIFEST)
        if not os.path.isfile(path):
            continue
        abs_repo = os.path.join(dev, name)
        project = repo_project.get(abs_repo)
        if project is None:
            sys.exit(f"ERROR: {path} belongs to no known project — its routes would be lost")
        for lineno, line in enumerate(open(path), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                sys.exit(f"ERROR: {path}:{lineno}: expected 5 tab-separated fields, got {len(fields)}")
            kind, dest, env, ref, transform = fields
            key = (name, kind, dest, env)
            if key in flat:
                sys.exit(f"ERROR: {path}:{lineno}: duplicate route {key}")
            flat[key] = (ref, transform)
            routes[project].append(dict(repo=name, kind=kind, dest=dest, env=env,
                                        ref=ref, transform=transform))
    return entries, health, routes, flat


def build(entries, health, routes):
    owned = collections.Counter((e["project"], e["owner_repo"]) for e in entries)
    primary = {}
    for (project, repo), _ in owned.most_common():
        primary.setdefault(project, repo)

    docs = {}
    for project, prim in sorted(primary.items()):
        rows = sorted(routes.get(project, []),
                      key=lambda x: (x["kind"], x["repo"], x["dest"], x["env"]))
        rotation = {}
        for e in entries:
            if e["project"] != project:
                continue
            d = {k: v for k, v in e.items() if k not in ("id", "project", "consumers")}
            d["owner_repo"] = repo_name(d["owner_repo"])
            rotation[e["id"]] = d
        dests = {r["dest"] for r in rows}
        docs[project] = (repo_name(prim), {
            "project": project,
            "repos": sorted({r["repo"] for r in rows} | {repo_name(prim)}),
            "health": {k: v for k, v in health.items() if k in dests},
            "rotation": rotation,
            "routes": rows,
        })
    return docs


def dump(doc):
    """Routes one-per-line (flow style) so the file scans like the TSV it
    replaces; everything else block style for its prose fields."""
    head = {k: doc[k] for k in ("project", "repos", "health", "rotation")}
    out = yaml.safe_dump(head, sort_keys=False, width=100, allow_unicode=True)
    out += "\nroutes:\n"
    for row in doc["routes"]:
        out += "- " + yaml.safe_dump(row, default_flow_style=True, width=10 ** 6,
                                     sort_keys=False, allow_unicode=True).strip() + "\n"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-root", default=os.path.expanduser("~/dev"))
    ap.add_argument("--out", help="write here instead of into the primary repos")
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    args = ap.parse_args()

    dev = os.path.abspath(os.path.expanduser(args.dev_root))
    entries, health, routes, flat = load_legacy(dev)
    docs = build(entries, health, routes)

    # Equivalence proof: reparse what we emit and diff every route against the
    # manifests. (repo, kind, dest, env) -> (ref, transform) must be identical.
    rebuilt = {}
    for _, doc in docs.values():
        for r in yaml.safe_load(dump(doc))["routes"]:
            rebuilt[(r["repo"], r["kind"], r["dest"], r["env"])] = (r["ref"], r["transform"])

    missing = sorted(k for k in flat if k not in rebuilt)
    changed = sorted(k for k in flat if k in rebuilt and flat[k] != rebuilt[k])
    extra = sorted(k for k in rebuilt if k not in flat)
    ok = not (missing or changed or extra)

    for project, (prim, doc) in sorted(docs.items()):
        print(f"{project:14s} -> {prim}/{CONFIG_NAME}   "
              f"routes={len(doc['routes'])} rotation={len(doc['rotation'])}")
        orphans = [i for i, e in doc["rotation"].items()
                   if not any(r["ref"] == e["ref"] for r in doc["routes"])]
        for o in orphans:
            print(f"  WARNING: rotation entry '{o}' has no route — it rotates nothing")

    print(f"\nroutes: legacy={len(flat)} migrated={len(rebuilt)} "
          f"missing={len(missing)} changed={len(changed)} extra={len(extra)}")
    for k in (missing + changed + extra)[:20]:
        print("  ", k)
    print("EQUIVALENCE:", "PASS" if ok else "FAIL")
    if not ok:
        return 1
    if args.check:
        return 0

    for _, (prim, doc) in sorted(docs.items()):
        target = os.path.join(args.out or dev, prim) if args.out else os.path.join(dev, prim)
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, CONFIG_NAME)
        open(path, "w").write(dump(doc))
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
