from datetime import date
from decimal import Decimal
from core import Product, CartItem, Customer, Order, Factory, PricingEngine
import unittest
import sys


# --- Готовые данные ---
PRODUCTS = [
    Product("p1", "Книга Python", Decimal('1000'), "Книги"),
    Product("p2", "Кружка", Decimal('500'), "Посуда"),
    Product("p3", "Ноутбук", Decimal('50000'), "Электроника"),
    Product("p4", "Футболка", Decimal('1500'), "Одежда"),
    Product("p5", "Наушники", Decimal('3000'), "Электроника"),
]

DISCOUNTS_CONFIG = [
    {"type": "threeForTwo", "category": "Книги", "name": "3 по 2 (Книги)"},
    {"type": "threeForTwo", "category": "Электроника", "name": "3 по 2 (Электроника)"},
    {"type": "percent", "value": 10, "name": "Скидка 10%"},
    {"type": "percent", "value": 20, "name": "Скидка 20%"},
    {"type": "fixed", "value": 500, "threshold": 3000, "name": "500 от 3000"},
    {"type": "fixed", "value": 1000, "threshold": 10000, "name": "1000 от 10000"},
    {"type": "loyalty", "percent": 5, "days": 30, "name": "Лояльность 5%"},
    {"type": "firstOrder", "percent": 10, "name": "Первый заказ 10%"},
    {"type": "freeDelivery", "threshold": 3000, "name": "Бесплатная доставка > 3000"},
    {"type": "freeDelivery", "threshold": 5000, "name": "Бесплатная доставка > 5000"},
    {"type": "promoCode", "code": "PROMO10", "isPercent": True, "value": 10, "expiry": "2026-12-31", "name": "Промо PROMO10 (10%)"},
    {"type": "promoCode", "code": "PROMO500", "isPercent": False, "value": 500, "expiry": "2026-12-31", "name": "Промо PROMO500 (500 руб)"},
]

CUSTOMERS = [
    {"last": date(2026, 9, 10), "first": False, "desc": "Постоянный (покупка 14 дн. назад)"},
    {"last": date(2026, 8, 1), "first": False, "desc": "Давний клиент (57 дн. назад)"},
    {"last": None, "first": True, "desc": "Новый клиент (первый заказ)"},
    {"last": None, "first": False, "desc": "Гость (без истории)"},
]

DELIVERY_OPTIONS = [Decimal('0'), Decimal('300'), Decimal('600')]

PROMO_CODES = [None, "PROMO10", "PROMO500", "EXPIRED", "UNKNOWN"]


def sep():
    print("=" * 55)


def run_tests():
    """Запуск всех 12 тестов"""
    sep()
    print("ЗАПУСК ТЕСТОВ (12 штук)")
    sep()

    from tests import TestEngine

    suite = unittest.TestLoader().loadTestsFromTestCase(TestEngine)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=01)
    result = runner.run(suite)

    sep()
    print(f"\nИТОГО: {result.testsRun} тестов")
    print(f"Пройдено: {result.testsRun - len(result.failures) - len(result.errors)}")
    if result.failures:
        print(f"Провалено: {len(result.failures)}")
    if result.errors:
        print(f"Ошибок: {len(result.errors)}")
    sep()


def select_num(prompt, min_val, max_val):
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"Введите число от {min_val} до {max_val}")
        except ValueError:
            print("Введите число")


def demo_calculation():
    """Интерактивный расчёт с выбором по цифрам"""
    sep()
    print("ДЕМОНСТРАЦИОННЫЙ РАСЧЁТ ЗАКАЗА")
    sep()

    # 1. Товары
    print("\nШАГ 1: ВЫБОР ТОВАРОВ")
    print("Доступные товары:")
    for i, p in enumerate(PRODUCTS, 1):
        print(f"  {i}. {p.name} - {p.base_price} руб. ({p.category})")

    cart = []
    print("\nДобавляйте товары (0 - закончить)")
    while True:
        idx = select_num("Номер товара: ", 0, len(PRODUCTS))
        if idx == 0:
            break
        qty = select_num("Количество: ", 1, 99)
        cart.append(CartItem(PRODUCTS[idx - 1], qty))

    if not cart:
        print("Корзина пуста. Добавляю 1 товар по умолчанию.")
        cart.append(CartItem(PRODUCTS[0], 1))

    # 2. Покупатель
    print("\nШАГ 2: ВЫБОР ПОКУПАТЕЛЯ")
    for i, c in enumerate(CUSTOMERS, 1):
        print(f"  {i}. {c['desc']}")
    cust_idx = select_num("Выбор: ", 1, len(CUSTOMERS))
    cust = CUSTOMERS[cust_idx - 1]
    customer = Customer("c1", cust["last"], cust["first"])

    # 3. Доставка
    print("\nШАГ 3: СТОИМОСТЬ ДОСТАВКИ")
    for i, d in enumerate(DELIVERY_OPTIONS, 1):
        print(f"  {i}. {d} руб.")
    del_idx = select_num("Выбор: ", 1, len(DELIVERY_OPTIONS))
    delivery = DELIVERY_OPTIONS[del_idx - 1]

    # 4. Промокод
    print("\nШАГ 4: ПРОМОКОД")
    for i, p in enumerate(PROMO_CODES, 1):
        print(f"  {i}. {p or 'без промокода'}")
    promo_idx = select_num("Выбор: ", 1, len(PROMO_CODES))
    promo = PROMO_CODES[promo_idx - 1]

    # 5. Скидки
    print("\nШАГ 5: ВЫБОР СКИДОК (можно несколько, 0 - закончить)")
    for i, d in enumerate(DISCOUNTS_CONFIG, 1):
        print(f"  {i}. {d['name']}")

    selected_discounts = []
    while True:
        idx = select_num("Номер скидки: ", 0, len(DISCOUNTS_CONFIG))
        if idx == 0:
            break
        selected_discounts.append(DISCOUNTS_CONFIG[idx - 1])

    discounts = Factory.create(selected_discounts)
    order = Order("demo_1", customer, cart, promo, date(2026, 9, 24), delivery)

    # Расчёт
    sep()
    print("РЕЗУЛЬТАТ РАСЧЁТА")
    sep()

    print("\nСОСТАВ ЗАКАЗА:")
    for item in order.items:
        total = item.product.base_price * item.quantity
        print(f"  - {item.product.name} x {item.quantity} = {total} руб.")

    print(f"\nПокупатель: {'первый заказ' if order.customer.is_first_order else 'постоянный'}")
    if order.customer.last_purchase_date:
        days = (order.created_at - order.customer.last_purchase_date).days
        print(f"   Последняя покупка: {days} дн. назад")

    print(f"Доставка: {order.delivery_cost} руб.")
    print(f"Промокод: {order.promo_code or 'нет'}")

    print(f"\nВЫБРАННЫЕ СКИДКИ:")
    for d in discounts:
        print(f"  - {d.name}")

    result = PricingEngine().calculate(order, discounts)

    print(f"\nРАСЧЁТ:")
    print(f"  Базовая сумма (товары + доставка): {result.base_total} руб.")

    if result.applied_discounts:
        print(f"\nПРИМЕНЁННЫЕ СКИДКИ:")
        for d in result.applied_discounts:
            print(f"  + {d.name}: -{d.amount} руб.")
            print(f"    -> {d.reason}")
    else:
        print(f"\nНи одна скидка не применилась")

    print(f"\nИТОГО К ОПЛАТЕ: {result.final_total} руб.")
    sep()


def main():
    while True:
        print("\nМАРКЕТПЛЕЙС 'ШТУЧКИ-ДРЮЧКИ'")
        print("1. Запустить все тесты (12 штук)")
        print("2. Демонстрационный расчёт (выбор по цифрам)")
        print("0. Выход")

        choice = input("\nВыбор (0-2): ").strip()

        if choice == '1':
            run_tests()
        elif choice == '2':
            demo_calculation()
        elif choice == '0':
            print("\nВыход. Удачи!\n")
            break
        else:
            print("Неверный ввод. Введите 0, 1 или 2.")


if __name__ == "__main__":
    main()