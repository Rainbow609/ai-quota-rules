#!/usr/bin/env python3
"""校验 rules/ 下的规则文件：结构 + 语义（纯离线，仅标准库）。

刻意不引入 jsonschema 依赖：schema/ruleset.schema.json 给编辑器与客户端用，
这里用等价的显式检查，保证 CI 与本地零依赖可跑。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "rules")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[0-9]+\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[[0-9]+\])?)*$")
TIME_RE = re.compile(r"^[0-2][0-9]:[0-5][0-9]$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

KINDS = {"balance", "subscription"}
AUTH_TYPES = {"bearer", "raw", "oauth", "cookie"}
CONFIDENCE = {"official", "semi-official", "community"}
UNITS = {"money", "percent", "count", "seconds", "string", "bool", "timestamp"}

errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_provider(name: str, p: dict, holiday_ids: set[str]) -> None:
    tag = f"providers/{name}"
    for field in ("id", "name", "kind", "auth", "queries", "confidence"):
        check(field in p, f"{tag}: 缺少必填字段 {field}")
    check(ID_RE.match(p.get("id", "")) is not None, f"{tag}: id 格式非法")
    check(p.get("kind") in KINDS, f"{tag}: kind 非法")
    check(p.get("confidence") in CONFIDENCE, f"{tag}: confidence 非法")
    check(bool(p.get("sources")), f"{tag}: 必须给出至少一个来源 URL")
    check(p.get("auth", {}).get("type") in AUTH_TYPES, f"{tag}: auth.type 非法")

    region_ids = {r["id"] for r in p.get("regions", [])}
    for r in p.get("regions", []):
        check(r.get("base", "").startswith("https://"), f"{tag}: region {r.get('id')} 的 base 必须 https")

    queries = p.get("queries") or []
    check(len(queries) > 0, f"{tag}: queries 不能为空")
    for q in queries:
        qt = f"{tag}:query[{q.get('id')}]"
        check(q.get("method") in {"GET", "POST"}, f"{qt} method 非法")
        check(str(q.get("path", "")).startswith("/"), f"{qt} path 必须以 / 开头")
        if region_ids:
            check(q.get("region") in region_ids, f"{qt} region 未在 regions 中声明")
        for lp in q.get("legacy_paths", []):
            check(str(lp).startswith("/"), f"{qt} legacy_paths 元素必须以 / 开头")
        values = q.get("values") or []
        check(len(values) > 0, f"{qt} values 不能为空")
        for v in values:
            check(PATH_RE.match(str(v.get("from", ""))) is not None, f"{qt} value[{v.get('id')}] from 路径非法")
            check(v.get("unit") in UNITS, f"{qt} value[{v.get('id')}] unit 非法")
            for key in ("currency_from", "reset_from", "status_from"):
                if key in v:
                    check(PATH_RE.match(str(v[key])) is not None, f"{qt} value[{v.get('id')}] {key} 路径非法")

    peak = p.get("peak")
    if peak:
        check(isinstance(peak.get("has_peak"), bool), f"{tag}: peak.has_peak 必须是布尔")
        check(isinstance(peak.get("schedule_known"), bool), f"{tag}: peak.schedule_known 必须是布尔")
        if peak.get("windows"):
            check(bool(peak.get("timezone")), f"{tag}: peak.windows 存在时必须给 timezone")
            for w in peak["windows"]:
                check(all(1 <= d <= 7 for d in w.get("days", [])), f"{tag}: peak.windows days 越界")
                check(TIME_RE.match(w.get("start", "")) is not None, f"{tag}: peak.windows start 非法")
                check(TIME_RE.match(w.get("end", "")) is not None, f"{tag}: peak.windows end 非法")
        hc = peak.get("holiday_calendar")
        if hc:
            check(hc in holiday_ids, f"{tag}: holiday_calendar '{hc}' 在 rules/holidays 下不存在")


def main() -> int:
    pdir = os.path.join(RULES, "providers")
    hdir = os.path.join(RULES, "holidays")
    holiday_ids = {n[:-5] for n in os.listdir(hdir) if n.endswith(".json")} if os.path.isdir(hdir) else set()

    seen: set[str] = set()
    files = sorted(n for n in os.listdir(pdir) if n.endswith(".json"))
    for name in files:
        p = load(os.path.join(pdir, name))
        check(p.get("id") == name[:-5], f"providers/{name}: id 与文件名不一致")
        check(p.get("id") not in seen, f"providers/{name}: id 重复")
        seen.add(p.get("id"))
        check_provider(name, p, holiday_ids)

    for hid in holiday_ids:
        h = load(os.path.join(hdir, f"{hid}.json"))
        for d in h.get("days", []):
            check(DATE_RE.match(str(d)) is not None, f"holidays/{hid}: 非法日期 {d}")

    if errors:
        print("校验失败：")
        for e in errors:
            print("  -", e)
        return 1
    print(f"校验通过：{len(files)} 个 provider，{len(holiday_ids)} 个节假日日历")
    return 0


if __name__ == "__main__":
    sys.exit(main())
