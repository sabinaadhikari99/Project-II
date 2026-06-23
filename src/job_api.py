import os
from urllib.parse import urlencode

from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

APIFY_API_TOKEN = (os.getenv("APIFY_API_TOKEN") or os.getenv("APIFY_TOKEN") or "").strip()
LINKEDIN_ACTOR_ID = os.getenv("LINKEDIN_ACTOR_ID", "hKByXkMQaC5Qt9UMN").strip()


def _normalize_job(item: dict) -> dict:
    return {
        "title": item.get("title") or item.get("jobTitle") or item.get("positionName") or "Untitled role",
        "company": item.get("companyName") or item.get("company") or item.get("company_name") or "Company not listed",
        "location": item.get("location") or item.get("jobLocation") or "Location not listed",
        "link": item.get("link") or item.get("url") or item.get("jobUrl") or "https://www.linkedin.com/jobs/",
    }


def fetch_linkedin_jobs(search_query: str, location: str = "Nepal", rows: int = 60) -> list[dict]:
    if not APIFY_API_TOKEN:
        raise RuntimeError("APIFY_API_TOKEN or APIFY_TOKEN is missing in the .env file.")

    query_params = urlencode({"keywords": search_query, "location": location})
    url = f"https://www.linkedin.com/jobs/search/?{query_params}"

    run_input = {
        "urls": [url],
        "rows": rows,
        "maxItems": rows,
        "proxy": {"useApifyProxy": True},
    }

    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(LINKEDIN_ACTOR_ID).call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []

    jobs = list(client.dataset(dataset_id).iterate_items())
    return [_normalize_job(job) for job in jobs[:rows]]
