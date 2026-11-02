"""Генератор синтетического каталога из 100 000 объектов для local-вида.

Все объекты имеют scale='local' и детерминированы по индексу (K-5: без
Math.random). Каждые 10 объектов — 1 звезда + 9 экзопланет. Экзопланеты
имеют parent, указывающий на свою звезду.

Генерирует data/objects_100k.json, который можно подать в бэкенд через
ASTROVERSE_CATALOG_PATH + ASTROVERSE_CATALOG_MODE=existing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.catalog import validate_catalog  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "objects_100k.json"
TOTAL = 100_000
STARS = TOTAL // 10          # 10 000 звёзд
EXOPLANETS = TOTAL - STARS   # 90 000 экзопланет

# Детерминированный LCG (как в clusterMesh.js) — без Math.random.
def lcg(seed):
    state = seed & 0xFFFFFFFF
    while True:
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        yield state / 4294967296.0


def hex_color(rng):
    """Детерминированный hex-цвет из генератора."""
    r = int(rng() * 256)
    g = int(rng() * 256)
    b = int(rng() * 256)
    return f"#{r:02x}{g:02x}{b:02x}"


def main():
    objects = []
    star_rng = lcg(0xC0FFEE)
    planet_rng = lcg(0xBABECAFE)

    for i in range(STARS):
        r = next(star_rng)
        temp = 3500 + int(r * 6500)  # 3500–10000 K
        color = (
            "#1a2a6e" if temp > 8500 else
            "#8aa3e0" if temp > 7000 else
            "#e8c060" if temp > 5200 else
            "#f4a261" if temp > 3700 else
            "#d85a5a"
        )
        radius = 0.3 + r * 1.7  # 0.3–2.0
        objects.append({
            "id": f"star_{i:06d}",
            "name": f"Звезда {i:06d}",
            "latin": f"Star {i:06d}",
            "kind": "star",
            "scale": "local",
            "radius": round(radius, 4),
            "color": color,
            "temperature_k": temp,
            "ra": round((next(star_rng) * 24) % 24, 6),
            "dec": round((next(star_rng) * 180) - 90, 6),
            "distance_ly": round(1 + next(star_rng) * 200, 2),
            "displayRadius": round(radius, 4),
            "facts": ["Синтетический объект для нагрузочного теста Фазы 1."],
            "source": "synthetic",
        })

    for i in range(EXOPLANETS):
        star_index = i // 9
        parent_id = f"star_{star_index:06d}"
        r = next(planet_rng)
        temp = 100 + int(r * 2000)  # 100–2100 K
        color = (
            "#4f83ff" if temp > 1200 else
            "#2ec4b6" if temp > 800 else
            "#ff6b6b"
        )
        radius = 0.05 + r * 0.4  # 0.05–0.45
        au = 0.1 + r * 4.0  # 0.1–4.1 a.e.
        objects.append({
            "id": f"exoplanet_{i:06d}",
            "name": f"Экзопланета {i:06d}",
            "latin": f"Exoplanet {i:06d}",
            "kind": "exoplanet",
            "scale": "local",
            "parent": parent_id,
            "radius": round(radius, 4),
            "color": color,
            "temperature_k": temp,
            "au": round(au, 4),
            "period_days": round(10 + r * 3650, 2),
            "ra": None,
            "dec": None,
            "distance_ly": None,
            "displayRadius": round(radius, 4),
            "facts": ["Синтетический объект для нагрузочного теста Фазы 1."],
            "source": "synthetic",
        })

    validate_catalog(objects)
    OUTPUT.write_text(json.dumps(objects, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Сгенерировано {len(objects)} объектов -> {OUTPUT}")


if __name__ == "__main__":
    main()
