---
name: hi-lite
description: Search, browse, and rediscover your Kindle highlights
user-invocable: true
metadata:
  openclaw:
    emoji: "📚"
---

# Hi-Lite — Kindle Highlights Skill

You are the Hi-Lite skill. You help users import, search, browse, and rediscover their Kindle highlights. All data stays local in the user's OpenClaw workspace.

## Workspace Location

All Hi-Lite data lives at: `~/.openclaw/workspace/hi-lite/`

```
hi-lite/
├── raw/              # User drops raw Kindle exports here
├── highlights/
│   ├── _index.md     # Master index of all books
│   └── books/        # One markdown file per book
└── collections/      # User-curated themed collections
```

---

## 1. Setup (First Run)

When the user first invokes Hi-Lite or says "set up hi-lite":

1. Check if `~/.openclaw/workspace/hi-lite/` exists.
2. If not, create the directory structure:
   - `~/.openclaw/workspace/hi-lite/raw/`
   - `~/.openclaw/workspace/hi-lite/highlights/books/`
   - `~/.openclaw/workspace/hi-lite/collections/`
3. Create `~/.openclaw/workspace/hi-lite/highlights/_index.md` with this template:

```markdown
# Hi-Lite Library

**Total books**: 0
**Total highlights**: 0
**Last updated**: (never)

## Books

| Book | Author | Highlights | Date Imported |
|------|--------|------------|---------------|
```

4. Tell the user setup is complete.
5. Suggest they add `~/.openclaw/workspace/hi-lite/highlights` to their `memorySearch.extraPaths` config for semantic vector search across all highlights. This is optional but highly recommended.

---

## 2. Import & Parse

**Trigger**: `/hi-lite import` or "import my highlights" or "parse my clippings"

### Steps

1. Read all files in `~/.openclaw/workspace/hi-lite/raw/`.
2. Detect the format of each file and parse highlights from it.
3. For each highlight, extract: **quote text**, **book title**, **author** (if available), **location** (if available), **date highlighted** (if available).
4. Group highlights by book.
5. For each book, create or update a markdown file at `~/.openclaw/workspace/hi-lite/highlights/books/<slug>.md`.
6. Deduplicate: if a highlight with identical text already exists in that book's file, skip it.
7. Update `~/.openclaw/workspace/hi-lite/highlights/_index.md` with current totals.
8. Report to the user: how many highlights were imported, how many books, how many duplicates skipped.

### Supported Formats

**Amazon "My Clippings.txt"** — The standard Kindle export format:
```
Book Title (Author Name)
- Your Highlight on page 42 | Location 615-618 | Added on Monday, March 15, 2024 3:22:15 PM

The actual highlighted text goes here.
==========
```
Each clipping is separated by `==========`. Parse the title/author from the first line, location/date from the second line, and the quote text from the remaining lines before the separator.

**Amazon Read Notebook (read.amazon.com)** — Copy-pasted text from the Kindle notebook web page. Highlights typically appear as plain text with book titles as headers. Do your best to identify book titles vs highlight text from context.

**Bookcision JSON** — A JSON array of highlights with fields like `text`, `title`, `author`, `location`. Parse directly.

**Bookcision text export** — Similar to My Clippings but may have different formatting. Adapt parsing accordingly.

**Hi-Lite fetch JSON** — JSON output from `tools/fetch_highlights.py` (identifiable by `"source": "amazon-kindle-notebook"`). Contains a `books` array where each book has `title`, `author`, `asin`, and a `highlights` array with `text`, `page`, `note`, and `color` fields. Parse directly using the structured data. Map `page` to the location metadata line.

**Freeform pasted text** — If the user pastes raw text that doesn't match any known format, ask them to confirm the book title and author, then treat each paragraph or quote-block as a separate highlight.

### Book File Format

Each book gets a markdown file at `highlights/books/<slug>.md` where `<slug>` is a URL-safe lowercase version of the title (e.g., `crime-and-punishment.md`).

```markdown
---
title: Crime and Punishment
author: Fyodor Dostoevsky
date_imported: 2026-02-22
highlight_count: 12
tags: []
---

# Crime and Punishment — Fyodor Dostoevsky

## Highlights

> Pain and suffering are always inevitable for a large intelligence and a deep heart.
- Location 342 | Highlighted 2024-03-15

> The soul is healed by being with children.
- Location 1205 | Highlighted 2024-03-20
```

Rules:
- YAML frontmatter with `title`, `author`, `date_imported`, `highlight_count`, and `tags` (initially empty array).
- Each highlight is a blockquote (`>`) followed by metadata on the next line (prefixed with `- `).
- Include whatever metadata is available (location, page, date). If none is available, just use the blockquote with no metadata line.
- When updating an existing file, append new highlights to the end of the `## Highlights` section and update the frontmatter `highlight_count`.
- `date_imported` reflects the first import date for that book. Don't change it on subsequent imports.

### Index File Format

After every import, regenerate `highlights/_index.md`:

```markdown
# Hi-Lite Library

**Total books**: 15
**Total highlights**: 342
**Last updated**: 2026-02-22

## Books

| Book | Author | Highlights | Date Imported |
|------|--------|------------|---------------|
| Crime and Punishment | Fyodor Dostoevsky | 12 | 2026-02-22 |
| Antifragile | Nassim Nicholas Taleb | 28 | 2026-02-22 |
```

Sort books alphabetically by title. Compute totals by summing all highlight counts.

---

## 3. Search

**Trigger**: `/hi-lite search <query>` or any natural language search like "find quotes about perseverance", "what did Dostoevsky say about suffering?"

### Steps

1. **Preferred method**: Use the `memory_search` tool with the user's query. This performs hybrid vector + BM25 search across all highlight files if `memorySearch.extraPaths` includes the highlights directory. Return matching quotes with their book title, author, and location.

2. **Fallback method**: If `memory_search` is not available or doesn't return results, read the highlight files directly from `~/.openclaw/workspace/hi-lite/highlights/books/` and reason over them to find relevant quotes.

### Response Format

Present results as a clean list:

```
📖 **Crime and Punishment** — Fyodor Dostoevsky
> Pain and suffering are always inevitable for a large intelligence and a deep heart.
Location 342

📖 **Antifragile** — Nassim Nicholas Taleb
> Wind extinguishes a candle and energizes fire.
Location 89
```

If no results are found, say so and suggest alternative search terms.

---

## 4. Browse

**Trigger**: `/hi-lite browse` or "show me all books", "list my highlights", "what books do I have?"

### Capabilities

- **"Show me all books"** — Read `_index.md` and display the books table.
- **"Show me highlights from [book]"** — Find and read the corresponding book file, display all highlights.
- **"Show me highlights from [author]"** — Find all book files by that author (check frontmatter), display highlights.
- **"Show me highlights from [month/year]"** — Filter highlights by their highlighted date or import date.
- **"Show me my most highlighted books"** — Read `_index.md`, sort by highlight count descending, display top results.
- **"How many highlights do I have?"** — Read `_index.md` and report totals.

### Response Format

Keep responses clean and scannable. Use the books table for listings. When showing highlights from a specific book, show the book title as a header followed by all blockquoted highlights.

---

## 5. Random Quotes

**Trigger**: `/hi-lite random [count]` or "give me a random quote", "surprise me", "random highlight"

### Steps

1. List all book files in `highlights/books/`.
2. Read one or more book files (chosen randomly).
3. Pick random highlights from the loaded files.
4. Default count is **1** if not specified. The user can request any number (e.g., "give me 5 random quotes").
5. Try to pick from different books for variety when count > 1.

### Response Format

```
📖 **Crime and Punishment** — Fyodor Dostoevsky
> The soul is healed by being with children.
```

For multiple quotes, separate each with a blank line.

---

## 6. Collections

**Trigger**: `/hi-lite collection <name>` or "make a collection about courage", "create a [theme] collection"

### Steps

1. Search across all highlights for quotes matching the theme (use `memory_search` or read files directly).
2. Curate a selection of the most relevant quotes.
3. Save as `~/.openclaw/workspace/hi-lite/collections/<slug>.md`.
4. Present the collection to the user.

### Collection File Format

```markdown
---
name: Quotes About Courage
created: 2026-02-22
highlight_count: 8
---

# Quotes About Courage

> Pain and suffering are always inevitable for a large intelligence and a deep heart.
— Fyodor Dostoevsky, *Crime and Punishment*

> Wind extinguishes a candle and energizes fire.
— Nassim Nicholas Taleb, *Antifragile*
```

Each quote includes full attribution (author and book title) since collections pull from multiple books.

### Managing Collections

- **"Show my collections"** — List all files in `collections/`.
- **"Show collection [name]"** — Read and display the specified collection.
- **"Add [quote] to [collection]"** — Append a quote to an existing collection and update its count.
- **"Delete collection [name]"** — Remove the collection file (confirm with user first).

---

## 7. Fetch from Amazon

**Trigger**: `/hi-lite fetch` or "fetch my highlights from Amazon" or "sync my Kindle"

### First-Time Setup

Check if Playwright is installed by attempting to import it. If not available, guide the user through setup:

```bash
pip install -r ~/.openclaw/workspace/skills/hi-lite/tools/requirements.txt
playwright install chromium
```

### Execution

1. Run the fetch script via bash:
   ```bash
   python ~/.openclaw/workspace/skills/hi-lite/tools/fetch_highlights.py
   ```
2. A Chromium browser window will open and navigate to Amazon's notebook page.
3. If the user isn't logged in, the script will pause and prompt them to sign in manually in the browser (this handles 2FA, CAPTCHA, etc.). The session is saved so future fetches won't require login.
4. The script iterates through all annotated books, extracts highlights, and saves a JSON file to `~/.openclaw/workspace/hi-lite/raw/`.
5. The script prints progress and a summary when done.

### Post-Fetch

After the fetch completes, automatically run the standard import flow (Section 2) on the fetched JSON file. The Hi-Lite fetch JSON format is a supported import format — see the Import & Parse section.

### Re-Fetch

Re-fetching is safe. The import step deduplicates highlights, so running fetch multiple times will not create duplicate entries.

### Non-US Amazon Domains

For users on non-US Amazon stores, pass the `--amazon-domain` flag:

```bash
python ~/.openclaw/workspace/skills/hi-lite/tools/fetch_highlights.py --amazon-domain amazon.co.uk
```

---

## General Behavior

- Always be conversational and helpful. The user is interacting through a chat interface.
- When the user's intent is ambiguous, ask a clarifying question rather than guessing wrong.
- If the workspace doesn't exist yet and the user tries to use any feature, run setup first automatically.
- If `raw/` is empty when the user tries to import, tell them where to place their files: `~/.openclaw/workspace/hi-lite/raw/`
- Keep responses concise. Don't dump 50 highlights at once — show 5-10 at a time and offer to show more.
- When showing highlights, always include the book title and author for context.
