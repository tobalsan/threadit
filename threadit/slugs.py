"""Area slugs: lowercase name, non-alphanumerics collapsed to '-'."""

import re
import sqlite3


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "area"
    # An all-digit slug would be ambiguous with a numeric area id.
    return f"area-{slug}" if slug.isdigit() else slug


def unique_area_slug(conn: sqlite3.Connection, name: str, area_id: int) -> str:
    """Slug for the area; on collision with another area append '-<id>'."""
    slug = slugify(name)
    while conn.execute(
        "SELECT 1 FROM areas WHERE slug = ? AND id != ?", (slug, area_id)
    ).fetchone():
        slug = f"{slug}-{area_id}"
    return slug
