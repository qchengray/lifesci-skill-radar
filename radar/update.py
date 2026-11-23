"""Collect GitHub metadata, then render an auditable, curated research radar."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
API = "https://api.github.com"
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
KINDS = {"Skill", "Marketplace", "Plugin", "MCP", "Extension"}

def load_catalog(root):
    catalog = json.loads((root / "catalog/sources.json").read_text())
    if catalog.get("schema") != 1:
        raise ValueError("unknown catalog schema")
    seen = set()
    for row in catalog["sources"]:
        repo = row["repo"]
        if not REPO.fullmatch(repo) or repo.split("/")[1] in {".", ".."}:
            raise ValueError(f"invalid repository slug: {repo}")
        if repo.lower() in seen:
            raise ValueError(f"duplicate repository: {repo}")
        if row["kind"] not in KINDS or row["tier"] not in {"上游", "社区"}:
            raise ValueError(f"invalid classification: {repo}")
        if not row["evidence"].startswith("https://"):
            raise ValueError(f"expected HTTPS source evidence: {repo}")
        seen.add(repo.lower())
    if not seen:
        raise ValueError("empty catalog")
    return catalog["sources"]

def api_json(endpoint, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LifeSci-Skill-Radar/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            with urlopen(Request(API + endpoint, headers=headers), timeout=12) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in {500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("retry loop exhausted")

def observe(source, token, fetch=api_json):
    repo = source["repo"]
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        data = fetch(f"/repos/{repo}", token)
        stars = data["stargazers_count"]
        if type(stars) is not int or stars < 0 or data.get("visibility") != "public":
            raise ValueError("not a verified public observation")
    except HTTPError as e:
        return {"status": f"http_{e.code}", "stars": None, "observed_at": at}
    except (URLError, TimeoutError, ValueError, TypeError, KeyError):
        return {"status": "unavailable", "stars": None, "observed_at": at}
    license_info = data.get("license") or {}
    return {
        "status": "ok", "stars": stars, "observed_at": at,
        "repo_id": data.get("id"), "pushed_at": data.get("pushed_at"),
        "archived": bool(data.get("archived")),
        "license": license_info.get("spdx_id"),
    }

def atomic_text(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == body:
        return
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(body, encoding="utf-8")
    temp.replace(path)

def read_history(root):
    history = {}
    for path in sorted((root / "snapshots").glob("????-??-??.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        day = date.fromisoformat(path.stem)
        if payload["day_beijing"] != day.isoformat() or payload["schema"] != 1:
            raise ValueError(f"invalid snapshot: {path}")
        history[day] = payload["observations"]
    return history

def save_snapshot(root, day, observations):
    payload = {"schema": 1, "day_beijing": day.isoformat(), "observations": observations}
    atomic_text(root / "snapshots" / f"{day}.json",
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

def rank(observations):
    ordered = sorted((key for key, row in observations.items() if row["stars"] is not None),
                     key=lambda key: (-observations[key]["stars"], key.lower()))
    # Competition rank: 1, 1, 3 ...
    ranks = {}
    last = None
    for index, key in enumerate(ordered, 1):
        stars = observations[key]["stars"]
        if stars != last:
            position = index
        ranks[key] = position
        last = stars
    return ranks

def delta(before, after):
    if not before or not after or before["stars"] is None or after["stars"] is None:
        return None
    if before.get("repo_id") is None or before.get("repo_id") != after.get("repo_id"):
        return None
    return after["stars"] - before["stars"]

def signed(value):
    return "—" if value is None else f"{value:+,}" if value else "0"

def md(value):
    return str(value).replace("|", r"\|").replace("\n", " ")

def source_link(source):
    repo = source["repo"]
    return f"[{repo}](https://github.com/{repo})"

def render_board(root, sources, history):
    chunks = ["# 每日雷达 / Daily radar", ""]
    if history:
        day = max(history)
        now = history[day]
        yesterday = history.get(day - timedelta(days=1), {})
        before_week = history.get(day - timedelta(days=7), {})
        active = {s["repo"] for s in sources}
        ranks = rank({key: val for key, val in now.items() if key in active})
        prev_ranks = rank({key: val for key, val in yesterday.items() if key in active})
        same_cohort = (set(now) == active == set(yesterday) == set(ranks) == set(prev_ranks)
                       and all(delta(yesterday[k], now[k]) is not None for k in active))
        chunks += [f"北京时间 **{day}**｜GitHub 星数采集成功：{len(ranks)}/{len(sources)}。",
                   f"[原始快照](../snapshots/{day}.json) · [周报和月报](../reports/README.md)", ""]
        head = "| 排名 | 来源 | 类型 | 来源归属 | 星数 | Δ1日 | Δ7日 | 排名↑ | 最近推送 (UTC) | 状态 |"
        chunks += [head, "|---:|---|---|---|---:|---:|---:|---:|---|---|"]
        for s in sorted(sources, key=lambda s: (ranks.get(s["repo"], 10**6), s["repo"].lower())):
            repo = s["repo"]
            row = now.get(repo, {"stars": None, "status": "not_sampled"})
            stars = row["stars"]
            rise = prev_ranks[repo] - ranks[repo] if same_cohort else None
            status = "已归档" if row.get("archived") else row["status"]
            pushed = (row.get("pushed_at") or "—")[:10]
            vals = [ranks.get(repo, "—"), source_link(s), s["kind"], s["tier"],
                    "—" if stars is None else f"{stars:,}",
                    signed(delta(yesterday.get(repo), row)), signed(delta(before_week.get(repo), row)),
                    signed(rise), pushed, status]
            chunks.append("| " + " | ".join(map(md, vals)) + " |")
    else:
        chunks += ["尚无实测快照。首次运行后生成排名；没有历史值时不补造涨幅。"]
    chunks += ["", "星标仅反映仓库关注度，不是科研质量或安全背书。Δ 按北京时间自然日精确对比；缺基线或采集失败显示「—」，真实零增长显示 0。昨日与今日必须是同一批且都采集成功，才显示名次变化。并列同名次。",
               "", "## 按科研用途选入口", ""]
    for track in dict.fromkeys(s["track"] for s in sources):
        chunks += [f"### {track}", ""]
        for s in sources:
            if s["track"] == track:
                chunks.append(f"- {source_link(s)} · {s['kind']} · {s['tier']}｜{s['use']}｜[上游依据]({s['evidence']})")
        chunks.append("")
    atomic_text(root / "catalog/README.md", "\n".join(chunks).rstrip() + "\n")

def previous_periods(today):
    monday = today - timedelta(days=today.weekday())
    start_week = monday - timedelta(days=7)
    end_week = monday - timedelta(days=1)
    iso = start_week.isocalendar()
    month_end = today.replace(day=1) - timedelta(days=1)
    month_start = month_end.replace(day=1)
    return [("weekly", f"{iso.year}-W{iso.week:02d}", start_week, end_week),
            ("monthly", month_start.strftime("%Y-%m"), month_start, month_end)]

def report_period(root, history, kind, slug, start, end):
    days = sorted(day for day in history if start <= day <= end)
    if not days:
        return
    first, latest = days[0], days[-1]
    early, late = history[first], history[latest]
    n, total = len(days), (end - start).days + 1
    old = history.get(start - timedelta(days=1), {})
    baseline = start - timedelta(days=1) if old else first
    base = old or early
    complete_window = bool(old) and latest == end
    lines = [f"# {'周报' if kind == 'weekly' else '月报'} / {slug}", "",
             f"统计区间（北京时间）：{start} 至 {end}。区间快照 {n}/{total} 天。",
             f"对比端点：{baseline} → {latest}（{'整期边界' if complete_window else '仅可用区间，非整期' }）。", ""]
    observed = {key for day in days for key, row in history[day].items() if row["stars"] is not None}
    baseline_set = {key.lower() for key in base}
    distinct_period_samples = baseline < latest
    changes = {key: delta(base.get(key), late[key]) for key in late if key in observed and key in base} if distinct_period_samples else {}
    ordered = sorted((key for key, change in changes.items() if change is not None),
                     key=lambda key: (-changes[key], -late[key]["stars"], key.lower()))
    if ordered:
        lines += ["| 来源 | 星数变化 | 期末星数 |", "|---|---:|---:|"]
        for key in ordered:
            lines.append(f"| [{key}](https://github.com/{key}) | {signed(changes[key])} | {late[key]['stars']:,} |")
    else:
        lines.append("暂无两个可比较的观测端点；不将缺失当作零增长。")
    new = sorted((key for key in observed if key.lower() not in baseline_set), key=str.lower)
    lines += ["", f"对比端点后新增且取得有效观测：{len(new)}。"]
    lines += [f"- [{key}](https://github.com/{key})" for key in new]
    missing = sorted(observed - set(ordered), key=str.lower)
    if missing:
        lines += ["", "缺少可比较端点：" + "、".join(f"`{key}`" for key in missing) + "。"]
    stale = sorted((key for key in late if late[key].get("archived")), key=str.lower)
    if stale:
        lines += ["", "期末已归档仓库：" + "、".join(f"`{key}`" for key in stale) + "。"]
    lines += ["", f"[期初原始快照](../../snapshots/{baseline}.json) · [期末原始快照](../../snapshots/{latest}.json) · [返回归档](../README.md)", ""]
    atomic_text(root / "reports" / kind / f"{slug}.md", "\n".join(lines))

def render_archive(root, history, today):
    for kind, slug, start, end in previous_periods(today):
        report_period(root, history, kind, slug, start, end)
    lines = ["# 周报与月报 / Report archive", "",
             "按北京时间统计：周一汇总上一周（周一至周日），每月 1 日汇总上一个自然月。"]
    for kind, title in (("weekly", "周报"), ("monthly", "月报")):
        lines += ["", f"## {title}", ""]
        files = sorted((root / "reports" / kind).glob("*.md"), reverse=True)
        lines += [f"- [{p.stem}]({kind}/{p.name})" for p in files] if files else ["暂无可供汇总的历史快照。"]
    atomic_text(root / "reports/README.md", "\n".join(lines) + "\n")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-only", action="store_true", help="do not query GitHub or write a snapshot")
    args = parser.parse_args()
    today = datetime.now(BEIJING).date()
    sources = load_catalog(ROOT)
    history = read_history(ROOT)
    if not args.render_only:
        token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        prior = history.get(today, {})
        observations = {}
        for source in sources:
            key = source["repo"]
            # Preserve earlier successful same-day samples; retry unresolved items.
            observations[key] = prior[key] if prior.get(key, {}).get("status") == "ok" else observe(source, token)
        n = sum(row["status"] == "ok" for row in observations.values())
        if not n:
            counts = {row["status"] for row in observations.values()}
            print(f"no successful observations; no snapshot written ({', '.join(sorted(counts))})", file=sys.stderr)
            return 1
        save_snapshot(ROOT, today, observations)
        history[today] = observations
        print(f"{today}: observed {n}/{len(observations)} public repositories")
    render_board(ROOT, sources, history)
    render_archive(ROOT, history, today)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
