# Pre-News source identification (2026-10-15)

Uploaded screenshots identified for engine integration:

1. Investing.com Economic Calendar
   - Visual signature: bull-head impact icons, `Act / Cons / Prev` row, event names such as `Core CPI (YoY)` and `CPI (MoM)`.
   - Role: secondary calendar/consensus source.

2. Myfxbook Economic Calendar
   - Visual/data signature: event naming such as `Core Inflation Rate MoM`, `Core Inflation Rate YoY`, `Inflation Rate YoY`, `Inflation Rate MoM`, with High impact and Previous/Consensus/Actual fields.
   - Role: secondary calendar/consensus source and conflict detector.

Integration rule: neither source is authoritative by itself. Their values should be normalized, compared against existing sources and official release sources, and fed into the Pre-News fusion layer with freshness/conflict handling.
