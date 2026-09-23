from datetime import UTC, datetime

import pandas as pd

from fx_scanner.research_xau_event_corpus_v193 import (
    dataframe_to_events,
    summarize_corpus,
)


def test_v193_corpus_filters_usd_medium_high_from_2012():
    frame = pd.DataFrame(
        [
            {
                "DateTime": "2011-12-31T12:30:00+00:00",
                "Currency": "USD",
                "Impact": "High Impact Expected",
                "Event": "Core CPI m/m",
                "Actual": "0.3%",
                "Forecast": "0.2%",
                "Previous": "0.2%",
            },
            {
                "DateTime": "2012-01-06T13:30:00+00:00",
                "Currency": "USD",
                "Impact": "High Impact Expected",
                "Event": "Non-Farm Employment Change",
                "Actual": "200K",
                "Forecast": "150K",
                "Previous": "120K",
            },
            {
                "DateTime": "2012-01-12T13:30:00+00:00",
                "Currency": "USD",
                "Impact": "Medium Impact Expected",
                "Event": "Unemployment Claims",
                "Actual": "360K",
                "Forecast": "370K",
                "Previous": "375K",
            },
            {
                "DateTime": "2012-01-12T13:30:00+00:00",
                "Currency": "EUR",
                "Impact": "High Impact Expected",
                "Event": "ECB Press Conference",
                "Actual": None,
                "Forecast": None,
                "Previous": None,
            },
            {
                "DateTime": "2012-01-13T15:00:00+00:00",
                "Currency": "USD",
                "Impact": "Low Impact Expected",
                "Event": "Business Inventories",
                "Actual": "0.1%",
                "Forecast": "0.2%",
                "Previous": "0.2%",
            },
        ]
    )
    events = dataframe_to_events(frame)
    assert len(events) == 2
    assert events[0].scheduled_at == datetime(2012, 1, 6, 13, 30, tzinfo=UTC)
    assert events[0].family == "NFP_EMPLOYMENT"
    assert events[0].actual == 200_000
    assert events[1].family == "JOBLESS_CLAIMS"


def test_v193_corpus_summary_marks_secondary_source_and_no_authority():
    frame = pd.DataFrame(
        [
            {
                "DateTime": "2012-01-06T13:30:00+00:00",
                "Currency": "USD",
                "Impact": "High Impact Expected",
                "Event": "Non-Farm Employment Change",
                "Actual": "200K",
                "Forecast": "150K",
                "Previous": "120K",
            },
            {
                "DateTime": "2013-01-04T13:30:00+00:00",
                "Currency": "USD",
                "Impact": "High Impact Expected",
                "Event": "Non-Farm Employment Change",
                "Actual": "190K",
                "Forecast": "180K",
                "Previous": "175K",
            },
        ]
    )
    summary = summarize_corpus(dataframe_to_events(frame))
    assert summary["event_count"] == 2
    assert summary["year_min"] == 2012
    assert summary["year_max"] == 2013
    assert summary["source_tier"] == "SECONDARY_ARCHIVE"
    assert summary["official_verification_required"] is True
    assert summary["execution_authority"] is False
