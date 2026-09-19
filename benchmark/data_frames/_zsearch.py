import requests, json, sys
q = sys.argv[1]
size = int(sys.argv[2]) if len(sys.argv) > 2 else 20
r = requests.get("https://zenodo.org/api/records",
                 params={"q": q, "size": size, "sort": "mostrecent"},
                 timeout=60)
r.raise_for_status()
hits = r.json()["hits"]
print("total:", hits["total"])
for h in hits["hits"]:
    md = h["metadata"]
    files = h.get("files", [])
    tot = sum(f.get("size", 0) for f in files) / 1e9
    lic = md.get("license", {}).get("id", "?")
    print(f'- {h["id"]} | {md.get("publication_date","?")} | {lic} | {tot:.2f} GB | {md["title"][:110]}')
