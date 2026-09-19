import requests, sys, re, html
for rid in sys.argv[1:]:
    r = requests.get(f"https://zenodo.org/api/records/{rid}", timeout=60)
    r.raise_for_status()
    j = r.json()
    md = j["metadata"]
    print("=" * 80)
    print(f'ID {rid} | DOI {j.get("doi")} | license {md.get("license",{}).get("id")}')
    print("TITLE:", md["title"])
    desc = re.sub(r"<[^>]+>", " ", md.get("description", ""))
    desc = html.unescape(re.sub(r"\s+", " ", desc)).strip()
    print("DESC:", desc[:1200])
    print("FILES:")
    for f in j.get("files", []):
        print(f'  {f["key"]}  {f["size"]/1e9:.3f} GB  {f["links"]["self"]}')
