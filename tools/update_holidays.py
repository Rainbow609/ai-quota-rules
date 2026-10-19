#!/usr/bin/env python3
"""拉取中国大陆法定节假日数据，写入 rules/holidays/cn.json。

数据源：NateScarlet/holiday-cn（每日自动抓取国务院公告）。只保留「放假日」(isOffDay=true)：
DeepSeek 的平峰判定是「周一至周五且非法定节假日」，调休上班的周末不落在高峰窗口内，故不纳入。

用法：python3 tools/update_holidays.py [year ...]   # 默认今年 + 明年
"""
import json
import os
import sys
import urllib.request
from datetime import date, timezone, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "rules", "holidays", "cn.json")

SOURCES = [
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
]
ATTRIBUTION = "https://github.com/NateScarlet/holiday-cn"


def fetch(year: int) -> dict:
    last = None
    for tpl in SOURCES:
        url = tpl.format(year=year)
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - 逐个源尝试，最后统一报错
            last = exc
    raise SystemExit(f"拉取 {year} 年节假日数据失败：{last}")


def main() -> None:
    year = date.today().year
    years = [int(a) for a in sys.argv[1:]] or [year, year + 1]
    days: list[str] = []
    ok: list[int] = []
    for y in years:
        try:
            data = fetch(y)
        except SystemExit as exc:  # 次年安排通常要到当年 11-12 月才公布
            print(f"跳过 {y}：{exc}", file=sys.stderr)
            continue
        ok.append(y)
        days += sorted(x["date"] for x in data.get("days", []) if x.get("isOffDay"))
    if not ok:
        raise SystemExit("所有年份都拉取失败，未写入文件")
    years = ok
    payload = {
        "source": ATTRIBUTION,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "days": sorted(set(days)),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"写入 {OUT}：{len(payload['days'])} 个放假日（{', '.join(map(str, years))}）")


if __name__ == "__main__":
    main()
