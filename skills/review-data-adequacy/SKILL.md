---
name: review-data-adequacy
description:
  Data adequacy and quality checklist for pipeline features. Verifies data transformations
  produce values fit for downstream use. Portable to Cursor.
---

# Review: Data Adequacy

Checklist for reviewing whether data transformations produce values that are fit for their intended
purpose. This review catches gaps where code is technically correct but produces inadequate data.

## When to Use

Use this review skill when changes involve:

- Data transformations (source → destination mapping)
- Pipeline record creation (fetching → storing)
- Content processing (text extraction, summarization)
- Any feature where downstream processing depends on data quality

## Core Principle

**Code correctness ≠ Data adequacy**

Code can be:

- Type-safe ✓
- Well-structured ✓
- Following patterns ✓

But still produce data that is:

- Too short for analysis ✗
- Missing critical fields ✗
- Inappropriate for downstream use ✗

## Data Adequacy Checklist

### 1. Content Richness

For any field that will be processed by an LLM or analysis pipeline:

- [ ] **Minimum content length:** Is the content sufficient for the analysis task?
  - Headlines (50 chars) → insufficient for impact analysis
  - Snippets (200 chars) → may work for classification, not detailed analysis
  - Full text (2000+ chars) → appropriate for comprehensive analysis

- [ ] **Content source verified:** Where does the content come from?
  - API response only → often just metadata
  - URL scraping → full article content
  - Both → best coverage

- [ ] **Fallback strategy:** What happens when primary source fails?
  - Graceful degradation with logging?
  - Or silent data quality loss?

### 2. Field Mapping Appropriateness

For each source → destination field mapping:

- [ ] **Semantic match:** Does the source field actually contain what the destination expects?
  - `source.snippet` → `record.content` may lose article body
  - `source.title` → `record.content` is usually insufficient

- [ ] **Information preservation:** Is critical information lost in transformation?
  - Truncation without indication?
  - Merging fields that should stay separate?

- [ ] **Type appropriateness:** Even if types match, are values appropriate?
  - String field with 50 chars when 2000 expected
  - List field with 1 item when 10+ expected

### 3. Downstream Consumer Needs

For each data consumer (pipeline stage, LLM call, report):

- [ ] **Consumer requirements documented:** What does the consumer need?
  - Input format
  - Minimum content length
  - Required fields

- [ ] **Producer output verified:** Does the producer meet consumer needs?
  - Compare actual output to consumer requirements
  - Check edge cases (empty, minimal, truncated)

- [ ] **Quality validation exists:** How do we know data quality is sufficient?
  - Verification queries check content length?
  - Metrics on processing success rate?

### 4. Source Type Handling

For features processing multiple source types:

- [ ] **Each source type evaluated:** Different sources have different characteristics
  - NewsAPI: headlines only in API, need URL scraping
  - FMP: press releases have full text, SEC filings need special handling
  - Grok search: AI-generated summaries, usually sufficient

- [ ] **Consistent quality across sources:** All sources meet minimum bar?
  - Or quality varies significantly by source type?

- [ ] **Source-specific handling:** Different sources may need different treatment
  - Some need scraping, some don't
  - Some have rich metadata, some don't

### 5. Pipeline Data Flow

For multi-stage pipelines:

- [ ] **Stage input requirements met:** Does each stage receive what it needs?
  - Preprocessing stage needs rich content for ticker extraction
  - Impact assessment needs context for scoring
  - Story integration needs content for matching

- [ ] **Data enrichment happens:** Is data enriched at appropriate points?
  - URL scraping before record creation (not after)
  - Metadata extraction before storage

- [ ] **Quality degradation tracked:** Can we detect when data quality drops?
  - Logging of content lengths
  - Metrics on processing success/failure rates

## Red Flags to Catch

| Pattern                                    | Problem                             | Fix                                   |
| ------------------------------------------ | ----------------------------------- | ------------------------------------- |
| `content = source.title`                   | Headlines insufficient for analysis | Scrape full article                   |
| `content = source.snippet or source.title` | Fallback loses information silently | Log when fallback used, scrape URLs   |
| No content length checks                   | Can't detect quality issues         | Add length metrics to verification    |
| Single source strategy                     | Quality varies by source            | Handle each source type appropriately |
| No downstream validation                   | Don't know if data works            | Test with actual consumers            |

## Example Findings

### Finding: Insufficient Content for Analysis

**Priority:** p1 (correctness)

**Location:** `src/flows/monitor/ticker_search/fetch/convert.py:65-76`

**Issue:** Records created with only headline content (avg 50 chars) when pipeline analysis requires
rich content for ticker extraction and impact assessment.

**Code:**

```python
def _build_content(source: SourceItem) -> str:
    if source.snippet:
        return f"{source.title}\n\n{source.snippet}"
    return source.title  # <-- 50 chars avg, insufficient
```

**Impact:** 78% of records discarded as "no_relevant_tickers" because LLM cannot extract tickers from
headlines like "China Fines PDD for Tax Offences" (32 chars).

**Fix:** Scrape article URLs to get full content before creating records.

---

### Finding: Source Type Not Handled Appropriately

**Priority:** p2 (quality)

**Location:** `src/flows/fetch/sources.py:45`

**Issue:** All source types treated identically, but NewsAPI only provides headlines while FMP
provides full press release text.

**Impact:** NewsAPI records have much lower quality than FMP records, causing inconsistent pipeline
results.

**Fix:** Add source-specific handling - scrape URLs for sources that only provide headlines.

## Integration with Other Reviews

This skill complements but does not replace:

- **review-python-standards:** Code quality (this skill: data quality)
- **review-architecture:** System design (this skill: data flow design)
- **review-data-integrity:** Database constraints (this skill: field values)

Use together for comprehensive coverage.
