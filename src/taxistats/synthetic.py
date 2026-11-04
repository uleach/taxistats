"""Generate a synthetic Yandex Go data export with the same structure as a real one.

A real export is a folder of nine JSON files. Only ``ridehistory.json`` holds
rides; the other eight (saved cards, phones, support chats, saved places…)
are generated here too, so the sample folder looks exactly like a real
export and the loader is tested against the files it must *ignore*.

Every field path, JSON type and nesting level follows a schema report of a
real export (field paths, presence counts, distinct counts, max lengths).
Presence rates are reproduced, for example driver name on ~10% of rides,
``formatted_duration`` only on completed rides, and ``payment.cashback`` on
~4%. Values are invented. Names, plates, addresses, coordinates, card
numbers and phones are fake, and URLs use the reserved ``.invalid`` domain.

What the generator reproduces because the pipeline must cope with it:

* **Two overlapping exports.** An export contains the full history up to
  the day it was requested, so a later export is a superset of an earlier
  one.
* **A few changed copies.** About 1% of rides have a different cost in the
  older export, as if adjusted afterwards (illustrative).
* **Three countries, three currencies, three UTC offsets.**
* **Repeat cars and drivers are rare**, as in the real data (782 distinct
  plates in 789 rides): a small pool of cars and drivers recurs.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

# tariff_class (≤8 chars), tariff_internal_name (≤11 chars), weight, base fare, per-minute (KZT)
TARIFFS = [
    ("econom", "econom", 0.40, 450, 38),
    ("start", "start", 0.07, 400, 34),
    ("business", "comfort", 0.24, 600, 50),
    ("comfort", "comfortplus", 0.13, 800, 66),
    ("vip", "business", 0.05, 1500, 115),
    ("ultimate", "ultimate", 0.01, 2500, 170),
    ("minivan", "minivan", 0.04, 1100, 80),
    ("kids", "kids", 0.02, 750, 60),
    ("express", "express", 0.04, 500, 30),
]

# country_id, currency, UTC offset (min), weight, FX vs KZT, map centre (lon, lat), price format
COUNTRIES = [
    ("kaz", "KZT", 360, 0.91, 1.0, (76.93, 43.24), "{} ₸"),
    ("rus", "RUB", 180, 0.06, 0.19, (37.62, 55.75), "{} ₽"),
    ("uzb", "UZS", 300, 0.03, 25.0, (69.28, 41.31), "{} сум"),
]

SURGES = [1.0] * 40 + [1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.4, 2.6, 2.8]

SURNAMES = ["Тестов", "Образцов", "Примеров", "Синтетов", "Макетов", "Шаблонов", "Пробин", "Демин",
            "Условнов", "Выдумкин", "Модельный", "Учебнов", "Случайнов", "Безымянов", "Черновой"]
FIRST = ["Арман", "Даулет", "Нурлан", "Ерлан", "Аскар", "Марат", "Руслан", "Тимур", "Азамат",
         "Сергей", "Дмитрий", "Олег", "Кайрат", "Мурат", "Самат", "Олжас", "Виктор", "Рустам"]
PATRONYMIC = ["Тестович", "Примерович", "Условович", "Образцович", "Шаблонович", "Демович"]

MAKES = {
    "Toyota": ["Camry", "Corolla", "RAV4", "Prius", "Land Cruiser", "Highlander", "Avalon", "C-HR", "Yaris"],
    "Hyundai": ["Sonata", "Elantra", "Accent", "Creta", "Tucson", "Staria", "Solaris", "Santa Fe", "Grandeur", "i40"],
    "Kia": ["K5", "K8", "Rio", "Cerato", "Optima", "Sportage", "Carnival", "Seltos", "Sorento", "Soul", "Ceed"],
    "Chevrolet": ["Cobalt", "Nexia", "Malibu", "Onix", "Tracker", "Lacetti", "Gentra", "Spark", "Captiva", "Monza"],
    "Volkswagen": ["Polo", "Jetta", "Passat", "Tiguan", "Touran", "Teramont"],
    "Skoda": ["Octavia", "Rapid", "Superb", "Kodiaq", "Karoq"],
    "Lexus": ["ES", "RX", "LX", "NX"],
    "Chery": ["Tiggo 7 Pro", "Tiggo 4", "Tiggo 8", "Arrizo 8", "Arrizo 6"],
    "Haval": ["Jolion", "F7", "M6", "H6", "Dargo"],
    "Nissan": ["Almera", "Qashqai", "Teana", "X-Trail", "Sentra"],
    "Mercedes-Benz": ["E-Class", "V-Class", "S-Class", "C-Class"],
    "Geely": ["Coolray", "Monjaro", "Emgrand", "Atlas", "Tugella"],
    "Renault": ["Logan", "Duster", "Arkana", "Sandero"],
    "Lada": ["Vesta", "Granta", "Largus", "XRAY"],
    "Ravon": ["R4", "Nexia R3", "Gentra"],
    "BYD": ["Han", "Song Plus", "Qin Plus", "Seal"],
    "Changan": ["CS35 Plus", "UNI-K", "Alsvin", "CS55 Plus"],
    "Exeed": ["TXL", "LX", "VX"],
    "Mitsubishi": ["Outlander", "ASX", "Lancer"],
    "Ford": ["Focus", "Mondeo", "Galaxy"],
    "Honda": ["Accord", "CR-V", "Civic"],
    "Mazda": ["6", "CX-5", "3"],
    "Jetour": ["X70", "Dashing", "X90 Plus"],
    "Omoda": ["C5", "S5"],
    "JAC": ["J7", "S3", "JS4"],
    "Zeekr": ["001", "X", "009"],
    "Tank": ["300", "500"],
    "Li": ["L7", "L9"],
}
MODELS = [f"{make} {m}" for make, ms in MAKES.items() for m in ms]
assert max(map(len, MODELS)) <= 22
VANS = {"Hyundai Staria", "Kia Carnival", "Mercedes-Benz V-Class", "Lada Largus", "Ford Galaxy", "Volkswagen Touran"}

# colour name (≤10 chars) -> the colour codes seen with it (several shades per name)
COLOURS = [("белый", ["FAFBFB", "FFFFFF", "F2F2F2"]), ("чёрный", ["000000", "1A1A1A", "0D0D0D"]),
           ("серый", ["808080", "6B6B6B", "A9A9A9"]), ("серебряный", ["C0C0C0", "B5B5B5"]),
           ("синий", ["0000CC", "1F3A93"]), ("красный", ["CC0000", "B22222"]), ("бежевый", ["F5F5DC"]),
           ("коричневый", ["8B4513", "5C4033"]), ("зелёный", ["008000"]), ("голубой", ["87CEEB", "6CA6CD"]),
           ("жёлтый", ["FFD700"]), ("вишнёвый", ["911E42"]), ("золотой", ["D4AF37"])]
STREETS = ["ул. Тестовая", "пр. Образцовый", "ул. Синтетическая", "ул. Примерная", "мкр. Условный",
           "пр. Демонстрационный", "ул. Макетная", "ул. Шаблонная", "бул. Учебный", "ул. Пробная",
           "пер. Выдуманный", "ул. Черновая", "пр. Модельный", "ул. Случайная"]
CITY = {"kaz": "Алматы", "rus": "Москва", "uzb": "Ташкент"}

START = date(2022, 1, 1)
EXPORTS = [date(2024, 6, 30), date(2025, 10, 31)]  # request dates; each export holds full history
PHONE_IDS = ["64f0a1b2c3d4e5f60718293a", "6512bc34de56fa7801234567"]
INVALID = "https://{}.example.invalid"


def _w(rng: random.Random, items: list[Any], weights: list[float]) -> Any:
    return rng.choices(items, weights=weights, k=1)[0]


def _hex(rng: random.Random, n: int = 32) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _plate(rng: random.Random, country: str) -> str:
    L = "ABCEHKMOPTXY"
    if country == "rus":
        return f"{rng.choice(L)}{rng.randint(100, 999)}{rng.choice(L)}{rng.choice(L)}{rng.choice(['77', '97', '199'])}"
    if country == "uzb":
        return f"01{rng.choice(L)}{rng.randint(100, 999)}{rng.choice(L)}{rng.choice(L)}"
    return f"{rng.randint(100, 999)}{''.join(rng.choice(L) for _ in range(3))}02"


def _money(value: float, fmt: str) -> str:
    whole = int(round(value))
    text = f"{whole:,}".replace(",", " ")
    return fmt.format(text)


def _formatted_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} ч {m} мин" if h else f"{m} мин"


def _address(rng: random.Random) -> str:
    return f"{rng.choice(STREETS)}, {rng.randint(1, 240)}"


def _layers(van: bool) -> dict[str, str]:
    kind = "van" if van else "sedan"
    layers = {k: f"default_{kind}_{k}.png" for k in ("details", "glossy", "hard_light", "mask", "shadow", "soft_light")}
    layers["warm_light"] = ""
    return layers


# --------------------------------------------------------------------------
# ridehistory.json
# --------------------------------------------------------------------------

class _Pools:
    """Small pools of recurring cars and drivers; most rides get a fresh car."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.cars = [self._car("kaz") for _ in range(6)]
        self.drivers = [self._name() for _ in range(4)]

    def _name(self) -> str:
        r = self.rng
        return f"{r.choice(SURNAMES)} {r.choice(FIRST)} {r.choice(PATRONYMIC)}"

    def _car(self, country: str) -> dict[str, Any]:
        r = self.rng
        model = r.choice(MODELS)
        colour, codes = r.choice(COLOURS)
        code = r.choice(codes)
        return {"car_number": _plate(r, country), "color": colour, "color_code": code,
                "layers": _layers(model in VANS), "model": model}

    def car(self, country: str) -> tuple[dict[str, Any], int | None]:
        if country == "kaz" and self.rng.random() < 0.012:
            i = self.rng.randrange(len(self.cars))
            return dict(self.cars[i]), i
        return self._car(country), None

    def driver(self, car_idx: int | None) -> str:
        # A recurring car usually has its own recurring driver.
        if car_idx is not None and car_idx < len(self.drivers) and self.rng.random() < 0.8:
            return self.drivers[car_idx]
        return self._name()


def _legal_entity_pool(rng: random.Random, n: int) -> list[list[dict[str, Any]]]:
    """Each taxi park has one fixed set of legal-entity details (≈3 values per park)."""
    return [_legal_entities(rng) for _ in range(n)]


def _legal_entities(rng: random.Random) -> list[dict[str, Any]]:
    def props() -> list[dict[str, str]]:
        p = [{"type": "tin", "value": "".join(rng.choice("0123456789") for _ in range(12))},
             {"type": "address", "value": f"г. {CITY['kaz']}, {_address(rng)}, офис {rng.randint(1, 99)}"},
             {"type": "work_hours", "value": "Пн–Пт 09:00–18:00"}]
        if rng.random() < 0.15:
            p.append({"type": "ogrn", "value": "".join(rng.choice("0123456789") for _ in range(13))})
        return p

    out = [{"additional_properties": props(), "title": "Перевозчик", "type": "carrier"}]
    if rng.random() < 0.025:
        out.append({"additional_properties": props(), "title": "Партнёр", "type": "partner"})
    return out


class _Places:
    """Pickup/drop-off points. Real histories reuse a few places (home, work) a lot."""

    def __init__(self, rng: random.Random, centre: tuple[float, float], n: int):
        self.rng = rng
        self.places = [(_address(rng), (round(centre[0] + rng.uniform(-0.08, 0.08), 6),
                                        round(centre[1] + rng.uniform(-0.05, 0.05), 6))) for _ in range(n)]
        self.weights = [40.0, 22.0] + [1.0 / (1 + 0.05 * i) for i in range(n - 2)]

    def pick(self) -> tuple[str, tuple[float, float]]:
        if self.rng.random() < 0.12:  # a one-off place
            p = self.places[0][1]
            return _address(self.rng), (round(p[0] + self.rng.uniform(-0.1, 0.1), 6), round(p[1] + self.rng.uniform(-0.06, 0.06), 6))
        return self.rng.choices(self.places, weights=self.weights, k=1)[0]


def _track(rng: random.Random, a: tuple[float, float], b: tuple[float, float], n: int) -> list[list[float]]:
    pts = []
    for i in range(n):
        t = i / max(n - 1, 1)
        pts.append([round(a[0] + (b[0] - a[0]) * t + rng.gauss(0, 0.0007), 6),
                    round(a[1] + (b[1] - a[1]) * t + rng.gauss(0, 0.0007), 6)])
    return pts


def _map_image(track: list[list[float]], src: tuple[float, float]) -> str:
    step = max(1, math.ceil(len(track) / 55))
    pl = ",".join(f"{p[0]:.5f},{p[1]:.5f}" for p in track[::step][:55]) or f"{src[0]:.5f},{src[1]:.5f}"
    return f"{INVALID.format('static-maps')}/1.x/?l=map&size=600,300&pl=c:3C3C3CFF,w:5,{pl}"


def _rides_today(rng: random.Random, day: date, span: int) -> int:
    seasonal = 1 + 0.45 * math.cos(2 * math.pi * (day.timetuple().tm_yday - 15) / 365)
    weekday = 1.25 if day.weekday() >= 4 else 0.9
    growth = 0.75 + 0.35 * (day - START).days / span
    lam = 0.605 * seasonal * weekday * growth
    k, p, u = 0, math.exp(-lam), rng.random()
    s = p
    while u > s:
        k += 1
        p *= lam / k
        s += p
    return k


def _hour(rng: random.Random, weekend: bool) -> int:
    if weekend:
        w = [3.0 if 12 <= h <= 23 else 1.5 if h <= 3 else 0.3 for h in range(24)]
    else:
        w = [3.5 if h in (7, 8) else 3.0 if h in (18, 19) else 1.0 if 9 <= h <= 22 else 0.15 for h in range(24)]
    return _w(rng, list(range(24)), w)


def generate_rides(seed: int = 42, end: date = EXPORTS[-1]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pools = _Pools(rng)
    span = (end - START).days
    parks = [f'ТОО "Демо Таксопарк {i:03d}"' for i in range(1, 260)]
    park_legal = _legal_entity_pool(rng, len(parks))
    places = {c[0]: _Places(rng, c[5], 150 if c[0] == "kaz" else 25) for c in COUNTRIES}
    rides: list[dict[str, Any]] = []

    day = START
    while day <= end:
        for _ in range(_rides_today(rng, day, span)):
            country, currency, offset, _, fx, centre, price_fmt = _w(rng, COUNTRIES, [c[3] for c in COUNTRIES])
            local = datetime(day.year, day.month, day.day, _hour(rng, day.weekday() >= 5),
                             rng.randint(0, 59), rng.randint(0, 59), tzinfo=timezone(timedelta(minutes=offset)))
            t_class, t_internal, _, base, per_min = _w(rng, TARIFFS, [t[2] for t in TARIFFS])
            completed = rng.random() > 0.124  # 691 of 789 in the real file have a duration
            minutes = max(3, int(rng.lognormvariate(math.log(17), 0.45)))
            surge = rng.choice(SURGES)
            inflation = 1.09 ** ((day - START).days / 365)
            kzt = (base + per_min * minutes) * inflation * surge
            cost = float(round(kzt * fx / 10) * 10) if completed else 0.0
            if currency == "UZS":
                cost = float(round(kzt * fx / 1000) * 1000) if completed else 0.0

            src_text, src = places[country].pick()
            dst_text, dst = places[country].pick()
            park_idx = rng.randrange(len(parks))
            track = _track(rng, src, dst, max(2, int(minutes * 2.5))) if completed else []
            car, car_idx = pools.car(country)
            order_id = _hex(rng)
            card = rng.random() < 0.963  # 760 of 789 paid by card

            ride: dict[str, Any] = {
                "calculation": {"surge_coefficient": surge},
                "country_id": country,
                "created_at": local.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "driver": {"call_mode": "regular"},
                "extra_enabled": False,
                "is_active": False,
                "item_id": {"created_at": int(local.timestamp()), "order_id": order_id},
                "legal_entities": json.loads(json.dumps(park_legal[park_idx])),
                "order_id": order_id,
                "payment": {
                    "cost": cost,
                    "currency_code": currency,
                    "final_cost": _money(cost, price_fmt),
                    "payment_method": (
                        {"system": "VISA", "title": rng.choice(["VISA •••• 0001", "VISA •••• 0002", "VISA •••• 0003", "Корпоративная карта"]), "type": "card"}
                        if card else {"title": "Наличные", "type": "cash"}
                    ),
                    "ride_cost": _money(cost, price_fmt),
                },
                "phone_id": PHONE_IDS[0] if rng.random() < 0.9 else PHONE_IDS[1],
                "route": {
                    "destinations": [] if rng.random() < 0.004 else
                    [{"point": [dst[0], dst[1]], "short_text": dst_text}],
                    "map_image": _map_image(track, src),
                    "source": {"point": [src[0], src[1]], "short_text": src_text},
                    "track": track,
                },
                "status": "complete" if completed else "cancelled",
                "tariff_class": t_class,
                "tariff_internal_name": t_internal,
                "taxi_status": "complete" if completed else rng.choice(["cancelled", "cancelled", "expired", "failed", "waiting"]),
                "vehicle": car,
            }
            if completed:
                ride["formatted_duration"] = _formatted_duration(minutes)
            if rng.random() < 0.975:
                ride["park"] = {"long_name": parks[park_idx]}
            if completed and rng.random() < 0.05:
                ride["payment"]["cashback"] = str(int(cost * 0.05))
                ride["payment"]["is_agent_cashback"] = True
            if rng.random() < 0.025:
                ride["receipt"] = {"url_with_embedded_pdf": f"{INVALID.format('receipts')}/{_hex(rng, 24)}.pdf"}
            # Driver details are rare (75 of 789) and come with a rating; photo is slightly rarer.
            if completed and (car_idx is not None or rng.random() < 0.098):
                ride["driver"]["name"] = pools.driver(car_idx)
                ride["driver"]["rating"] = f"{rng.randint(475, 500) / 100:.2f}"
                if rng.random() < 0.93:
                    ride["driver"]["photo_url"] = f"{INVALID.format('avatars')}/get-driver-photo/{_hex(rng, 24)}/orig"
            rides.append(ride)
        day += timedelta(days=1)
    rides.reverse()  # newest first
    return rides


# --------------------------------------------------------------------------
# The other eight files (not analysed; generated so the folder is complete)
# --------------------------------------------------------------------------

def _iso_ms(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + dt.strftime("%z")


def _side_files(rng: random.Random, export_day: date) -> dict[str, Any]:
    tz = timezone(timedelta(hours=6))
    when = lambda: datetime(rng.randint(2021, export_day.year - 1), rng.randint(1, 12), rng.randint(1, 28),  # noqa: E731
                            rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59), rng.randint(0, 999999), tzinfo=tz)
    mongo = lambda: {"$date": when().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{rng.randint(0, 999):03d}Z"}  # noqa: E731
    uid = "".join(rng.choice("0123456789") for _ in range(9))

    cards = []
    for i in range(8):
        cards.append({
            "aliases": [f"card-alias-{_hex(rng, 8)}" for _ in range(1 if i % 4 else 3)],
            "bound": i % 2 == 0, "busy": i % 3 == 0,
            "card_bank": rng.choice(["Demo Bank", "Example Bank JSC", "Synthetic Savings Bank", "Placeholder Bank of Testing"]),
            "card_country": "KAZ", "card_id": "card-x" + _hex(rng, 24),
            "currency": "KZT" if i % 3 else "USD",
            "expiration_month": rng.choice([1, 6, 12]), "expiration_year": rng.choice([2026, 2027, 2028]),
            "number": f"400000****000{i % 4}", "owner": uid, "system": "VISA",
            "unverified": False, "valid": True,
        })

    saved = [(f"Казахстан, {CITY['kaz']}, {_address(rng)}",
              [round(76.93 + rng.uniform(-0.08, 0.08), 6), round(43.24 + rng.uniform(-0.05, 0.05), 6)]) for _ in range(44)]
    routes = []
    for i in range(29):
        pts = []
        for _ in range(3 if i == 0 else 2):
            text, point = saved[i] if i < 29 and rng.random() < 0.6 else saved[29 + rng.randrange(15)]
            p = {"full_text": text, "point": list(point)}
            if rng.random() < 0.983:
                p["metrica_method"] = rng.choice(["suggest", "pin_drop"])
            if rng.random() < 0.85:
                p["metrica_action"] = rng.choice(["addressCorrection", "userInput", "favouritePlace", "lastOrderPoint",
                                                  "suggestPoint", "mapMove", "recentSearch", "homeShortcut"])
            pts.append(p)
        routes.append({"brand": "yataxi", "created": _iso_ms(when()), "route": pts})

    places = []
    for i, (name, ptype, desc) in enumerate([("Дом", "home", "Домашний адрес"), ("Работа", "work", "Офис"),
                                             ("Спорт", "other", "Тренажёрный зал"), ("Дом 2", "other", "Тренажёрный зал")]):
        p = {"created": _iso_ms(when()), "description": desc, "full_text": f"Казахстан, {CITY['kaz']}, {_address(rng)}",
             "id": ptype if ptype != "other" else "pl01", "name": name, "place_type": ptype if ptype != "other" else "user",
             "point": [round(76.93 + rng.uniform(-0.08, 0.08), 6), round(43.24 + rng.uniform(-0.05, 0.05), 6)],
             "short_text": f"{rng.choice([x for x in STREETS if len(x) <= 16])}, {rng.randint(1, 99)}", "source": "taxi", "type": "address" if i < 2 else "organization",
             "updated": _iso_ms(when()), "uri": f"ymapsbm1:geo?ll=76.93%2C43.24&spn=0.001%2C0.001&text={_hex(rng, 16)}",
             "version": 1}
        if i < 2:
            p["house"] = str(rng.randint(1, 240))
            p["street"] = rng.choice(STREETS)
        places.append(p)

    acct = "family/" + _hex(rng, 32)
    created = when().replace(tzinfo=None).isoformat(timespec="microseconds")
    shared = {
        "owned_accounts": [{"created": created, "deleted": when().replace(tzinfo=None).isoformat(timespec="microseconds"),
                            "error_description": "account_deleted", "id": acct, "is_active": False,
                            "members": [{"created": created, "nickname": "Тестовый участник", "phone": "+77000000099", "role": "child"}],
                            "type": "family"}],
        "used_accounts": [{"account_id": acct, "account_is_active": False, "account_type": "family", "member_created": created}],
    }

    chats = []
    for _ in range(21):
        msgs = [{"created": when().isoformat(timespec="seconds"),
                 "text": rng.choice(["Здравствуйте! Синтетическое обращение №{}.",
                                     "Спасибо, вопрос №{} решён.", "Водитель не приехал, прошу вернуть деньги (заказ {}).",
                                     "Мы проверили поездку {} и вернули средства на карту.", "{}"]).format(rng.randint(10000, 99999))}
                for _ in range(rng.randint(3, 8))]
        chats.append({"chat_id": "chat-" + _hex(rng, 24), "data": msgs})

    phones = ["+77000000000", "+77000000001"]
    phone_dates = [(mongo(), mongo()) for _ in phones]
    user_phones = [{"created": dict(phone_dates[i % 2][0]), "phone": phones[i % 2], "stat_complete": 0 if i % 2 else 690,
                    "stat_complete_card": 0 if i % 2 else 660, "stat_total": 0 if i % 2 else 789,
                    "type": "yandex", "updated": dict(phone_dates[i % 2][1])} for i in range(12)]
    users = [{"application": rng.choice(["iphone", "android_yango_kz"]), "application_version": f"{rng.randint(4, 6)}.{rng.randint(0, 99)}.{rng.randint(0, 9)}",
              "authorized": True, "created": mongo(), "id": _hex(rng), "phone_id": PHONE_IDS[i % 2],
              "updated": mongo(), "yandex_uid": rng.choice([uid, "1000000001", "1000000002", "1000000003"])} for i in range(12)]
    coupons = [{"code": f"DEMO{_hex(rng, 7).upper()}", "cost_usage": 500.0, "series_id": "dm1", "total_uses": 1,
                "usages": [{"cost_usage": 500.0, "reserve": _hex(rng), "was_used": True}]} for _ in range(2)]

    return {
        "cardstorage.json": {"cards": cards},
        "coupons.json": coupons,
        "routehistory.json": {"history": routes},
        "shared-payments.json": shared,
        "support_chats.json": chats,
        "user_phones.json": user_phones,
        "userplaces.json": {"places": places},
        "users.json": users,
    }


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def build_exports(seed: int = 42) -> dict[str, dict[str, Any]]:
    """Return ``{export_folder_name: {file_name: payload}}`` for every export."""
    rides = generate_rides(seed)
    rng = random.Random(seed + 1)
    exports: dict[str, dict[str, Any]] = {}
    for i, export_day in enumerate(EXPORTS):
        latest = i == len(EXPORTS) - 1
        subset = []
        for r in rides:
            if datetime.strptime(r["created_at"][:10], "%Y-%m-%d").date() > export_day:
                continue
            r = json.loads(json.dumps(r))
            if not latest and r["status"] == "complete" and rng.random() < 0.01:
                # The older copy shows the price before a later adjustment.
                pay = r["payment"]
                pay["cost"] = float(round(pay["cost"] * rng.uniform(1.05, 1.2) / 10) * 10)
                fmt = next(c[6] for c in COUNTRIES if c[1] == pay["currency_code"])
                pay["final_cost"] = pay["ride_cost"] = _money(pay["cost"], fmt)
            subset.append(r)
        files = {"ridehistory.json": subset, **_side_files(random.Random(seed + 10 + i), export_day)}
        exports[export_day.isoformat()] = dict(sorted(files.items()))
    return exports


def write_sample(out_dir: str | Path, seed: int = 42) -> list[Path]:
    out = Path(out_dir)
    written = []
    for folder, files in build_exports(seed).items():
        d = out / folder
        d.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            path = d / name
            path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            written.append(path)
    return written
