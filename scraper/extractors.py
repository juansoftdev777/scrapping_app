from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from scraper.models import EventRecord, SourceSite

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def normalize_name(value: str | None) -> str | None:
    if not value:
        return value
    text = re.sub(r"\s+", " ", value).strip().strip(",:-|")

    # Remove leading season/year prefixes like "2025, ..." or "2025-2026: ..."
    text = re.sub(
        r"^(?:\d{4}(?:\s*[-/]\s*\d{2,4})?(?:\s+season)?)\s*[,:\-|]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:season\s+)?\d{4}(?:\s*[-/]\s*\d{2,4})\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip() or value.strip()


def fetch_html(url: str, timeout: int = 20) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def normalize_datetime(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        parsed = parse_datetime(value)
    except (ValueError, TypeError, OverflowError):
        return value, None
    return parsed.date().isoformat(), parsed.strftime("%H:%M")


def _iter_event_objects(payload: object) -> list[dict]:
    output: list[dict] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            event_type = node.get("@type")
            if event_type == "Event" or (isinstance(event_type, list) and "Event" in event_type):
                output.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return output


def _parse_jsonld_events(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        content = (script.string or script.text or "").strip()
        if not content:
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        events.extend(_iter_event_objects(payload))
    return events


def _value_text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("name", "@id", "url", "text"):
            if key in value and isinstance(value[key], str):
                return value[key].strip() or None
    return None


def _to_offer_list(offers: object) -> list[dict]:
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [item for item in offers if isinstance(item, dict)]
    return []


def _extract_ticket_fields(offers: object) -> dict[str, str | int | None]:
    offer_list = _to_offer_list(offers)
    if not offer_list:
        return {
            "price": None,
            "cover_price": None,
            "advance": None,
            "day_of_show": None,
            "tickets_start_at": None,
            "tickets_end_at": None,
            "tickets_url": None,
            "is_free": None,
        }

    first = offer_list[0]
    price_value = _value_text(first.get("price")) or _value_text(first.get("lowPrice"))
    if not price_value and isinstance(first.get("priceSpecification"), dict):
        spec = first["priceSpecification"]
        price_value = _value_text(spec.get("price")) or _value_text(spec.get("minPrice"))
    tickets_url = _value_text(first.get("url"))
    tickets_start_at, _ = normalize_datetime(_value_text(first.get("validFrom")))
    tickets_end_at, _ = normalize_datetime(_value_text(first.get("availabilityEnds")))

    # Heuristic splits when multiple offers include advance/day-of-show wording.
    advance = None
    day_of_show = None
    for offer in offer_list:
        label = (_value_text(offer.get("name")) or "").lower()
        price = _value_text(offer.get("price")) or _value_text(offer.get("lowPrice"))
        if not price:
            continue
        if "advance" in label:
            advance = price
        if "day" in label and "show" in label:
            day_of_show = price

    free_flag: int | None = None
    if isinstance(first.get("price"), (int, float)) and float(first["price"]) == 0:
        free_flag = 1
    if isinstance(first.get("price"), str):
        cleaned = first["price"].strip().lower()
        if cleaned in {"0", "0.0", "$0", "free"}:
            free_flag = 1
    if price_value and str(price_value).replace("$", "").strip() in {"0", "0.0", "0.00"}:
        free_flag = 1

    return {
        "price": price_value,
        "cover_price": price_value,
        "advance": advance,
        "day_of_show": day_of_show,
        "tickets_start_at": tickets_start_at,
        "tickets_end_at": tickets_end_at,
        "tickets_url": tickets_url,
        "is_free": free_flag,
    }


def _extract_text_fields(text: str) -> dict[str, str | int | None]:
    blob = text or ""
    blob_lower = blob.lower()

    ages_match = re.search(
        r"\b(all ages|\d{1,2}\+|\d{1,2}\s*&\s*over|\d{1,2}\s+and\s+over)\b",
        blob,
        flags=re.IGNORECASE,
    )
    doors_match = re.search(
        r"\bdoors?\s*(?:open)?\s*(?:at)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        blob,
        flags=re.IGNORECASE,
    )
    adv_match = re.search(
        r"\badvance\b[^$]{0,20}\$(\d+(?:\.\d{2})?)",
        blob,
        flags=re.IGNORECASE,
    )
    dos_match = re.search(
        r"\bday\s*of\s*show\b[^$]{0,20}\$(\d+(?:\.\d{2})?)",
        blob,
        flags=re.IGNORECASE,
    )
    cover_match = re.search(r"\b(?:cover|price|tickets?\s+start\s+at)\b[^$]{0,20}\$(\d+(?:\.\d{2})?)", blob, flags=re.IGNORECASE)
    minimum_match = re.search(r"\b(?:minimum|food\s*&?\s*drink\s*minimum)\b[^$]{0,20}\$(\d+(?:\.\d{2})?)", blob, flags=re.IGNORECASE)
    free_flag = 1 if "free" in blob_lower and ("admission" in blob_lower or "entry" in blob_lower or "event" in blob_lower) else None

    return {
        "ages": ages_match.group(1) if ages_match else None,
        "doors_open": doors_match.group(1) if doors_match else None,
        "advance": f"${adv_match.group(1)}" if adv_match else None,
        "day_of_show": f"${dos_match.group(1)}" if dos_match else None,
        "cover_price": f"${cover_match.group(1)}" if cover_match else None,
        "food_drink_minimum": f"${minimum_match.group(1)}" if minimum_match else None,
        "is_free": free_flag,
    }


def _extract_special_guests(raw: dict) -> str | None:
    performer = raw.get("performer")
    names: list[str] = []
    if isinstance(performer, dict):
        name = _value_text(performer.get("name"))
        if name:
            names.append(name)
    elif isinstance(performer, list):
        for item in performer:
            if isinstance(item, dict):
                name = _value_text(item.get("name"))
                if name:
                    names.append(name)
    return ", ".join(names[1:]) if len(names) > 1 else None


def _normalize_lookup_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    tokens = [t for t in cleaned.split() if t not in {"the", "and", "at", "room", "hall"}]
    return " ".join(tokens).strip()


def _names_match(source_name: str, venue_name: str) -> bool:
    left = _normalize_lookup_name(source_name)
    right = _normalize_lookup_name(venue_name)
    if not left or not right:
        return False
    return left in right or right in left


def _extract_age_text(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        match = re.search(r"\b(all ages|\d{1,2}\+|\d{1,2}\s*&\s*over|\d{1,2}\s+and\s+over)\b", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_ticketmaster_key(html: str) -> str | None:
    match = re.search(r'w-tmapikey="([^"]+)"', html, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _price_from_ranges(price_ranges: object) -> tuple[str | None, str | None, str | None, int | None]:
    if not isinstance(price_ranges, list) or not price_ranges:
        return None, None, None, None
    values: list[float] = []
    for item in price_ranges:
        if not isinstance(item, dict):
            continue
        for key in ("min", "max"):
            value = item.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
    if not values:
        return None, None, None, None

    min_price = min(values)
    max_price = max(values)
    price = str(min_price).rstrip("0").rstrip(".")
    advance = str(min_price).rstrip("0").rstrip(".")
    day_of_show = str(max_price).rstrip("0").rstrip(".") if max_price > min_price else None
    is_free = 1 if min_price == 0 and max_price == 0 else 0
    return price, advance, day_of_show, is_free


def _map_ticketmaster_event(source: SourceSite, event: dict) -> EventRecord:
    venue = ((event.get("_embedded") or {}).get("venues") or [{}])[0]
    dates = event.get("dates") or {}
    start = dates.get("start") or {}
    end = dates.get("end") or {}
    access = dates.get("access") or {}
    sales = event.get("sales") or {}
    public_sales = sales.get("public") or {}
    classifications = event.get("classifications") or []
    classification = classifications[0] if classifications and isinstance(classifications[0], dict) else {}
    price, advance, day_of_show, is_free = _price_from_ranges(event.get("priceRanges"))

    start_date = _value_text(start.get("localDate"))
    start_time = _value_text(start.get("localTime"))
    end_time = _value_text(end.get("localTime"))
    _, doors_open = normalize_datetime(_value_text(access.get("startDateTime")))
    tickets_start_at, _ = normalize_datetime(_value_text(public_sales.get("startDateTime")))
    tickets_end_at, _ = normalize_datetime(_value_text(public_sales.get("endDateTime")))

    attractions = (event.get("_embedded") or {}).get("attractions") or []
    guests: list[str] = []
    for attraction in attractions:
        if not isinstance(attraction, dict):
            continue
        name = _value_text(attraction.get("name"))
        if name:
            guests.append(name)

    info_text = _value_text(event.get("info"))
    note_text = _value_text(event.get("pleaseNote"))
    return EventRecord(
        source=source.source_label,
        category=source.category,
        venue_name=_value_text(venue.get("name")) or source.venue_name,
        special_guests=", ".join(guests[1:]) if len(guests) > 1 else None,
        doors_open=doors_open,
        ages=_extract_age_text(info_text, note_text),
        is_free=is_free,
        event_name=normalize_name(_value_text(event.get("name"))),
        event_id=_value_text(event.get("id")),
        record_type=_value_text(event.get("type")),
        cover_price=price,
        advance=advance,
        day_of_show=day_of_show,
        tickets_start_at=tickets_start_at,
        tickets_end_at=tickets_end_at,
        start_date=start_date,
        start_time=start_time,
        end_time=end_time,
        description=info_text or note_text,
        event_url=_value_text(event.get("url")),
        tickets_url=_value_text(event.get("url")),
        venue_id=_value_text(venue.get("id")),
        zip_code=_value_text(venue.get("postalCode")),
        time_zone=_value_text(dates.get("timezone")),
        city=_value_text((venue.get("city") or {}).get("name")) if isinstance(venue, dict) else None,
        state=(
            _value_text((venue.get("state") or {}).get("stateCode")) or _value_text((venue.get("state") or {}).get("name"))
            if isinstance(venue, dict)
            else None
        ),
        address=_value_text((venue.get("address") or {}).get("line1")) if isinstance(venue, dict) else None,
        price=price,
        event_type=_value_text((classification.get("segment") or {}).get("name")) if isinstance(classification, dict) else None,
        event_subtype=_value_text((classification.get("genre") or {}).get("name")) if isinstance(classification, dict) else None,
        images=_value_text((event.get("images") or [{}])[0].get("url")) if isinstance(event.get("images"), list) else None,
        raw_payload=event,
    )


def _scrape_ticketmaster_widget(source: SourceSite, html: str) -> list[EventRecord]:
    key = _extract_ticketmaster_key(html)
    if not key:
        return []

    try:
        response = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params={
                "apikey": key,
                "keyword": source.venue_name,
                "size": 200,
                "sort": "date,asc",
                "countryCode": "US",
            },
            headers=HEADERS,
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    payload = response.json()
    events = payload.get("_embedded", {}).get("events", [])
    records: list[EventRecord] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        venue = ((event.get("_embedded") or {}).get("venues") or [{}])[0]
        venue_name = _value_text(venue.get("name")) or ""
        if not _names_match(source.venue_name, venue_name):
            continue
        records.append(_map_ticketmaster_event(source, event))
    return records


def map_event_data(source: SourceSite, raw: dict, source_url: str) -> EventRecord:
    start_date, start_time = normalize_datetime(_value_text(raw.get("startDate")))
    _, end_time = normalize_datetime(_value_text(raw.get("endDate")))
    location = raw.get("location") or {}
    address = location.get("address") if isinstance(location, dict) else {}
    offers = raw.get("offers") or {}
    ticket_fields = _extract_ticket_fields(offers)
    free_from_raw = raw.get("isAccessibleForFree")
    ages = (
        _value_text(raw.get("typicalAgeRange"))
        or _value_text(raw.get("contentRating"))
        or _value_text(raw.get("audience"))
    )
    venue_name = (_value_text(location.get("name")) if isinstance(location, dict) else None) or source.venue_name

    return EventRecord(
        source=source.source_label,
        category=source.category,
        venue_name=venue_name,
        doors_open=_value_text(raw.get("doorTime")),
        ages=ages,
        is_free=(1 if free_from_raw is True else 0 if free_from_raw is False else ticket_fields["is_free"]),
        special_guests=_extract_special_guests(raw),
        event_name=normalize_name(_value_text(raw.get("name"))),
        event_id=_value_text(raw.get("@id")),
        record_type=_value_text(raw.get("@type")),
        cover_price=ticket_fields["cover_price"],  # type: ignore[arg-type]
        advance=ticket_fields["advance"],  # type: ignore[arg-type]
        day_of_show=ticket_fields["day_of_show"],  # type: ignore[arg-type]
        tickets_start_at=ticket_fields["tickets_start_at"],  # type: ignore[arg-type]
        tickets_end_at=ticket_fields["tickets_end_at"],  # type: ignore[arg-type]
        start_date=start_date,
        start_time=start_time,
        end_time=end_time,
        description=_value_text(raw.get("description")),
        event_url=_value_text(raw.get("url")) or source_url,
        tickets_url=ticket_fields["tickets_url"],  # type: ignore[arg-type]
        venue_id=_value_text(location.get("@id")) if isinstance(location, dict) else None,
        zip_code=_value_text(address.get("postalCode")) if isinstance(address, dict) else None,
        time_zone=_value_text(raw.get("eventSchedule")),
        city=_value_text(address.get("addressLocality")) if isinstance(address, dict) else None,
        state=_value_text(address.get("addressRegion")) if isinstance(address, dict) else None,
        address=_value_text(address.get("streetAddress")) if isinstance(address, dict) else None,
        price=ticket_fields["price"],  # type: ignore[arg-type]
        event_type=_value_text(raw.get("eventAttendanceMode")) or _value_text(raw.get("@type")),
        event_subtype=_value_text(raw.get("genre")),
        images=_value_text(raw.get("image")),
        raw_payload=raw,
    )


def _fallback_extract(source: SourceSite, html: str, page_url: str) -> list[EventRecord]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[EventRecord] = []
    seen_titles: set[str] = set()
    generic_titles = {
        "home",
        "events",
        "calendar",
        "tickets",
        "shows",
        "upcoming events",
        "view all",
        "get tickets",
        "ticket packages",
    }
    month_label_re = re.compile(
        r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}$",
        flags=re.IGNORECASE,
    )

    def is_noise_title(title: str) -> bool:
        cleaned = title.strip().lower()
        if cleaned in generic_titles:
            return True
        if cleaned.startswith("list ") or cleaned.startswith("calendar "):
            return True
        if cleaned.startswith("filter by "):
            return True
        if "skip to content" in cleaned:
            return True
        return False

    # First pass: prefer link-based candidates likely to be event details.
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        title = anchor.get_text(" ", strip=True)
        if not title:
            continue
        title_key = title.lower()
        if is_noise_title(title) or len(title) < 4 or len(title) > 140:
            continue
        if month_label_re.match(title.strip()):
            continue
        if not re.search(r"(event|show|concert|ticket|calendar|\/\d{4}\/)", href, flags=re.IGNORECASE):
            continue
        if title_key in seen_titles:
            continue

        event_url = urljoin(page_url, href)
        if event_url.rstrip("/") == page_url.rstrip("/"):
            continue

        seen_titles.add(title_key)
        anchor_scope = anchor.parent.get_text(" ", strip=True) if anchor.parent else title
        text_fields = _extract_text_fields(anchor_scope)
        inferred_price = text_fields["cover_price"] or text_fields["advance"] or text_fields["day_of_show"]
        results.append(
            EventRecord(
                source=source.source_label,
                category=source.category,
                venue_name=source.venue_name,
                event_name=normalize_name(title),
                doors_open=text_fields["doors_open"],  # type: ignore[arg-type]
                ages=text_fields["ages"],  # type: ignore[arg-type]
                is_free=text_fields["is_free"],  # type: ignore[arg-type]
                cover_price=text_fields["cover_price"],  # type: ignore[arg-type]
                advance=text_fields["advance"],  # type: ignore[arg-type]
                day_of_show=text_fields["day_of_show"],  # type: ignore[arg-type]
                food_drink_minimum=text_fields["food_drink_minimum"],  # type: ignore[arg-type]
                price=inferred_price,  # type: ignore[arg-type]
                event_url=event_url,
                raw_payload={"fallback_text": anchor_scope[:1000]},
            )
        )
        if len(results) >= 25:
            return results

    selectors = [
        "[class*='event']",
        "[id*='event']",
        "article",
        "li",
    ]

    for selector in selectors:
        for item in soup.select(selector):
            title_element = item.select_one("h1, h2, h3, h4, a, [class*='title']")
            if not title_element:
                continue
            title = title_element.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue
            title_key = title.lower()
            if is_noise_title(title):
                continue
            if month_label_re.match(title.strip()):
                continue
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            link_element = item.select_one("a[href]")
            event_url = urljoin(page_url, link_element["href"]) if link_element else page_url
            text_blob = item.get_text(" ", strip=True)
            date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text_blob) or re.search(
                r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?",
                text_blob,
                flags=re.IGNORECASE,
            )
            time_match = re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", text_blob, flags=re.IGNORECASE)

            start_date: str | None = None
            start_time: str | None = None
            if date_match:
                try:
                    parsed = parse_datetime(date_match.group(0), fuzzy=True, default=datetime.utcnow())
                    start_date = parsed.date().isoformat()
                except (ValueError, OverflowError):
                    start_date = date_match.group(0)
            if time_match:
                start_time = time_match.group(0)

            text_fields = _extract_text_fields(text_blob)

            results.append(
                EventRecord(
                    source=source.source_label,
                    category=source.category,
                    venue_name=source.venue_name,
                    event_name=normalize_name(title),
                    doors_open=text_fields["doors_open"],  # type: ignore[arg-type]
                    ages=text_fields["ages"],  # type: ignore[arg-type]
                    is_free=text_fields["is_free"],  # type: ignore[arg-type]
                    cover_price=text_fields["cover_price"],  # type: ignore[arg-type]
                    advance=text_fields["advance"],  # type: ignore[arg-type]
                    day_of_show=text_fields["day_of_show"],  # type: ignore[arg-type]
                    food_drink_minimum=text_fields["food_drink_minimum"],  # type: ignore[arg-type]
                    start_date=start_date,
                    start_time=start_time,
                    event_url=event_url,
                    raw_payload={"fallback_text": text_blob[:1000]},
                )
            )
            if len(results) >= 25:
                return results
    return results


def _needs_enrichment(record: EventRecord) -> bool:
    return any(
        value is None
        for value in (
            record.price,
            record.ages,
            record.doors_open,
            record.cover_price,
            record.advance,
            record.day_of_show,
        )
    )


def _enrich_from_event_page(record: EventRecord, listing_url: str) -> EventRecord:
    if not record.event_url or record.event_url.rstrip("/") == listing_url.rstrip("/"):
        return record
    if not _needs_enrichment(record):
        return record

    try:
        html = fetch_html(record.event_url, timeout=12)
    except requests.RequestException:
        return record

    soup = BeautifulSoup(html, "html.parser")
    text_blob = soup.get_text(" ", strip=True)
    text_fields = _extract_text_fields(text_blob)

    if record.ages is None:
        record.ages = text_fields["ages"]  # type: ignore[assignment]
    if record.doors_open is None:
        record.doors_open = text_fields["doors_open"]  # type: ignore[assignment]
    if record.cover_price is None:
        record.cover_price = text_fields["cover_price"]  # type: ignore[assignment]
    if record.advance is None:
        record.advance = text_fields["advance"]  # type: ignore[assignment]
    if record.day_of_show is None:
        record.day_of_show = text_fields["day_of_show"]  # type: ignore[assignment]
    if record.food_drink_minimum is None:
        record.food_drink_minimum = text_fields["food_drink_minimum"]  # type: ignore[assignment]
    if record.is_free is None:
        record.is_free = text_fields["is_free"]  # type: ignore[assignment]
    if record.price is None:
        record.price = (
            record.cover_price
            or record.advance
            or record.day_of_show
            or text_fields["cover_price"]  # type: ignore[assignment]
        )
    return record


def scrape_source(source: SourceSite) -> list[EventRecord]:
    urls = [source.listing_url] + source.sample_urls[:2]
    all_records: list[EventRecord] = []
    seen_signature: set[tuple[str | None, str | None]] = set()

    for url in urls:
        try:
            html = fetch_html(url)
        except requests.RequestException:
            continue

        extracted: list[EventRecord] = []
        if url == source.listing_url:
            extracted.extend(_scrape_ticketmaster_widget(source, html))

        jsonld_events = _parse_jsonld_events(html)
        if jsonld_events:
            extracted.extend([map_event_data(source, event, url) for event in jsonld_events])
        else:
            extracted.extend(_fallback_extract(source, html, url))

        for record in extracted:
            record = _enrich_from_event_page(record, source.listing_url)
            signature = (record.event_name, record.start_date)
            if signature in seen_signature:
                continue
            seen_signature.add(signature)
            all_records.append(record)

    return all_records
