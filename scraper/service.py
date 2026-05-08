from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from scraper.extractors import scrape_source
from scraper.models import SourceSite

ProgressCallback = Callable[[int, int, str], None]


def scrape_sources(sources: list[SourceSite], progress_cb: ProgressCallback | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if progress_cb:
            progress_cb(index - 1, total, f"Scraping {source.source_label}")
        records = scrape_source(source)
        rows.extend(record.as_dict() for record in records)
        if progress_cb:
            progress_cb(index, total, f"Finished {source.source_label}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["event_name", "venue_name", "start_date", "start_time"], keep="first")
    df = df.sort_values(by=["venue_name", "start_date", "start_time"], ascending=True, na_position="last")
    return df


def project_to_target_schema(df: pd.DataFrame, target_fields: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    mapping = {
        "Entered": "entered",
        "SpecialGuests": "special_guests",
        "DoorsOpen": "doors_open",
        "Ages": "ages",
        "Free": "is_free",
        "CoverPrice": "cover_price",
        "Advance": "advance",
        "DayOfShow": "day_of_show",
        "TicketsStartAt": "tickets_start_at",
        "TicketsEndAt": "tickets_end_at",
        "FoodDrinkMinimum": "food_drink_minimum",
        "id": "event_id",
        "type": "record_type",
        "name": "event_name",
        "venuesName": "venue_name",
        "venuesID": "venue_id",
        "zipCode": "zip_code",
        "timeZone": "time_zone",
        "images": "images",
        "startDate": "start_date",
        "startTime": "start_time",
        "endTime": "end_time",
        "description": "description",
        "eventsUrl": "event_url",
        "venueTicketsURL": "tickets_url",
        "city": "city",
        "state": "state",
        "address": "address",
        "eventType": "event_type",
        "eventSubtype": "event_subtype",
        "Price": "price",
    }

    output = pd.DataFrame()
    for field in target_fields:
        source_column = mapping.get(field)
        output[field] = df[source_column] if source_column in df.columns else None

    for helper in ["source", "category", "event_url"]:
        if helper in df.columns and helper not in output.columns:
            output[helper] = df[helper]
    return output
