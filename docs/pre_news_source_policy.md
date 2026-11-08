# Pre-News source policy

The Pre-News Expectation Engine should treat Investing.com and Myfxbook as independent secondary calendar/consensus providers. Values must be normalized by canonical event ID and compared with existing providers before fusion. A disagreement produces SOURCE_CONFLICT and lowers conviction. Official statistical releases remain authoritative for post-release actual values.


## Six-provider pool (2026-11-08)

The XAUUSD Pre-News display can show these six candidate publishers:
Forex Factory Weekly, Investing.com, Myfxbook, ShowMyTrades, Helious, and
Trading Economics. A distinct vendor only counts when it supplies a usable
numeric forecast for the SAME canonical event component and release time.
A missing, stale, tentative, conflicted or malformed response never becomes a
neutral forecast. At least three valid numeric vendor records are required;
anything less is UNAVAILABLE rather than a forced bullish/bearish call.

ShowMyTrades and Helious use public JSON interfaces with no key. The former
has a provider-side 15-minute cache; the latter's free tier is documented as
being delayed about 60 minutes. An HTTP 200 indicates API reachability only:
the matching future economic release and forecast value must still be
individually checked. Investing.com and Myfxbook may reject automated requests.
Trading Economics is a *subscription-gated, disabled-by-default* backup
requiring explicit enablement and RIZAN_TRADING_ECONOMICS_API_KEY; guest access
is not supported. Neither BLS nor BEA official schedules is counted toward
the numeric forecast quorum because those agencies do not publish an analyst
consensus.

Provider-level separation does not necessarily mean independent underlying
economist surveys. Some calendar vendors redistribute identical consensus
data. The panel shows provenance and cross-source conflicts, not a guarantee
that six fully independent forecasts are available for every event.

The publisher remains read-only and preserves source status and source
timestamps. No LIVE cBot, bridge, trading/order workflow, or execution rule
is changed.
