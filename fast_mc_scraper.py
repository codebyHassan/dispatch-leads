"""
Ultra-Fast Bulk MC Carrier Leads Scraper (CLI)
==============================================
- Scrapes live official FMCSA government registries
- Outputs formatted Phone (XXX) XXX-XXXX, Official Email, and MC Months Age
- Multi-threaded parallel performance (50 workers)
"""

import argparse
import concurrent.futures
import csv
import os
import re
import sys
import time
from typing import Dict, List, Optional
from multi_source_scraper import scrape_real_mc


def bulk_scrape_mcs_cli(
    mc_list: List[str],
    workers: int = 50,
    proxy_url: Optional[str] = None,
    output_csv: str = "mc_leads.csv"
):
    print(f"\n🚀 STARTING FAST BULK MC SCRAPER (REAL FMCSA DATA)")
    print(f"==================================================")
    print(f"Total MCs to scrape : {len(mc_list)}")
    print(f"Parallel Workers    : {workers} threads")
    print(f"Output File         : {output_csv}")
    print(f"==================================================\n")

    start_time = time.time()
    results = []
    completed = 0
    total = len(mc_list)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_mc = {
            executor.submit(scrape_real_mc, mc, proxy_url): mc for mc in mc_list
        }

        for future in concurrent.futures.as_completed(future_to_mc):
            try:
                res = future.result()
                results.append(res)
                completed += 1
                if completed % 10 == 0 or completed == total:
                    elapsed = time.time() - start_time
                    speed = completed / max(elapsed, 0.001)
                    sys.stdout.write(f"\rProgress: {completed}/{total} MCs ({completed/total*100:.1f}%) | Speed: {speed:.1f} MCs/sec")
                    sys.stdout.flush()
            except Exception:
                completed += 1

    results.sort(key=lambda r: int(r["mc_number"]) if r["mc_number"].isdigit() else 0)
    elapsed_total = time.time() - start_time
    print(f"\n\n✅ SCRAPING COMPLETED IN {elapsed_total:.2f} SECONDS!")

    if results:
        fieldnames = [
            "mc_number", "dot_number", "entity_type", "status_label",
            "insurance_status", "legal_name", "dba_name", "owner_name", "phone",
            "email", "mc_age_months", "grant_date", "state", "city", "power_units", "drivers", "source"
        ]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "mc_number": r.get("mc_number"),
                    "dot_number": r.get("dot_number"),
                    "entity_type": r.get("entity_type"),
                    "status_label": r.get("status_label"),
                    "insurance_status": r.get("insurance_status"),
                    "legal_name": r.get("legal_name"),
                    "dba_name": r.get("dba_name"),
                    "owner_name": r.get("owner_name"),
                    "phone": r.get("phone"),
                    "email": r.get("email"),
                    "mc_age_months": r.get("mc_age_months"),
                    "grant_date": r.get("grant_date"),
                    "state": r.get("state"),
                    "city": r.get("city"),
                    "power_units": r.get("power_units"),
                    "drivers": r.get("drivers"),
                    "source": r.get("source"),
                })

        print(f"📁 Leads saved to: {os.path.abspath(output_csv)}")
        print(f"📊 Sample Row:")
        first = results[0]
        print(f"   MC #{first['mc_number']} | {first['legal_name']} | Phone: {first['phone']} | Email: {first['email']} | Age: {first['mc_age_months']} | Status: {first['status_label']}")


def main():
    parser = argparse.ArgumentParser(description="Fastest Bulk MC Trucking Carrier Lead Scraper")
    parser.add_argument("--start-mc", type=int, help="Starting MC Number (e.g. 1811001)")
    parser.add_argument("--count", type=int, default=50, help="Number of MCs to scrape (default: 50)")
    parser.add_argument("--mcs", type=str, help="Comma-separated MC numbers (e.g. 1811001,1811002)")
    parser.add_argument("--file", type=str, help="Text/CSV file containing MC numbers")
    parser.add_argument("--workers", type=int, default=50, help="Parallel worker threads (default: 50)")
    parser.add_argument("--output", type=str, default="mc_leads.csv", help="Output CSV filename")
    parser.add_argument("--proxy", type=str, help="Proxy URL (optional)")

    args = parser.parse_args()

    mc_list = []
    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                c = re.sub(r"\D", "", line.strip())
                if c:
                    mc_list.append(c)
    elif args.mcs:
        mc_list = [re.sub(r"\D", "", x) for x in args.mcs.split(",") if re.sub(r"\D", "", x)]
    elif args.start_mc:
        mc_list = [str(args.start_mc + i) for i in range(args.count)]
    else:
        start = 1811001
        mc_list = [str(start + i) for i in range(args.count or 50)]

    bulk_scrape_mcs_cli(mc_list=mc_list, workers=args.workers, proxy_url=args.proxy, output_csv=args.output)


if __name__ == "__main__":
    main()
