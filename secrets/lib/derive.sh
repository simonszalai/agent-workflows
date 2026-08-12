# shellcheck shell=bash
# derive.sh — the value transforms. PURE: a value comes in on stdin, a
# transformed value goes out on stdout; no `op`, no I/O, no hidden topology.
# The transform string lives on the manifest row, so the same input + transform
# always yields the same output (trivially unit-testable).
#
# Union of every hub's transforms (value on stdin):
#   self                     pass the value through unchanged (keeps query)
#   conn-id                  Kinde connection id: must begin with `conn_`
#   db=<name>                swap the database to <name>, keep host/scheme/query
#                            (one instance credential reused across databases)
#   pgbouncer=<host:port>/<db>   plain postgresql scheme via a pgbouncer host,
#                            port from the transform string, query dropped
#   asyncpg-internal=<db>    postgresql+asyncpg on the Render-internal host
#   asyncpg-external=<db>    postgresql+asyncpg on the external host
#   rehost=<host>/<db>       swap host and database, keep scheme/user/query
#                            (optional :port on host; default is the source port)
#
# Empty stdin -> exit 2. Unknown transform -> exit 3. The transform string is
# passed via the TRANSFORM env var, never argv.
apply_transform() { # transform   (value on stdin -> transformed value on stdout)
  TRANSFORM="$1" python3 -c '
import os, sys, urllib.parse as up
url = sys.stdin.read().strip()
if not url:
    sys.exit(2)
t = os.environ["TRANSFORM"]
w = sys.stdout.write
if t == "self":
    w(url)
    sys.exit(0)
if t == "no-query":
    # Strip the query string (and fragment): pgbouncer-style config generators
    # cannot parse URLs carrying ?options=... parameters.
    sp = up.urlsplit(url)
    w(up.urlunsplit((sp.scheme, sp.netloc, sp.path, "", "")))
    sys.exit(0)
if t == "conn-id":
    if not url.startswith("conn_"):
        sys.stderr.write("ERROR: value is not a Kinde connection id (must start with conn_)\n")
        sys.exit(3)
    w(url)
    sys.exit(0)
p = up.urlsplit(url)
user = up.quote(p.username or "", safe="")
pw   = up.quote(up.unquote(p.password or ""), safe="")  # unquote-then-requote: idempotent %-encoding
cred = f"{user}:{pw}"
ext  = p.hostname or ""
port = p.port or 5432
internal = ext.split(".")[0]  # Render internal host = external minus regional suffix
if t.startswith("db="):
    db = t[3:]
    tail = f"?{p.query}" if p.query else ""
    w(f"{p.scheme}://{cred}@{ext}:{port}/{db}{tail}")
elif t.startswith("pgbouncer="):
    hostport, _, db = t[len("pgbouncer="):].partition("/")
    w(f"postgresql://{cred}@{hostport}/{db}")
elif t.startswith("asyncpg-internal="):
    db = t[len("asyncpg-internal="):]
    w(f"postgresql+asyncpg://{cred}@{internal}:{port}/{db}")
elif t.startswith("asyncpg-external="):
    db = t[len("asyncpg-external="):]
    w(f"postgresql+asyncpg://{cred}@{ext}:{port}/{db}")
elif t.startswith("rehost="):
    spec = t[len("rehost="):]
    hostport, sep, db = spec.partition("/")
    if not sep or not hostport or not db or "/" in db:
        sys.stderr.write("ERROR: rehost needs host[:port]/db\n")
        sys.exit(3)
    if ":" in hostport:
        host, _, port_s = hostport.rpartition(":")
        if not host or not port_s.isdigit():
            sys.stderr.write("ERROR: rehost host:port is malformed\n")
            sys.exit(3)
        port = int(port_s)
    else:
        host = hostport
    tail = f"?{p.query}" if p.query else ""
    w(f"{p.scheme}://{cred}@{host}:{port}/{db}{tail}")
else:
    sys.stderr.write(f"ERROR: unknown transform: {t}\n")
    sys.exit(3)
'
}
