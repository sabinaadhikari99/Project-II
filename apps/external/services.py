from urllib.parse import urlencode

from django.conf import settings

from apps.shared.performance import PerformanceTimer


def _normalize_job(item: dict) -> dict:
    link = item.get("link") or item.get("url") or item.get("jobUrl") or "https://www.linkedin.com/jobs/"
    return {
        "title": item.get("title") or item.get("jobTitle") or item.get("positionName") or "Untitled role",
        "company": item.get("companyName") or item.get("company") or item.get("company_name") or "Company not listed",
        "location": item.get("location") or item.get("jobLocation") or "Location not listed",
        "url": link,
        "source": item.get("source") or "linkedin",
    }


def fetch_linkedin_jobs(query: str, location: str = "", limit: int = 10):
    timer = PerformanceTimer("fetch_linkedin_jobs")

    if settings.APIFY_TOKEN:
        try:
            from apify_client import ApifyClient

            with timer.measure("ApifyClient — init"):
                client = ApifyClient(settings.APIFY_TOKEN)

            search_url = "https://www.linkedin.com/jobs/search/?" + urlencode(
                {"keywords": query, "location": location}
            )
            run_input = {
                "urls": [search_url],
                "rows": limit,
                "maxItems": limit,
                "proxy": {"useApifyProxy": True},
            }

            with timer.measure("ApifyClient — actor call"):
                run = client.actor(settings.LINKEDIN_ACTOR_ID).call(run_input=run_input)

            dataset_id = run.get("defaultDatasetId")
            if dataset_id:
                with timer.measure("ApifyClient — iterate items"):
                    jobs = list(client.dataset(dataset_id).iterate_items())[:limit]

                with timer.measure("Normalize jobs"):
                    result = [_normalize_job(job) for job in jobs]

                timer.flush("fetch_linkedin_jobs (Apify path)")
                return result
        except Exception:
            timer.flush("fetch_linkedin_jobs (Apify — failed)")
            pass

    with timer.measure("Return mock data"):
        result = [
            {
                "title": f"{query or 'Software'} Engineer",
                "company": "Demo LinkedIn Company",
                "location": location or "Remote",
                "url": "https://www.linkedin.com/jobs/",
                "source": "mock",
            }
        ]

    timer.flush("fetch_linkedin_jobs (mock path)")
    return result
