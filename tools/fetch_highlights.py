#!/usr/bin/env python3
"""Fetch Kindle highlights from Amazon's read.amazon.com/notebook page.

Uses Playwright with a persistent browser context so the user only needs to
log into Amazon once. Subsequent runs reuse the saved session cookies.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    print(
        "Playwright is not installed. Run:\n"
        "  pip install -r tools/requirements.txt\n"
        "  playwright install chromium"
    )
    sys.exit(1)


DEFAULT_BROWSER_DATA = os.path.expanduser(
    "~/.openclaw/workspace/hi-lite/.browser-data"
)
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/hi-lite/raw")
DEFAULT_DOMAIN = "amazon.com"
LOGIN_TIMEOUT_SEC = 300  # 5 minutes


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch Kindle highlights from Amazon"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save the fetched JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--amazon-domain",
        default=DEFAULT_DOMAIN,
        help="Amazon domain, e.g. amazon.co.uk (default: %(default)s)",
    )
    parser.add_argument(
        "--browser-data",
        default=DEFAULT_BROWSER_DATA,
        help="Path to persistent browser profile (default: %(default)s)",
    )
    return parser.parse_args()


def wait_for_login(page, timeout_sec=LOGIN_TIMEOUT_SEC):
    """Wait for the user to complete login and land on the notebook page."""
    print("Login required — please sign in to Amazon in the browser window.")
    print(f"Waiting up to {timeout_sec // 60} minutes for login...")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        url = page.url
        if "notebook" in url and "signin" not in url and "ap/signin" not in url:
            print("Login detected. Continuing...")
            return True
        time.sleep(2)
    print("Login timed out.")
    return False


def scroll_to_load_all(page, container_selector, item_selector, description="items"):
    """Scroll a container until no new items appear."""
    previous_count = 0
    stale_rounds = 0
    while stale_rounds < 3:
        items = page.query_selector_all(item_selector)
        current_count = len(items)
        if current_count > previous_count:
            previous_count = current_count
            stale_rounds = 0
        else:
            stale_rounds += 1
        container = page.query_selector(container_selector)
        if container:
            container.evaluate("el => el.scrollTop = el.scrollHeight")
        else:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
    return previous_count


def extract_highlights_from_pane(page):
    """Extract all highlights currently visible in the main content pane."""
    highlights = []

    highlight_els = page.query_selector_all("#annotationHighlightHeader")
    note_els_map = {}

    # Build a list of all annotation containers
    annotations = page.query_selector_all(".a-row.a-spacing-base")

    for annotation in annotations:
        header = annotation.query_selector("#annotationHighlightHeader")
        if not header:
            continue

        metadata_text = header.inner_text().strip()
        color = ""
        page_num = ""

        # Parse "Aqua highlight | Page: 14" or "Yellow highlight | Location: 123"
        if "|" in metadata_text:
            parts = [p.strip() for p in metadata_text.split("|")]
            if parts:
                color_part = parts[0]
                color = color_part.replace("highlight", "").strip()
            if len(parts) > 1:
                loc_part = parts[1]
                if ":" in loc_part:
                    page_num = loc_part.split(":", 1)[1].strip()

        # Get highlight text
        text_el = annotation.query_selector("#highlight")
        text = text_el.inner_text().strip() if text_el else ""

        # Get note text if present
        note_el = annotation.query_selector("#note")
        note = note_el.inner_text().strip() if note_el else ""

        if text:
            highlights.append({
                "text": text,
                "page": page_num,
                "note": note,
                "color": color,
            })

    return highlights


def fetch_highlights(args):
    """Main fetch logic."""
    domain = args.amazon_domain
    notebook_url = f"https://read.{domain}/notebook"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    browser_data = Path(args.browser_data)
    browser_data.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(browser_data),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        print(f"Navigating to {notebook_url} ...")
        page.goto(notebook_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # Check if login is needed
        current_url = page.url
        if "signin" in current_url or "ap/signin" in current_url:
            if not wait_for_login(page):
                context.close()
                sys.exit(1)
            # Navigate to notebook after login
            page.goto(notebook_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # Wait for the book list to appear in the sidebar
        print("Waiting for notebook to load...")
        try:
            page.wait_for_selector("#library-section", timeout=30000)
        except PwTimeout:
            # Try alternate selectors
            try:
                page.wait_for_selector(".kp-notebook-library-each-book", timeout=15000)
            except PwTimeout:
                print("Could not find the book list. The page may have changed.")
                print(f"Current URL: {page.url}")
                context.close()
                sys.exit(1)

        time.sleep(2)

        # Scroll the sidebar to discover all books
        print("Discovering books in your library...")
        book_count = scroll_to_load_all(
            page,
            container_selector="#library-section",
            item_selector=".kp-notebook-library-each-book",
            description="books",
        )

        book_elements = page.query_selector_all(".kp-notebook-library-each-book")
        total_books = len(book_elements)
        print(f"Found {total_books} annotated books.")

        if total_books == 0:
            print("No annotated books found.")
            context.close()
            return

        books_data = []

        for i in range(total_books):
            # Re-query book elements each time since DOM may change after clicks
            book_elements = page.query_selector_all(
                ".kp-notebook-library-each-book"
            )
            if i >= len(book_elements):
                print(f"  Book index {i} out of range, skipping.")
                break

            book_el = book_elements[i]

            # Get book title from the sidebar for progress display
            title_el = book_el.query_selector("h2, .kp-notebook-searchable")
            sidebar_title = title_el.inner_text().strip() if title_el else f"Book {i+1}"

            print(
                f"Fetching highlights from {sidebar_title} ({i+1}/{total_books})..."
            )

            # Click the book in the sidebar
            book_el.click()
            time.sleep(2)

            # Wait for the annotation pane to update
            try:
                page.wait_for_selector(
                    "#annotationHighlightHeader", timeout=10000
                )
            except PwTimeout:
                # Book may have no highlights or page is slow
                time.sleep(2)

            # Extract book metadata from the main pane header
            title = ""
            author = ""
            asin = ""

            # Try to get title from the main pane
            title_header = page.query_selector(
                ".kp-notebook-metadata h3, .kp-notebook-metadata .a-size-base-plus"
            )
            if title_header:
                title = title_header.inner_text().strip()
            if not title:
                title = sidebar_title

            # Try to get author
            author_el = page.query_selector(
                ".kp-notebook-metadata .a-color-secondary, "
                ".kp-notebook-metadata p"
            )
            if author_el:
                author_text = author_el.inner_text().strip()
                author = author_text.replace("By: ", "").replace("by: ", "").strip()

            # Try to get ASIN from the book element's data attributes or link
            asin_attr = book_el.get_attribute("id")
            if asin_attr and asin_attr.startswith("B"):
                asin = asin_attr
            else:
                # Try to find ASIN in data attributes
                asin_el = book_el.query_selector("[id]")
                if asin_el:
                    el_id = asin_el.get_attribute("id") or ""
                    if el_id.startswith("B0"):
                        asin = el_id

            # Scroll the main content pane to load all highlights
            scroll_to_load_all(
                page,
                container_selector="#annotations-container, .a-row.a-spacing-base",
                item_selector="#annotationHighlightHeader",
                description="highlights",
            )

            # Extract highlights
            highlights = extract_highlights_from_pane(page)
            print(f"  Found {len(highlights)} highlights.")

            books_data.append({
                "title": title,
                "author": author,
                "asin": asin,
                "highlights": highlights,
            })

        context.close()

    # Build output
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    output = {
        "source": "amazon-kindle-notebook",
        "fetched_at": timestamp,
        "amazon_domain": domain,
        "books": books_data,
    }

    filename = f"kindle-fetch-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    output_path = output_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    total_highlights = sum(len(b["highlights"]) for b in books_data)
    print(f"\nDone! Fetched {total_highlights} highlights from {len(books_data)} books.")
    print(f"Saved to: {output_path}")
    return str(output_path)


if __name__ == "__main__":
    args = parse_args()
    fetch_highlights(args)
