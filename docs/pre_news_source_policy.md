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


## Always-visible news conclusion · 2026-11-08

Pre-News provides a human-readable conclusion for the nearest supported USD news
release, including explicit outcomes when no safe directional inference is
possible. With every release component covered by at least three numeric,
agreeing forecast providers, the label is validated COOL RISK (pre-release
bullish XAU), HOT RISK (pre-release bearish XAU), INLINE or MIXED. When only two
valid forecast/previous pairs support one direction, or when a valid Core CPI
component is accompanied by an unavailable/conflicted headline component,
the panel displays an **INDIKASI SEMENTARA** label instead of an unqualified
direction. Contradictory components produce MIXED; insufficient inputs,
stale calendar and language-dependent FOMC produce an explicit wait/data label.
The normal strict three-source forecast confirmation and macro-confirmed XAU
bias remain separate and may say UNAVAILABLE even when a provisional indication
is displayed.

As a data-contract correction, comparable previous values are sourced only
from forecast-quoting providers of the exact event component. Official agency
index-level observations cannot be compared against a monthly growth-rate
forecast, preventing false PREVIOUS_CONFLICT for CPI MoM. True forecast-provider
disagreements remain conflicting. The view is informational and does not grant
order execution, alter news gates, or change cBots, VPS or bridge.
