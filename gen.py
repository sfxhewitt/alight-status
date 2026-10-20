#!/usr/bin/env python3
"""Mission Control generator: reads projects.json, writes status.json.

PRIVACY: the output is published on a public site. Only derived facts go in it
(states, counts, times, HTTP codes, commit subjects of public repos). Never file
contents, env values, tokens, hostnames of private servers or local paths.
"""
import glob, json, os, re, sqlite3, subprocess, time, urllib.request, urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
LDN = ZoneInfo("Europe/London")
CFG = json.load(open(os.path.join(HERE, "projects.json")))
NOW = time.time()


def sh(args, cwd=None, timeout=20):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def iso(ts):  # epoch -> ISO in Europe/London
    return datetime.fromtimestamp(ts, LDN).isoformat(timespec="seconds") if ts else None


def from_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def files(root, pattern):
    p = pattern if os.path.isabs(pattern) else os.path.join(root, pattern)
    return [f for f in glob.glob(p, recursive=True) if os.path.isfile(f)]


def jget(path, key):
    try:
        d = json.load(open(path))
        for k in key.split("."):
            d = d[k]
        return d
    except Exception:
        return None


_meta_cache = {}
def catalog_meta(path):
    if path not in _meta_cache:
        _meta_cache[path] = jget(path, "meta")
    return _meta_cache[path]


def sqlite_count(path, table):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        n = c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        c.close()
        return n
    except Exception:
        return None


def site_check(url):
    if not url:
        return None
    t = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mission-control/1", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    return {"code": code, "ok": 200 <= code < 400, "ms": round((time.time() - t) * 1000)}


class Repo:
    def __init__(self, p):
        self.p = p
        self.root = p.get("path")
        self.git = bool(self.root and os.path.isdir(os.path.join(self.root, ".git")))
        self._status = None

    def g(self, *a):
        return sh(["git", *a], cwd=self.root) if self.git else None

    def status(self):  # list of (code, path)
        if self._status is None:
            out = self.g("status", "--porcelain", "--untracked-files=all") or ""
            self._status = [(l[:2], l[3:]) for l in out.splitlines() if l.strip()]
        return self._status

    def ignored(self, paths):  # subset of paths git ignores (generated output)
        if not self.git or not paths:
            return set()
        try:
            r = subprocess.run(["git", "check-ignore", "--stdin"], cwd=self.root, input="\n".join(paths),
                               capture_output=True, text=True, timeout=20)
            return set(r.stdout.splitlines())
        except Exception:
            return set()

    def head(self):
        return self.g("rev-parse", "HEAD")

    def ahead(self):
        n = self.g("rev-list", "--count", "@{u}..HEAD")
        if n is None:
            br = self.g("rev-parse", "--abbrev-ref", "HEAD")
            n = self.g("rev-list", "--count", f"origin/{br}..HEAD") if br else None
        return int(n) if n and n.isdigit() else None

    def last_commit_ts(self):
        s = self.g("log", "-1", "--format=%ct")
        return int(s) if s else None

    def recent_files(self, minutes):
        out, cutoff, ign = [], NOW - minutes * 60, set(CFG.get("ignore_dirs", []))
        if not self.root or not os.path.isdir(self.root):
            return out
        for d, dirs, fs in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in ign]
            for f in fs:
                fp = os.path.join(d, f)
                try:
                    m = os.path.getmtime(fp)
                except OSError:
                    continue
                if m >= cutoff:
                    out.append((m, os.path.relpath(fp, self.root)))
        ig = self.ignored([f for _, f in out])
        return sorted([x for x in out if x[1] not in ig], reverse=True)


_pages = {}
def pages_state(slug):
    """Latest GitHub Pages build/deployment for a repo -> {"state", "sha"} (legacy builds or Actions deployments)."""
    if slug in _pages:
        return _pages[slug]
    res = None
    j = sh(["gh", "api", f"repos/{slug}/pages/builds/latest"], timeout=15)
    try:
        b = json.loads(j)
        res = {"state": b.get("status"), "sha": b.get("commit")}
    except Exception:
        pass
    if not res or not res["sha"]:  # Actions-based Pages: use the github-pages environment deployments
        j = sh(["gh", "api", f"repos/{slug}/deployments?environment=github-pages&per_page=1"], timeout=15)
        try:
            dep = json.loads(j)[0]
            st = json.loads(sh(["gh", "api", dep["statuses_url"] + "?per_page=1"], timeout=15) or "[]")
            s0 = st[0]["state"] if st else "queued"
            res = {"state": "built" if s0 == "success" else s0, "sha": dep["sha"]}
        except Exception:
            res = None
    _pages[slug] = res
    return res


def check(c, repo, ctx):
    t, root = c["type"], repo.root or ""
    if t == "exists":
        return bool(files(root, c["path"]))
    if t == "commit_grep":
        out = repo.g("log", "-200", "--format=%s%n%b")
        return bool(out and re.search(c["pattern"], out, re.I))
    if t == "site_up":
        return bool(ctx.get("site") and ctx["site"]["ok"])
    if t == "pushed":
        return repo.ahead() == 0
    if t == "clean":  # tracked changes only; untracked files never block (use untracked:true to include)
        return repo.git and not [x for x in repo.status() if c.get("untracked") or x[0] != "??"]
    if t == "deployed":  # GitHub Pages serves HEAD
        d = pages_state(ctx["repo"])
        return bool(d and d["state"] == "built" and d["sha"] == repo.head())
    if t == "deploying":
        d = pages_state(ctx["repo"])
        return bool(d and d["state"] in ("building", "queued", "in_progress") and d["sha"] == repo.head())
    if t == "tracked":
        return bool(repo.g("ls-files", "--error-unmatch", c["path"]))
    if t == "process":
        return sh(["pgrep", "-f", c["pattern"]]) is not None
    if t == "newer":
        a = [os.path.getmtime(f) for f in files(root, c["path"])]
        b = [os.path.getmtime(f) for f in files(root, c["than"])]
        return bool(a and b and max(a) > max(b))
    if t == "json_true":
        return jget(os.path.join(root, c["path"]), c["key"]) is True
    if t == "catalog_scored":
        m = catalog_meta(os.path.join(root, c["path"]))
        return bool(m and m.get("count") and m.get("jev_scored", 0) >= c.get("min_ratio", 1) * m["count"])
    if t == "source_dirty":
        lc = repo.last_commit_ts() or 0
        pats = [os.path.join(root, g) for g in c["globs"]]
        for code, path in repo.status():
            if any(glob.fnmatch.fnmatch(os.path.join(root, path), p) for p in pats):
                return True
        return any(os.path.getmtime(f) > lc + 5 for g in c["globs"] for f in files(root, g))
    return False


def progress(c, repo):
    root = repo.root
    if c["type"] == "catalog":
        m = catalog_meta(os.path.join(root, c["path"])) or {}
        fetched = sqlite_count(os.path.join(root, c["db"]), "tmdb")
        cached = sqlite_count(os.path.join(root, c["db"]), "jev_cache")
        total = m.get("count") or fetched
        scored = max(m.get("jev_scored") or 0, cached or 0)
        if not total:
            return None
        return {"done": scored, "total": total, "label": f"{scored:,}/{total:,} films Jev-scored",
                "extra": f"{total:,} films in catalogue · {m.get('heuristic_scored', 0):,} heuristic" if m else None}
    return None


def detail(c, repo):
    if c["type"] == "sqlite_count":
        n = sqlite_count(os.path.join(repo.root, c["path"]), c["table"])
        return f"{n:,} {c['label']}" if n is not None else None
    return None


def build_project(p):
    repo, private = Repo(p), bool(p.get("private"))
    out = {k: p.get(k) for k in ("id", "name", "description", "phase", "live")}
    out["repo"] = p["repo"]
    out["repo_url"] = f"https://github.com/{p['repo']}"
    out["private"] = private
    if p.get("archived"):
        out["archived"] = True  # permanent archive from projects.json
    out["site"] = site_check(p.get("live"))
    ctx = {"site": out["site"], "repo": p["repo"]}

    # commit info
    if repo.git:
        ig = ["--invert-grep", "--extended-regexp", f"--grep={p['commit_ignore']}"] if p.get("commit_ignore") else []
        fmt = repo.g("log", "-1", *ig, "--format=%ct%x1f%h%x1f%s") or repo.g("log", "-1", "--format=%ct%x1f%h%x1f%s")
        if fmt:
            ts, h, subj = fmt.split("\x1f", 2)
            out["commit"] = {"time": iso(int(ts)), "hash": h, "message": subj[:140]}
        out["commits"] = int(repo.g("rev-list", "--count", "HEAD") or 0)
        out["ahead"] = repo.ahead()
    else:
        j = sh(["gh", "api", f"repos/{p['repo']}/commits?per_page=1"])
        try:
            c = json.loads(j)[0]
            out["commit"] = {"time": iso(from_iso(c["commit"]["committer"]["date"])), "hash": c["sha"][:7],
                             "message": c["commit"]["message"].splitlines()[0][:140]}
        except Exception:
            out["commit"] = None

    # active build indicator
    if not p.get("skip_active"):
        st = repo.status()
        recent = repo.recent_files(CFG.get("active_minutes", 15))
        st = [x for x in st if x[0] != "??" or x[1] not in repo.ignored([x[1]])]
        active = bool(recent) or any(c != "??" for c, _ in st)
        a = {"on": active, "changed": len(st), "recent": len(recent)}
        if recent:
            a["last_edit"] = iso(recent[0][0])
        if not private:  # file names only for public repos
            a["files"] = [f for _, f in recent[:4]] or [f for _, f in st[:4]]
        out["active"] = a

    # steps
    steps = []
    for s in p.get("steps", []):
        try:
            done = all(check(c, repo, ctx) for c in s.get("done", []))
            run = bool(s.get("run")) and all(check(c, repo, ctx) for c in s["run"])
            warn = [c.get("message", "warning") for c in s.get("warn", []) if check(c, repo, ctx)]
            state = "done" if done else "run" if run else "warn" if warn else "todo"
            item = {"name": s["name"], "state": state}
            if warn and not done:
                item["note"] = warn[0]
            if s.get("progress"):
                pr = progress(s["progress"], repo)
                if pr:
                    item["progress"] = pr
            if s.get("detail"):
                d = detail(s["detail"], repo)
                if d:
                    item["note"] = d
            steps.append(item)
        except Exception as e:
            steps.append({"name": s["name"], "state": "todo", "note": "check failed"})
    out["steps"] = steps
    if steps:
        nd = sum(s["state"] == "done" for s in steps)
        out["pct"] = round(100 * nd / len(steps))
        cur = next((s for s in steps if s["state"] in ("run", "warn")), None) or next((s for s in steps if s["state"] == "todo"), None)
        out["current"] = cur["name"] if cur else "Complete"
    return out


# ---- per-project notes: GitHub Issues in the dashboard repo labelled mc:<id> ----
NOTES_REPO = CFG.get("notes_repo", "sfxhewitt/alight-status")
NOTES_CACHE = os.path.join(HERE, ".cache", "notes.json")
NOTES_TTL = 120          # seconds between GitHub calls
NOTES_CLOSED_DAYS = 14   # closed notes stay visible this long
NOTES_MAX = 8            # per project
NOTES_Q = """query($o:String!,$r:String!){viewer{login}repository(owner:$o,name:$r){issues(first:100,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{
number title body state createdAt closedAt url author{login} labels(first:10){nodes{name}}
comments(last:20){nodes{author{login} body createdAt url}}}}}}"""


def _snip(s, n=220):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def fetch_notes_raw():
    """One GraphQL call (gh's own auth; the token never touches our output). Cached for NOTES_TTL."""
    try:
        c = json.load(open(NOTES_CACHE))
        if NOW - c.get("at", 0) < NOTES_TTL:
            return c["data"]
    except Exception:
        c = None
    o, r = NOTES_REPO.split("/", 1)
    out = sh(["gh", "api", "graphql", "-f", f"query={NOTES_Q}", "-F", f"o={o}", "-F", f"r={r}"], timeout=15)
    try:
        d = json.loads(out)["data"]
        issues = d["repository"]["issues"]["nodes"]
        data = {"viewer": d["viewer"]["login"], "issues": issues}
        os.makedirs(os.path.dirname(NOTES_CACHE), exist_ok=True)
        tmp = NOTES_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"at": NOW, "data": data}, f)
        os.replace(tmp, NOTES_CACHE)
        return data
    except Exception:
        return c["data"] if c else None  # stale cache beats nothing; None = unavailable


def notes_by_project(raw, now=None):
    """raw -> {project_id: [note, ...]} with open notes first (newest first), then recently closed."""
    now = NOW if now is None else now
    if not raw:
        return {}
    me = (raw.get("viewer") or "").lower()
    res = {}
    for it in raw.get("issues") or []:
        labels = [l["name"] for l in (it.get("labels") or {}).get("nodes", [])]
        ids = [l[3:] for l in labels if l.startswith("mc:")]
        if not ids:
            continue
        closed = it.get("state") != "OPEN"
        if closed and (now - (from_iso(it.get("closedAt")) or 0)) > NOTES_CLOSED_DAYS * 86400:
            continue
        n = {"number": it["number"], "title": _snip(it.get("title"), 140), "body": _snip(it.get("body")),
             "state": "closed" if closed else "open", "created_at": iso(from_iso(it.get("createdAt"))),
             "html_url": it.get("url")}
        if closed:
            n["closed_at"] = iso(from_iso(it.get("closedAt")))
        mine = [c for c in (it.get("comments") or {}).get("nodes", [])
                if me and ((c.get("author") or {}).get("login") or "").lower() == me]
        if mine:
            c = mine[-1]
            n["reply"] = {"body": _snip(c.get("body"), 280), "created_at": iso(from_iso(c.get("createdAt"))),
                          "html_url": c.get("url")}
        for pid in ids:
            res.setdefault(pid, []).append(n)
    for pid, ns in res.items():
        ns.sort(key=lambda n: (n["state"] != "open", -(from_iso(n["created_at"]) or 0)))
        res[pid] = ns[:NOTES_MAX]
    return res


def repos():
    j = sh(["gh", "repo", "list", CFG["owner"], "--limit", "200", "--json", "name,visibility,pushedAt"], timeout=30)
    try:
        rs = json.loads(j)
    except Exception:
        return None
    return [{"name": r["name"], "visibility": r["visibility"].lower(), "pushed": iso(from_iso(r["pushedAt"]))}
            for r in sorted(rs, key=lambda r: r["pushedAt"], reverse=True)]


def main():
    prev = jget(os.path.join(HERE, "status.json"), "repos")
    projects = []
    for p in CFG["projects"]:
        try:
            projects.append(build_project(p))
        except Exception:
            projects.append({"id": p.get("id"), "name": p.get("name"), "error": True})
    try:
        raw = fetch_notes_raw()
        notes = notes_by_project(raw)
    except Exception:
        raw, notes = None, {}
    for pr in projects:
        pr["comments"] = notes.get(pr.get("id"), [])
        if raw is None:
            pr["comments_error"] = True
    rl = repos() or prev or []
    data = {"schema": 2, "updated": iso(NOW), "generated_ms": round((time.time() - NOW) * 1000),
            "projects": projects, "repos": rl}
    tmp = os.path.join(HERE, ".status.json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(HERE, "status.json"))


if __name__ == "__main__":
    main()
