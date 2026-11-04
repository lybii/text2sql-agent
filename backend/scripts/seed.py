"""Deterministic synthetic data (seed 42) + demo accounts. Idempotent: truncates source data first.

Run as the database owner:  MIGRATION_DATABASE_URL=... python -m scripts.seed
All names/projects are fictional.
"""

import asyncio
import os
import random
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.security import hash_password

RNG = random.Random(42)
START, END = date(2023, 1, 1), date(2026, 10, 31)

REGIONS = {
    "Hà Nội": ["Cầu Giấy", "Tây Hồ", "Hoàng Mai", "Long Biên", "Nam Từ Liêm"],
    "TP.HCM": ["Quận 1", "Quận 7", "Thủ Đức", "Bình Thạnh", "Gò Vấp"],
    "Đà Nẵng": ["Hải Châu", "Sơn Trà", "Ngũ Hành Sơn"],
}
CITY_PRICE = {"Hà Nội": 1.0, "TP.HCM": 1.12, "Đà Nẵng": 0.72}
CITY_TARGET = {"Hà Nội": 5.5e9, "TP.HCM": 6.5e9, "Đà Nẵng": 3.5e9}
# code, name, commission, price range (billion VND), area range (m2), bedrooms
TYPES = [
    ("can_ho", "Căn hộ", Decimal("0.020"), (2.2, 8.5), (45, 130), (1, 3)),
    ("nha_pho", "Nhà phố", Decimal("0.020"), (6.0, 24.0), (60, 160), (3, 5)),
    ("dat_nen", "Đất nền", Decimal("0.015"), (1.6, 10.0), (80, 250), None),
    ("biet_thu", "Biệt thự", Decimal("0.025"), (15.0, 55.0), (180, 450), (4, 7)),
]
TYPE_WEIGHTS = [0.5, 0.22, 0.18, 0.10]
PROJECTS = {
    "Hà Nội": ["Lotus Garden", "Maple Residence"],
    "TP.HCM": ["Sky Harbor", "Riverside One"],
    "Đà Nẵng": ["Golden Coast", "Pine Hill"],
}
SOURCES = ["Quảng cáo online", "Giới thiệu", "Website", "Sự kiện", "Khách vãng lai"]
SOURCE_WEIGHTS = [0.32, 0.24, 0.2, 0.14, 0.1]
LAST = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương"]
MIDDLE = ["Văn", "Thị", "Minh", "Đức", "Thu", "Ngọc", "Quang", "Hải", "Thanh", "Gia"]
FIRST = ["An", "Bình", "Châu", "Dũng", "Giang", "Hà", "Hùng", "Khánh", "Linh", "Long", "Mai", "Nam",
         "Phúc", "Quân", "Sơn", "Thảo", "Trang", "Tuấn", "Vy", "Yến"]  # fmt: skip

DEMO_USERS = [
    ("admin@demo.local", "Quản trị viên", "Admin@123", "admin"),
    ("analyst@demo.local", "Chuyên viên phân tích", "Analyst@123", "user"),
    ("manager@demo.local", "Trưởng phòng kinh doanh", "Manager@123", "user"),
]


def _ascii(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
                   if unicodedata.category(c) != "Mn")  # fmt: skip


def _name() -> str:
    return f"{RNG.choice(LAST)} {RNG.choice(MIDDLE)} {RNG.choice(FIRST)}"


def _phone() -> str:
    return "09" + "".join(str(RNG.randint(0, 9)) for _ in range(8))


def _rand_date(lo: date, hi: date) -> date:
    return lo + timedelta(days=RNG.randint(0, max((hi - lo).days, 0)))


def _seasonal_date(lo: date, hi: date) -> date:
    """Q4 is busier: rejection-sample with month weights."""
    weights = {
        1: 0.6,
        2: 0.5,
        3: 0.8,
        4: 0.85,
        5: 0.9,
        6: 0.9,
        7: 0.85,
        8: 0.9,
        9: 1.0,
        10: 1.1,
        11: 1.2,
        12: 1.3,
    }
    while True:
        d = _rand_date(lo, hi)
        if RNG.random() < weights[d.month] / 1.3:
            return d


async def _insert(conn: AsyncConnection, table: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    for i in range(0, len(rows), 2000):
        await conn.execute(text(sql), rows[i : i + 2000])


async def seed(conn: AsyncConnection) -> dict[str, int]:
    await conn.execute(
        text(
            "TRUNCATE source.sales_targets, source.transactions, source.properties, source.customers,"
            " source.agents, source.property_types, source.regions RESTART IDENTITY CASCADE"
        )
    )

    regions, region_city = [], {}
    for city, districts in REGIONS.items():
        for district in districts:
            regions.append({"id": len(regions) + 1, "district": district, "city": city})
            region_city[len(regions)] = city
    await _insert(conn, "source.regions", regions)
    await _insert(
        conn,
        "source.property_types",
        [{"id": i + 1, "code": c, "name": n, "commission_rate": r} for i, (c, n, r, *_) in enumerate(TYPES)],
    )

    agents = []
    for i in range(1, 49):
        name = _name()
        agents.append({
            "id": i, "full_name": name, "email": f"{_ascii(name).lower().replace(' ', '.')}{i}@company.local",
            "phone": _phone(), "hired_on": _rand_date(date(2019, 1, 1), date(2025, 6, 30)),
            "region_id": RNG.randint(1, len(regions)),
        })  # fmt: skip
    await _insert(conn, "source.agents", agents)
    agents_by_region: dict[int, list[dict[str, object]]] = {}
    for a in agents:
        agents_by_region.setdefault(a["region_id"], []).append(a)  # type: ignore[arg-type]

    customers = []
    for i in range(1, 2601):
        name = _name()
        customers.append({
            "id": i, "full_name": name, "phone": _phone(),
            "email": f"{_ascii(name).lower().replace(' ', '')}{i}@mail.local" if RNG.random() < 0.8 else None,
            "city": RNG.choices(list(REGIONS), [0.42, 0.43, 0.15])[0],
            "source": RNG.choices(SOURCES, SOURCE_WEIGHTS)[0],
            "created_on": _seasonal_date(START - timedelta(days=180), END),
        })  # fmt: skip
    await _insert(conn, "source.customers", customers)

    properties, transactions = [], []
    for i in range(1, 3301):
        region_id = RNG.randint(1, len(regions))
        city = region_city[region_id]
        t_idx = RNG.choices(range(len(TYPES)), TYPE_WEIGHTS)[0]
        _, _, rate, (pmin, pmax), (amin, amax), beds = TYPES[t_idx]
        area = round(RNG.uniform(amin, amax), 1)
        price = round(RNG.uniform(pmin, pmax) * CITY_PRICE[city] * 1e9, -6)
        listed = _rand_date(START - timedelta(days=120), END - timedelta(days=10))
        local_agents = agents_by_region.get(region_id) or agents
        agent = RNG.choice(local_agents)
        properties.append({
            "id": i, "code": f"BDS-{i:05d}", "type_id": t_idx + 1, "region_id": region_id,
            "project_name": RNG.choice(PROJECTS[city]), "area_m2": Decimal(str(area)),
            "bedrooms": RNG.randint(*beds) if beds else None, "list_price": Decimal(price),
            "listed_on": listed, "agent_id": agent["id"],
        })  # fmt: skip

        # Sales pipeline: ~78 % of listings get a deal; some cancel and are re-sold.
        attempts = 1 if RNG.random() < 0.78 else 0
        cursor = listed
        while attempts:
            attempts -= 1
            created = cursor + timedelta(days=RNG.randint(5, 240))
            if created > END:
                break
            created = _seasonal_date(created, min(created + timedelta(days=30), END))
            sale = Decimal(round(price * RNG.uniform(0.92, 1.03), -6))
            close = created + timedelta(days=RNG.randint(10, 90))
            roll = RNG.random()
            if close > END:
                status, completed = ("deposited" if roll < 0.6 else "pending"), None
            elif roll < 0.78:
                status, completed = "completed", close
            elif roll < 0.93:
                status, completed = "cancelled", None
                attempts = 1 if RNG.random() < 0.5 else 0
                cursor = close
            else:
                status, completed = ("deposited" if roll < 0.97 else "pending"), None
            transactions.append({
                "id": len(transactions) + 1, "property_id": i, "customer_id": RNG.randint(1, len(customers)),
                "agent_id": agent["id"] if RNG.random() < 0.85 else RNG.choice(agents)["id"], "status": status,
                "sale_price": sale, "commission": Decimal(round(sale * rate)), "created_on": created,
                "completed_on": completed,
            })  # fmt: skip
    await _insert(conn, "source.properties", properties)
    await _insert(conn, "source.transactions", transactions)

    targets = []
    for a in agents:
        city = region_city[a["region_id"]]  # type: ignore[index]
        y, m = max(a["hired_on"], START).year, max(a["hired_on"], START).month  # type: ignore[type-var,union-attr]
        while (y, m) <= (END.year, END.month):
            targets.append({
                "agent_id": a["id"], "year": y, "month": m,
                "target_revenue": Decimal(round(CITY_TARGET[city] * RNG.uniform(0.8, 1.2), -7)),
            })  # fmt: skip
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    await _insert(conn, "source.sales_targets", targets)

    for email, name, password, role in DEMO_USERS:
        await conn.execute(
            text(
                "INSERT INTO app.users (email, full_name, password_hash, role) VALUES (:e, :n, :p, :r)"
                " ON CONFLICT (email) DO NOTHING"
            ),
            {"e": email, "n": name, "p": hash_password(password), "r": role},
        )
    # Manager can see staff performance out of the box; the analyst must request it (demo of the flow).
    await conn.execute(
        text(
            """
            INSERT INTO app.entitlements (user_id, dataset_code, granted_by)
            SELECT m.id, 'staff_performance', a.id FROM app.users m, app.users a
            WHERE m.email = 'manager@demo.local' AND a.email = 'admin@demo.local'
            ON CONFLICT (user_id, dataset_code) DO NOTHING
            """
        )
    )
    return {
        "regions": len(regions),
        "agents": len(agents),
        "customers": len(customers),
        "properties": len(properties),
        "transactions": len(transactions),
        "sales_targets": len(targets),
    }


async def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (owner connection)")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        counts = await seed(conn)
    await engine.dispose()
    print("seeded:", counts)


if __name__ == "__main__":
    asyncio.run(main())
