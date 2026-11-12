"""
prep_ecearth3_psl_esgf.py - DAILY sea-level pressure (psl) of EC-Earth3 historical r1i1p1f1 (CMIP6, grid gr),
1981-2014, downloaded from ESGF: the pressure field of the analogue step of the supervisor's pipeline (the other
historical variables, tasmax / tasmin / pr / rsds, come from the same run and member).

Source: ESGF dataset CMIP6.CMIP.EC-Earth-Consortium.EC-Earth3.historical.r1i1p1f1.day.psl.gr, version 20200310 (the
standard CMIP6 EC-Earth3, T255 / ORCA1, as the b025 / b050 runs of Meccia et al. 2023). The file list (URL and SHA256)
comes from the ESGF wget script of 12 Nov 2026 (CEDA data node), restricted to 1981-2014: 34 yearly files, about 4.6 GB.
With --wget-script another ESGF wget script (another data node or variable) can be used instead of the list below.

Each file is written as <name>.part and renamed only once its SHA256 checksum matches; files already present are skipped,
so the script can be stopped and restarted.

Usage (JEO-lab terminal, from the repository folder):
  nohup python prep_ecearth3_psl_esgf.py > ~/psl_esgf.log 2>&1 &
  tail -3 ~/psl_esgf.log
"""
import argparse
import hashlib
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

DST = Path("/eos/jeodpp/data/projects/DROUGHTOBS/elisa/GCM_downscaling/Input_data/EC-Earth3_historical_CMIP6")
YEARS = (1981, 2014)
FILES = [   # (file name, URL, SHA256): CEDA data node, wget script of 12 Nov 2026
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19810101-19811231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19810101-19811231.nc",
     "a7f1e8781bcf4225522ecdf2f63b2c6b0d0d529a4896f40ca54fc48b8064b0dd"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19820101-19821231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19820101-19821231.nc",
     "58d02ec3d41f73c5d0bd33f121d371bdb05f93139c1e20108755ea05012a58d5"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19830101-19831231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19830101-19831231.nc",
     "0f2eaf4cb67a8ac5852589873401b0c13f8f1526bea1a46f20fae5d4198c48f6"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19840101-19841231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19840101-19841231.nc",
     "fde2cadcaec73476b534a185b25b1ea81ca39e6ac48bc167db1c6a3fe608e29a"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19850101-19851231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19850101-19851231.nc",
     "1f45008c502618abe60a222a6ef614ed08a0c9344ecf847b47346f5420da6fff"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19860101-19861231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19860101-19861231.nc",
     "6ffcfc18128887e9676f3a53e1c97df1b7b5f504a159c9110de969277b2ed128"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19870101-19871231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19870101-19871231.nc",
     "6a7d9f1b4a14de17f29e0c4943f338d394f4c08083ac5afcb7124d785e7bac18"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19880101-19881231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19880101-19881231.nc",
     "4ad4191cbb6ed5a354b7a8e0def47e140eb28ebcce64643412ad76c4d6464945"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19890101-19891231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19890101-19891231.nc",
     "0964a8f84859785ede9c670c89dfb760cff2e018d1d594989ce854634d0e6124"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19900101-19901231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19900101-19901231.nc",
     "e9b033a9f51cbb20272a154286c623f9a56cb96b607419cab8628cfb032ec0b2"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19910101-19911231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19910101-19911231.nc",
     "c4fecf05097281542bf18446cb2943f7b4b813eecc7adf8caed6e303e885f227"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19920101-19921231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19920101-19921231.nc",
     "90f6d5c7f9d51b445d4ab1849af774d8ae7c47bf381c21477c6a93745d6cab85"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19930101-19931231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19930101-19931231.nc",
     "fddfb5c335d71d9add13fc5052f8b34cc28c1f83c245bfce9f09c9beb10eaba3"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19940101-19941231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19940101-19941231.nc",
     "ca2740620bfe26ff7f4dcf4c7f6db176e2fcc6eb7bc7efdeec15064db750677c"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19950101-19951231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19950101-19951231.nc",
     "fccdf789cda568965fca902ed14603e2608f22fd082745880f995149cb6cbca8"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19960101-19961231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19960101-19961231.nc",
     "a689cd339575bda64341fb01dbe368001da0854dc0d2b2cd052d0789c35f26eb"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19970101-19971231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19970101-19971231.nc",
     "0192f6a94b6dc634b8cd4b7a67859f42a79ff7b4ad3e733bd69a6cff7b43f53b"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19980101-19981231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19980101-19981231.nc",
     "eab07d3c2ea2974a99e59823b51db7b3fe34eef14c06111a3abcbc132d935372"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_19990101-19991231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_19990101-19991231.nc",
     "e94e8263c8f7562b5b267f71bede4e4c035a708de8d9e43976122bb4aa92680f"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20000101-20001231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20000101-20001231.nc",
     "b5817d3a5cfe7eace40eeae07f6e94c547b1e909d5a13d3fb4e55c6f8302b9c1"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20010101-20011231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20010101-20011231.nc",
     "dc1ee07b8ed86570184eba08f0fe653508b0e014f573aeaf48c700fb397d1caa"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20020101-20021231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20020101-20021231.nc",
     "03b1ccda8223f0607606c25d94201ba9add1fa8b90ff7b5993cbe20664f2bfbe"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20030101-20031231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20030101-20031231.nc",
     "fa0f8087fa9cba2b60df3bbe87beebc0e1b0b7de12e3f0389b2b52e312428748"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20040101-20041231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20040101-20041231.nc",
     "5286dd9097f69f5a2ad6a9084389d0f86bf08b92af1dbd7d20fba3b77000738a"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20050101-20051231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20050101-20051231.nc",
     "1ccf404401e1cc8b28868e90e6fe60e2ade8c44a000a8ce7ff1f5e069dc9512a"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20060101-20061231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20060101-20061231.nc",
     "e8b8279e001a049e81d64e8036bf34ef1434bd4a7402a13ec57bbeb15ab4a878"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20070101-20071231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20070101-20071231.nc",
     "68629a8812ddaa85ea91cb57c864127864cb698693d857e0d37ce922dbe7c6c8"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20080101-20081231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20080101-20081231.nc",
     "a9d29628172280cd2c803894dc1e393d0b0087b501f956cc480f29803b6bd1c4"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20090101-20091231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20090101-20091231.nc",
     "5d9722a33f4a3c8e74a1045e12475b637c47092f8d7dd0b2653ae318c7ec04dc"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20100101-20101231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20100101-20101231.nc",
     "8efc8bc0bc5da1bb118c2e25cf8d049d4f669655c361bfab077c482004509e8f"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20110101-20111231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20110101-20111231.nc",
     "fa75ea72fc8c321f2e19e555bb5a4c998eb649692b8a7f528631e7d9d9df7697"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20120101-20121231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20120101-20121231.nc",
     "2c42d82a7bff00f5cb1c3a2d89a4c63d922e098109764d3892e934131f45b885"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20130101-20131231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20130101-20131231.nc",
     "b87c707c1712c2ad87a30470c7f724977e9985aa662dce8188e2a1b20e5bdf98"),
    ("psl_day_EC-Earth3_historical_r1i1p1f1_gr_20140101-20141231.nc",
     "https://esgf.ceda.ac.uk/thredds/fileServer/esg_cmip6/CMIP6/CMIP/EC-Earth-Consortium/EC-Earth3/historical/r1i1p1f1/day/psl/gr/v20200310/psl_day_EC-Earth3_historical_r1i1p1f1_gr_20140101-20141231.nc",
     "e3c4d2eebe855386ead1af2d276163269e4e4b0baff4c1e14db8f4e38b416719"),
]


def from_wget_script(path, years):
    """(file name, URL, SHA256) of the files of an ESGF wget script whose first year lies in `years`."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    ent = re.findall(r"'([^']+\.nc)'\s+'(https?://[^']+)'\s+'SHA256'\s+'([a-f0-9]+)'", text)
    first = lambda fn: int(re.search(r"_(\d{4})\d{4}-\d{8}\.nc$", fn).group(1))
    return [e for e in ent if years[0] <= first(e[0]) <= years[1]]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def download(url, dest, chk, ctx, tries=3):
    part = dest.with_name(dest.name + ".part")
    for k in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=300) as resp, open(part, "wb") as f:
                while True:
                    block = resp.read(1 << 22)
                    if not block:
                        break
                    f.write(block)
            if sha256(part) != chk:
                raise IOError("SHA256 checksum does not match")
            part.rename(dest)
            return True
        except Exception as exc:
            print(f"    try {k}/{tries} failed: {exc}", flush=True)
            part.unlink(missing_ok=True)
            time.sleep(30 * k)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dst", default=str(DST), help="output folder (default: %(default)s)")
    ap.add_argument("--wget-script", help="ESGF wget script to read the file list from (default: the list in this file)")
    ap.add_argument("--start", type=int, default=YEARS[0])
    ap.add_argument("--end", type=int, default=YEARS[1])
    ap.add_argument("--no-verify-ssl", action="store_true",
                    help="do not check the server certificate (only for a data node with a broken certificate chain; "
                         "the SHA256 checksum of each file is still checked)")
    a = ap.parse_args()
    if a.wget_script:
        files = from_wget_script(a.wget_script, (a.start, a.end))
    else:
        files = [e for e in FILES if a.start <= int(re.search(r"_gr_(\d{4})", e[0]).group(1)) <= a.end]
    dst = Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    if a.no_verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    print(f"{len(files)} files -> {dst}", flush=True)
    failed = []
    for i, (fn, url, chk) in enumerate(files, 1):
        dest = dst / fn
        if dest.exists():
            print(f"[{i:2d}/{len(files)}] present   {fn}", flush=True)
            continue
        t0 = time.time()
        ok = download(url, dest, chk, ctx)
        print(f"[{i:2d}/{len(files)}] {'done' if ok else 'FAILED':9s} {fn} ({time.time() - t0:.0f} s)", flush=True)
        if not ok:
            failed.append(fn)
    if failed:
        print(f"{len(failed)} files failed: run the script again (or --wget-script with the script of another data node)")
        sys.exit(1)
    print("PSL_DONE")


if __name__ == "__main__":
    main()
