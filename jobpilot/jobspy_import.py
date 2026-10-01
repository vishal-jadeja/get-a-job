"""Optional broader discovery. Install python-jobspy separately; not needed by the app."""
import argparse
import json
from pathlib import Path
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Discover jobs with optional JobSpy using your runtime profile")
    parser.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "data"))
    parser.add_argument("--sites", nargs="+", choices=["indeed", "google", "zip_recruiter", "glassdoor", "linkedin"], default=["indeed"])
    parser.add_argument("--country", default="india", help="Country supported by the selected board")
    parser.add_argument("--location", help="Overrides the location in your profile")
    parser.add_argument("--limit", type=int, default=30, help="Results per role and board, maximum 100")
    args = parser.parse_args()
    try:
        from jobspy import scrape_jobs
    except ImportError:
        parser.error("Optional dependency missing. In your virtual environment: pip install python-jobspy")
    from .transfer import active_directory
    store = Store(active_directory(args.data))
    profile = store.setting("profile")
    if not profile["roles"]:
        parser.error("Complete your profile in JobPilot first; role suggestions are generated at runtime")
    location = args.location or profile.get("location")
    if not location:
        parser.error("Set your profile location or pass --location")
    total = 0
    for role in profile["roles"][:8]:
        print(f"Searching {role} in {location}…", flush=True)
        try:
            frame = scrape_jobs(site_name=args.sites, search_term=role, location=location,
                                google_search_term=f"{role} jobs in {location}",
                                results_wanted=max(1, min(args.limit, 100)), country_indeed=args.country,
                                hours_old=min(168, profile["max_age_days"] * 24), description_format="markdown")
            added = 0
            for row in json.loads(frame.to_json(orient="records", date_format="iso")):
                if not row.get("title") or not row.get("company") or not row.get("job_url"):
                    continue
                try:
                    added += store.import_discovered_jobs([{"title": row["title"], "company": row["company"],
                        "url": row.get("job_url_direct") or row["job_url"], "location": row.get("location", ""),
                        "description": row.get("description", ""), "source": row.get("site", "jobspy"),
                        "posted_at": row.get("date_posted", ""), "remote": row.get("is_remote", False)}])
                except ValueError as exc:
                    print("Skipped invalid posting:", exc)
            total += added
            print(f"Imported {added} new jobs for this role")
        except Exception as exc:
            print(f"Source failed for {role}: {exc}")
    print(f"Done. {total} new opportunities in your workspace.")


if __name__ == "__main__":
    main()
