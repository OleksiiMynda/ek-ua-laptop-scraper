import json
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://ek.ua"
CATALOG_URL = "https://ek.ua/ua/list/298/"  # Каталог ноутбуків


def parse_price(price_text: str) -> int:
    """Витягує числове значення ціни."""
    digits = re.sub(r"\D", "", price_text)
    return int(digits) if digits else 0


def extract_city(text: str) -> str:
    """Визначає місто продажу або доставки."""
    cities = {
        "києв": "Київ", "київ": "Київ", "харк": "Харків", "дніпр": "Дніпро",
        "львів": "Львів", "одес": "Одеса", "запоріж": "Запоріжжя"
    }
    match = re.search(r"з\s+([А-Яа-яІіЇїЄєҐґ'\-]+)", text)
    target = match.group(1).lower() if match else text.lower()
    for stem, name in cities.items():
        if stem in target:
            return name
    return match.group(1).capitalize() if match else "Київ"


def extract_offers(page_html: str, default_title: str, specs: str) -> list[dict]:
    """Збирає окремі пропозиції магазинів з таблиці цін."""
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.find("table", class_=re.compile(r"conf-prices-table|where-buy-table"))
    if not table:
        return []

    # Очищення назви моделі
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else default_title
    title = re.sub(r"^Ноутбук\s+", "", title)
    title = re.sub(r"\s*-\s*купити.*$", "", title, flags=re.IGNORECASE).strip()

    offers = []
    for row in table.find_all("tr"):
        if "list-more-row" in row.get("class", []):
            continue

        price_td = row.find("td", class_=re.compile(r"price-big|where-buy-price"))
        if not price_td:
            continue

        price = parse_price(price_td.get_text())
        if price <= 0:
            continue

        # Магазин
        shop_tag = row.find("a", class_="it-shop")
        shop = shop_tag.get_text(strip=True) if shop_tag else "Інтернет-магазин"

        # Місто
        deliv_span = row.find("span", class_="it-deliv")
        city = extract_city(deliv_span.get_text() if deliv_span else row.get_text())

        offers.append({
            "назва": title,
            "опис": specs,
            "ціна": price,
            "місто": city,
            "магазин": shop
        })

    return offers


def main(output_file: str = "laptops_ek_ua.json", target_count: int = 30):
    """Основний процес парсингу та збереження у JSON."""
    collected_offers = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0")

        print("Завантаження каталогу...")
        page.goto(CATALOG_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)

        catalog_soup = BeautifulSoup(page.content(), "html.parser")
        laptop_cards = catalog_soup.find_all("table", class_="model-short-block")

        for card in laptop_cards:
            if len(collected_offers) >= target_count:
                break

            link_tag = card.find("a", class_="no-u") or card.find("a", class_="model-short-title")
            if not link_tag:
                continue

            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            url = BASE_URL + href if not href.startswith("http") else href

            # Характеристики моделі
            props = [li.get_text(strip=True) for li in card.select(".conf-key-prop li")]
            specs = "; ".join(props)

            print(f"Обробка: {title}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                offers = extract_offers(page.content(), title, specs)

                # Якщо сторінка веде на модифікації моделі (conf-table)
                if not offers:
                    sub_soup = BeautifulSoup(page.content(), "html.parser")
                    conf_links = sub_soup.select(".conf-table a[href^='/ua/']")
                    for clink in conf_links[:2]:
                        page.goto(BASE_URL + clink["href"], wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(1500)
                        offers.extend(extract_offers(page.content(), title, specs))
                        if len(collected_offers) + len(offers) >= target_count:
                            break

                collected_offers.extend(offers)
            except Exception as err:
                print(f"Помилка при зчитуванні {title}: {err}")

        browser.close()

    # Збереження у JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(collected_offers, f, ensure_ascii=False, indent=2)

    print(f"\nГотово! Зібрано {len(collected_offers)} пропозицій та збережено в {output_file}")


if __name__ == "__main__":
    main()
