import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("mod_analysis.json", encoding="utf-8") as f:
    mods = json.load(f)

sample_ids = {"1313", "491", "1487", "2321", "2729", "2785", "1090", "824"}

for m in mods:
    fid = m["file_id"]
    if fid in sample_ids:
        hints = m.get("install_hints", [])
        url = m["url"]
        name = m.get("title") or m["name"]
        print(f"{fid:6s}  {url}")
        print(f"         {name[:60]}  hints={hints}")
