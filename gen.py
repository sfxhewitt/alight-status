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
        return sorted(out, reverse=True)


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
    if t == "clean":
        return repo.git and not repo.status()
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
    out["site"] = site_check(p.get("live"))
    ctx = {"site": out["site"]}

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
    rl = repos() or prev or []
    data = {"schema": 2, "updated": iso(NOW), "generated_ms": round((time.time() - NOW) * 1000),
            "projects": projects, "repos": rl}
    tmp = os.path.join(HERE, ".status.json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(HERE, "status.json"))


if __name__ == "__main__":
    main()
