#!/usr/bin/env python3
"""同步 GCMP 上游定义 + 与本仓库的峰谷规则做差异比对。

背景：GCMP（VicBilibily/GCMP, MIT © 2025 VicBilibily）通过 https://gcmp.dev/configs/ 公开发布
每家 provider 的 ProviderConfig（模型清单、上下文、tokenPricing、tiers 峰谷 cron）。
该 JSON 层**只覆盖模型/价格/路由**；额度查询的 endpoint、鉴权、字段解析在 TS 源码里，
必须人工复核后才能写进 rules/providers/*.json —— 本工具负责前半段：
拉取 + 记录 gcmpVersion/contentHash（可做增量检测）+ 把峰谷 cron 与本仓库规则比对。

用法：
  python3 tools/sync_gcmp.py           # 拉取并写入 upstream/gcmp/snapshot.json
  python3 tools/sync_gcmp.py --diff    # 只做峰谷差异比对（不写文件）
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_URL = "https://gcmp.dev/configs/index.json"
CONFIG_URL = "https://gcmp.dev/configs/{id}.json"
OUT = os.path.join(ROOT, "upstream", "gcmp", "snapshot.json")

# 本仓库 provider id -> GCMP provider 目录名（不一致的才需要列）
ALIAS = {"opencode-go": "opencode", "zhipu-glm": "zhipu"}


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-quota-rules-sync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def index_entries(index: dict) -> dict:
    """index.json 的 providers 可能是 {id: {...}} 或 [{id, ...}]，两种都兼容。"""
    raw = index.get("providers") or {}
    if isinstance(raw, dict):
        return raw
    return {e.get("id"): e for e in raw if isinstance(e, dict)}


def extract_tiers(token_pricing):
    """tokenPricing 实测有四种形态：null / 裸数组 [in,out,cache] / {USD,RMB} / {pricing,tiers}。
    只有最后一种带峰谷 tiers，故按形态防御式提取（这也是"JSON 层不能盲目全自动"的实证）。"""
    if isinstance(token_pricing, dict):
        tiers = token_pricing.get("tiers")
        if isinstance(tiers, list):
            return [t for t in tiers if isinstance(t, dict) and t.get("cron")]
    return []


def build_snapshot() -> dict:
    index = fetch_json(INDEX_URL)
    entries = index_entries(index)
    providers = {}
    for pid in sorted(entries):
        try:
            cfg = fetch_json(CONFIG_URL.format(id=pid))
        except Exception as exc:  # noqa: BLE001 - 单家失败不影响整体
            print(f"  拉取 {pid} 失败：{exc}", file=sys.stderr)
            continue
        providers[pid] = {
            "content_hash": (entries[pid] or {}).get("contentHash"),
            "model_count": (entries[pid] or {}).get("modelCount"),
            "base_url": cfg.get("baseUrl"),
            "models": [
                {
                    "id": m.get("id"),
                    "max_input_tokens": m.get("maxInputTokens"),
                    "has_pricing": m.get("tokenPricing") is not None,
                    "tiers": [
                        {"cron": t.get("cron"), "timezone": t.get("timezone")}
                        for t in extract_tiers(m.get("tokenPricing"))
                    ],
                }
                for m in (cfg.get("models") or [])
                if isinstance(m, dict)
            ],
        }
    return {
        "source": INDEX_URL,
        "license": "GCMP 为 MIT（Copyright (c) 2025 VicBilibily）；本文件仅记录其公开发布的事实性定义",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": index.get("schemaVersion"),
        "gcmp_version": index.get("gcmpVersion"),
        "providers": providers,
    }


def parse_cron(cron: str):
    """支持 `* a-b,c-d * * 1-5` 这类形式；返回 (小时集合, 星期集合，1=周一)。无法解析返回 None。"""
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, _dom, _month, dow = parts
    if minute not in ("*", "0"):
        return None
    hours = set()
    for seg in hour.split(","):
        if "-" in seg:
            a, b = seg.split("-", 1)
            hours |= set(range(int(a), int(b) + 1))
        elif seg.isdigit():
            hours.add(int(seg))
        else:
            return None
    if dow == "*":
        return None  # 每天高峰 → 与本仓库的「按时段」模型不可比
    days = set()
    for seg in dow.split(","):
        if "-" in seg:
            a, b = seg.split("-", 1)
            days |= set(range(int(a), int(b) + 1))
        elif seg.isdigit():
            days.add(int(seg))
        else:
            return None
    return hours, {7 if d == 0 else d for d in days}


def our_windows(provider: dict):
    peak = provider.get("peak") or {}
    if not peak.get("enabled", True) or not peak.get("windows"):
        return None
    hours, days = set(), set()
    for w in peak["windows"]:
        sh, sm = w["start"].split(":")
        eh, em = w["end"].split(":")
        if sm != "00" or em != "00":
            return None  # 分钟级窗口不参与比对
        hours |= set(range(int(sh), int(eh)))
        days |= set(w["days"])
    return hours, days


def do_diff(snapshot: dict) -> int:
    pdir = os.path.join(ROOT, "rules", "providers")
    rows = []
    for name in sorted(os.listdir(pdir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(pdir, name), encoding="utf-8") as fh:
            provider = json.load(fh)
        ours = our_windows(provider)
        if not ours:
            continue
        gcmp_id = ALIAS.get(provider["id"], provider["id"])
        upstream = snapshot["providers"].get(gcmp_id)
        if not upstream:
            rows.append((provider["id"], "上游无此家", "-", "-"))
            continue
        crons = sorted({t["cron"] for m in upstream["models"] for t in m["tiers"]})
        if not crons:
            rows.append((provider["id"], "上游无峰谷 cron", "-", "-"))
            continue
        verdict = "一致"
        detail = []
        for cron in crons:
            parsed = parse_cron(cron)
            if not parsed:
                verdict = "需人工核对"
                detail.append(f"{cron}（无法解析）")
                continue
            same = parsed[0] == ours[0] and parsed[1] == ours[1]
            verdict = "一致" if same and verdict != "需人工核对" else ("不一致" if not same else verdict)
            detail.append(f"{cron}{'' if same else f' → 上游 {sorted(parsed[0])}时/{(parsed[1]) or chr(42)} 与本地 {sorted(ours[0])}时/{sorted(ours[1])} 不同'}")
        rows.append((provider["id"], verdict, "; ".join(crons), "; ".join(detail)))
    print(f"{'provider':<14}{'比对结果':<12}cron / 说明")
    for pid, verdict, crons, detail in rows:
        print(f"{pid:<14}{verdict:<12}{crons if detail in ('-', '') else detail}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true", help="只做峰谷差异比对，不写文件")
    args = ap.parse_args()
    try:
        snapshot = build_snapshot()
    except Exception as exc:  # noqa: BLE001 - 上游不可达时给出明确提示
        print(f"拉取 GCMP 上游失败：{exc}", file=sys.stderr)
        if args.diff and os.path.exists(OUT):
            print("改用本地已有快照做比对", file=sys.stderr)
            with open(OUT, encoding="utf-8") as fh:
                snapshot = json.load(fh)
        else:
            return 1
    if not args.diff:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"已写入 {OUT}：GCMP {snapshot['gcmp_version']}，{len(snapshot['providers'])} 家 provider")
    return do_diff(snapshot)


if __name__ == "__main__":
    sys.exit(main())
