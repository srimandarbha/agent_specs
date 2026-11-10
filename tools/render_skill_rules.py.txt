#!/usr/bin/env python3
"""Render the decision-rule table in a skill body from its front matter (single source of truth).
  python3 tools/render_skill_rules.py <skill.md>           # write
  python3 tools/render_skill_rules.py <skill.md> --check   # exit 1 if the table is stale"""
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agent.skills.loader import load

BEGIN, END = "<!-- rules:begin -->", "<!-- rules:end -->"


def _cond(c):
    fact, op, *v = c
    return f"`{fact}` {op}" + (f" `{v[0]}`" if v else "")


def render(meta) -> str:
    rows = ["| Rule | When | Result | Why |", "|---|---|---|---|"]
    for r in meta.rules:
        key = "always" if "always" in r.when else ("all" if "all" in r.when else "any")
        if key == "always":
            when = "otherwise"
        else:
            when = (" AND " if key == "all" else " OR ").join(_cond(c) for c in r.when[key])
        t = r.then
        rem = t.get("remediation") or {}
        res = f"{t['classification']}/{t['confidence']}"
        if t.get("reason_code"): res += f", `{t['reason_code']}`"
        if t.get("sub_branch"): res += f", `{t['sub_branch']}`"
        if rem: res += f", {rem['kind']}" + (f" `{rem['playbook_id']}`" if rem.get("playbook_id") else "")
        rows.append(f"| **{r.id}** | {when} | {res} | {r.why} |")
    return "\n".join(rows)


def apply(path) -> tuple[str, str]:
    p = pathlib.Path(path)
    meta, _, _ = load(p)
    text = p.read_text()
    pattern = re.compile(re.escape(BEGIN) + r"\n.*?\n?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"{path}: rules markers not found")
    new = pattern.sub(lambda m: f"{BEGIN}\n{render(meta)}\n{END}", text, count=1)
    return text, new


if __name__ == "__main__":
    path = sys.argv[1]
    old, new = apply(path)
    if "--check" in sys.argv:
        print("rules table up to date" if old == new else "rules table STALE")
        sys.exit(0 if old == new else 1)
    pathlib.Path(path).write_text(new)
    print("rendered rules table")
