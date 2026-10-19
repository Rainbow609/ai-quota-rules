#!/usr/bin/env python3
"""把 rules/ 合并为 dist/ruleset.json，并生成 dist/manifest.json（版本 + sha256 + 大小）。

版本号：日期制 `YYYY.MM.DD.N`，同一天多次构建则 N 自增（读现有 manifest 续号），
保证客户端可用字符串比较判新旧，不依赖时间戳。
"""
import hashlib
import json
import os
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "rules")
DIST = os.path.join(ROOT, "dist")
MIN_CLIENT_VERSION = "0.1.0"


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def next_version() -> str:
    env = os.environ.get("RULESET_VERSION")
    if env:
        return env
    today = date.today().strftime("%Y.%m.%d")
    current = None
    manifest = os.path.join(DIST, "manifest.json")
    if os.path.exists(manifest):
        try:
            current = load(manifest).get("version")
        except json.JSONDecodeError:
            current = None
    if current and current.startswith(today + "."):
        return f"{today}.{int(current.rsplit('.', 1)[1]) + 1}"
    return f"{today}.1"


def main() -> None:
    pdir = os.path.join(RULES, "providers")
    providers = [load(os.path.join(pdir, n)) for n in sorted(os.listdir(pdir)) if n.endswith(".json")]

    holidays = {}
    hdir = os.path.join(RULES, "holidays")
    if os.path.isdir(hdir):
        for n in sorted(os.listdir(hdir)):
            if n.endswith(".json"):
                data = load(os.path.join(hdir, n))
                holidays[n[:-5]] = {
                    "source": data.get("source", ""),
                    "updated_at": data.get("updated_at", ""),
                    "days": data.get("days", []),
                }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ruleset = {
        "schema_version": "1",
        "ruleset_version": next_version(),
        "generated_at": now,
        "min_client_version": MIN_CLIENT_VERSION,
        "holidays": holidays,
        "providers": providers,
    }
    body = json.dumps(ruleset, ensure_ascii=False, indent=2) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    manifest = {
        "schema_version": "1",
        "version": ruleset["ruleset_version"],
        "generated_at": now,
        "min_client_version": MIN_CLIENT_VERSION,
        "checksum": {"algorithm": "sha256", "sha256": digest},
        "size": len(body.encode("utf-8")),
        "paths": {"ruleset": "dist/ruleset.json", "mirrors": "mirrors/mirrors.json"},
        "provider_ids": [p["id"] for p in providers],
    }

    os.makedirs(DIST, exist_ok=True)
    with open(os.path.join(DIST, "ruleset.json"), "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(DIST, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(
        f"已构建 ruleset {manifest['version']}：{len(providers)} 个 provider，"
        f"{manifest['size']} 字节，sha256={digest[:16]}…"
    )


if __name__ == "__main__":
    main()
