from mcp.server.fastmcp import FastMCP

from tools.research import research_internships
from tools.spreadsheet import save_internships


mcp = FastMCP("AutoPilot AI Tools")


@mcp.tool()
def search_internships(
    field: str = "AI/ML",
    location: str = "Bengaluru",
    limit: int = 5
) -> list[dict]:
    """Search the web for internship opportunities."""

    limit = max(1, min(limit, 10))

    return research_internships(
        field=field,
        location=location,
        limit=limit
    )


@mcp.tool()
def save_internship_results(
    internships: list[dict]
) -> dict:
    """Save internship results to a CSV spreadsheet."""

    if not internships:
        return {
            "success": False,
            "message": "No internship results were provided."
        }

    result = save_internships(internships)

    return {
        "success": True,
        "file": result["file"],
        "new_entries": result["new_entries"],
        "total_saved": result["total_saved"]
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")