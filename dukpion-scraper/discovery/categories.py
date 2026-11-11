"""Discover categories and decide which are eyewear."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from config.settings import Settings
from discovery.navigation import extract_category_slugs
from scraper.http_client import HttpClient

log = logging.getLogger(__name__)


@dataclass
class CategoryPlan:
    included: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # discovered but not eyewear


def classify(slugs: list[str], s: Settings) -> CategoryPlan:
    pattern = re.compile(s.eyewear_pattern, re.I)
    plan = CategoryPlan()
    for slug in slugs:
        if slug in s.exclude_category_slugs:
            plan.skipped.append(slug)
        elif slug in s.extra_category_slugs or pattern.search(slug):
            plan.included.append(slug)
        else:
            plan.skipped.append(slug)
    return plan


def discover_categories(client: HttpClient, s: Settings) -> CategoryPlan:
    resp = client.get(s.base_url + "/")
    resp.raise_for_status()
    slugs = extract_category_slugs(resp.text, s.base_url)
    plan = classify(slugs, s)
    log.info("categories discovered=%d included=%d skipped=%d",
             len(slugs), len(plan.included), len(plan.skipped))
    for slug in plan.skipped:
        log.info("skipped (not eyewear): %s", slug)
    return plan
