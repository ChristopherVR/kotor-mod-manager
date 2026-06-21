"""Find all internal links on the mod builds page and then explore each sub-build page."""
import re
import sys
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
DS_RE = re.compile(r"https?://deadlystream\.com/files/file/(\d+)-[^\s\"'<>#]+", re.I)

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0"

# Get the full mod_builds page
r = s.get("https://kotor.neocities.org/modding/mod_builds/", timeout=15)
soup = BeautifulSoup(r.text, "lxml")

# Dump ALL links including internal
base = "https://kotor.neocities.org"
all_links = []
for a in soup.find_all("a", href=True):
    href = a["href"]
    if href.startswith("/"):
        href = base + href
    all_links.append((a.get_text(strip=True)[:50], href))

print("=== ALL LINKS (with text) ===")
for txt, href in all_links:
    print(f"  [{txt}] {href}")

print()
print("=== DS LINKS IN PAGE ===")
ds = DS_RE.findall(r.text)
for d in ds:
    print(f"  {d}")

# Now try to explore each unique /modding/ sub-path
print()
print("=== CHECKING SUB-PAGES ===")
seen = set()
for txt, href in all_links:
    if "/modding/mod_builds" in href and href not in seen:
        seen.add(href)
        try:
            r2 = s.get(href, timeout=10)
            ds2 = DS_RE.findall(r2.text)
            print(f"  [{r2.status_code}] {href} => {len(ds2)} DS links")
            for d in ds2[:3]:
                print(f"      DS: {d}")
        except Exception as e:
            print(f"  FAILED {href}: {e}")
