import pandas as pd
from conftest import ride

from taxistats.schema import parse_record
from taxistats.stats import breakdown, highlights, repeat_cars, repeat_driver_names, repeat_drivers, to_frame


def frame(records):
    return to_frame([parse_record(r) for r in records])


def drv(name, plate):
    return {"driver": name, "plate": plate}


def test_month_breakdown_includes_empty_months():
    df = frame([ride("a", created="2024-01-10T10:00:00+0600"), ride("b", created="2024-03-10T10:00:00+0600")])
    t = breakdown(df, "month")
    assert [str(p) for p in t.index] == ["2024-01", "2024-02", "2024-03"]
    assert t.loc[pd.Period("2024-02", "M"), "rides"] == 0
    assert highlights(t)["rides"]["least"][0] == pd.Period("2024-02", "M")


def test_month_uses_local_time_not_utc():
    # 00:30 local on 1 Feb is still 31 Jan in UTC
    df = frame([ride("a", created="2024-02-01T00:30:00+0600")])
    assert str(df["month"].iat[0]) == "2024-02"


def test_tariff_stats_and_cancelled_excluded():
    df = frame([ride("a", tariff="econom", cost=1000), ride("b", tariff="econom", cost=2000),
                ride("c", tariff="business", cost=5000), ride("d", tariff="business", cost=0.0, status="cancelled")])
    t = breakdown(df, "tariff")
    assert t.loc["Economy", "rides"] == 2 and t.loc["Economy", "cost_mean"] == 1500
    assert t.loc["Business", "rides"] == 1
    h = highlights(t)
    assert h["rides"]["most"] == ("Economy", 2.0)
    assert h["cost_mean"]["most"][0] == "Business"


def test_missing_metric_is_reported_absent():
    from taxistats.stats import has_data
    df = frame([ride("a"), ride("b")])
    assert has_data(df, "duration_min") and has_data(df, "surge")
    assert not has_data(df, "wait_min")  # Yandex Go exports have no wait time


def test_other_currency_excluded_from_money():
    df = frame([ride("a", cost=1000), ride("b", cost=1000), ride("c", cost=50.0, currency="RUB")])
    t = breakdown(df, "tariff")
    assert t.loc["Economy", "rides"] == 3
    assert t.loc["Economy", "spend"] == 2000


def test_repeat_drivers_need_name_and_plate():
    df = frame([ride("a", **drv("Arman K.", "111AAA02")), ride("b", **drv("Arman K.", "111AAA02")),
                ride("c", **drv("Arman K.", "999ZZZ02")), ride("d", **drv("Daulet S.", "222BBB02"))])
    rd = repeat_drivers(df)
    assert len(rd) == 1 and rd.iloc[0]["rides"] == 2
    rn = repeat_driver_names(df)
    assert rn.iloc[0]["driver_name"] == "Arman K." and rn.iloc[0]["rides"] == 3 and rn.iloc[0]["distinct_cars"] == 2
    rc = repeat_cars(df)
    assert list(rc["car_plate"]) == ["111AAA02"]
