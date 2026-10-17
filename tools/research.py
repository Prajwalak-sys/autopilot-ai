from ddgs import DDGS


def research_internships(field, location, limit=5):

    query = f"{field} internships for students in {location}"

    results = []

    try:
        with DDGS() as ddgs:

            search_results = ddgs.text(
                query,
                max_results=limit
            )

            for item in search_results:

                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", "")
                })

    except Exception as e:
        raise RuntimeError(
            f"Internship research failed: {e}"
        ) from e

    return results