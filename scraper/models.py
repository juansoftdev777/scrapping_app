from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceSite:
    category: str
    venue_name: str
    listing_url: str
    sample_urls: list[str] = field(default_factory=list)

    @property
    def source_label(self) -> str:
        return f"{self.venue_name} ({self.category})"


@dataclass(slots=True)
class EventRecord:
    source: str
    category: str
    venue_name: str
    entered: str | None = None
    special_guests: str | None = None
    doors_open: str | None = None
    ages: str | None = None
    is_free: int | None = None
    event_name: str | None = None
    event_id: str | None = None
    record_type: str | None = None
    cover_price: str | None = None
    advance: str | None = None
    day_of_show: str | None = None
    tickets_start_at: str | None = None
    tickets_end_at: str | None = None
    food_drink_minimum: str | None = None
    start_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    description: str | None = None
    event_url: str | None = None
    tickets_url: str | None = None
    venue_id: str | None = None
    zip_code: str | None = None
    time_zone: str | None = None
    city: str | None = None
    state: str | None = None
    address: str | None = None
    price: str | None = None
    event_type: str | None = None
    event_subtype: str | None = None
    images: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "category": self.category,
            "venue_name": self.venue_name,
            "entered": self.entered,
            "special_guests": self.special_guests,
            "doors_open": self.doors_open,
            "ages": self.ages,
            "is_free": self.is_free,
            "event_name": self.event_name,
            "event_id": self.event_id,
            "record_type": self.record_type,
            "cover_price": self.cover_price,
            "advance": self.advance,
            "day_of_show": self.day_of_show,
            "tickets_start_at": self.tickets_start_at,
            "tickets_end_at": self.tickets_end_at,
            "food_drink_minimum": self.food_drink_minimum,
            "start_date": self.start_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "description": self.description,
            "event_url": self.event_url,
            "tickets_url": self.tickets_url,
            "venue_id": self.venue_id,
            "zip_code": self.zip_code,
            "time_zone": self.time_zone,
            "city": self.city,
            "state": self.state,
            "address": self.address,
            "price": self.price,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "images": self.images,
            "raw_payload": self.raw_payload,
        }
