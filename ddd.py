import sys
import unittest
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import List, Optional, Dict, Any


# ==========================================
# УТИЛИТЫ
# ==========================================

def round_money(value: Decimal) -> Decimal:
    """Округление до копеек банковским способом (half to even)."""
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


# ==========================================
# МОДЕЛИ ДАННЫХ
# ==========================================

@dataclass
class Product:
    id: str
    name: str
    basePrice: Decimal
    category: str


@dataclass
class CartItem:
    product: Product
    quantity: int

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("Количество товара должно быть больше 0")


@dataclass
class Customer:
    id: str
    lastPurchaseDate: Optional[date]
    isFirstOrder: bool


@dataclass
class Order:
    id: str
    customer: Customer
    items: List[CartItem]
    promoCode: Optional[str]
    createdAt: date
    deliveryCost: Decimal


@dataclass
class AppliedDiscount:
    name: str
    amount: Decimal
    reason: str


@dataclass
class PricingResult:
    baseTotal: Decimal
    appliedDiscounts: List[AppliedDiscount]
    finalTotal: Decimal


@dataclass
class DiscountContext:
    order: Order
    current_subtotal: Decimal
    current_delivery: Decimal
    applied_discounts: List[AppliedDiscount] = field(default_factory=list)
    promo_code_used: bool = False


# ==========================================
# АБСТРАКЦИЯ СКИДКИ
# ==========================================

class IDiscount(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        pass


# ==========================================
# СТРАТЕГИИ СКИДОК
# ==========================================

class PercentDiscount(IDiscount):
    def __init__(self, percent: Decimal, name: str):
        self._percent = percent
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        amount = round_money(context.current_subtotal * self._percent / Decimal('100'))
        if amount > 0:
            return AppliedDiscount(self._name, amount, f"Скидка {self._percent}%")
        return None


class FixedDiscount(IDiscount):
    def __init__(self, value: Decimal, threshold: Decimal, name: str):
        self._value = value
        self._threshold = threshold
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        if context.current_subtotal >= self._threshold:
            return AppliedDiscount(self._name, self._value,
                                   f"Фиксированная скидка {self._value} при заказе от {self._threshold}")
        return None


class ThreeForTwoDiscount(IDiscount):
    def __init__(self, category: str, name: str):
        self._category = category
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        category_items = []
        for item in context.order.items:
            if item.product.category == self._category:
                for _ in range(item.quantity):
                    category_items.append(item.product.basePrice)

        if len(category_items) < 3:
            return None

        category_items.sort(reverse=True)

        total_free = 0
        free_count = 0
        for i, price in enumerate(category_items):
            if (i + 1) % 3 == 0:
                total_free += price
                free_count += 1

        if total_free > 0:
            amount = round_money(Decimal(str(total_free)))
            return AppliedDiscount(self._name, amount,
                                   f"Категория {self._category}: {free_count} бесплатно по акции 3 по цене 2")
        return None


class PromoCodeDiscount(IDiscount):
    def __init__(self, code: str, is_percent: bool, value: Decimal,
                 expiry_date: Optional[date], name: str):
        self._code = code
        self._is_percent = is_percent
        self._value = value
        self._expiry_date = expiry_date
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def code(self) -> str:
        return self._code

    @property
    def is_percent(self) -> bool:
        return self._is_percent

    def is_valid(self, context: DiscountContext) -> bool:
        if context.order.promoCode != self._code:
            return False
        if context.promo_code_used:
            return False
        if self._expiry_date and context.order.createdAt > self._expiry_date:
            return False
        return True

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        if not self.is_valid(context):
            return None

        context.promo_code_used = True

        if self._is_percent:
            amount = round_money(context.current_subtotal * self._value / Decimal('100'))
            reason = f"Промокод {self._code}: скидка {self._value}%"
        else:
            amount = self._value
            reason = f"Промокод {self._code}: фиксированная скидка {self._value}"

        if amount > 0:
            return AppliedDiscount(self._name, amount, reason)
        return None


class LoyaltyDiscount(IDiscount):
    def __init__(self, percent: Decimal, days: int, name: str):
        self._percent = percent
        self._days = days
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        last_date = context.order.customer.lastPurchaseDate
        if last_date is None:
            return None

        if last_date > context.order.createdAt:
            return None

        days_diff = (context.order.createdAt - last_date).days
        if 0 <= days_diff <= self._days:
            amount = round_money(context.current_subtotal * self._percent / Decimal('100'))
            if amount > 0:
                return AppliedDiscount(self._name, amount,
                                       f"Последняя покупка была {days_diff} дней назад")
        return None


class FirstOrderDiscount(IDiscount):
    def __init__(self, percent: Decimal, name: str):
        self._percent = percent
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        if context.order.customer.isFirstOrder:
            amount = round_money(context.current_subtotal * self._percent / Decimal('100'))
            if amount > 0:
                return AppliedDiscount(self._name, amount, "Скидка на первый заказ 10%")
        return None


class FreeDeliveryDiscount(IDiscount):
    def __init__(self, threshold: Decimal, name: str):
        self._threshold = threshold
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def apply(self, context: DiscountContext) -> Optional[AppliedDiscount]:
        if context.current_subtotal > self._threshold and context.current_delivery > 0:
            return AppliedDiscount(self._name, context.current_delivery,
                                   f"Бесплатная доставка при сумме товаров > {self._threshold}")
        return None


# ==========================================
# ФАБРИКА И СИНГЛТОН
# ==========================================

class DiscountRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._creators: Dict[str, Any] = {}
        return cls._instance

    def register(self, discount_type: str, creator):
        self._creators[discount_type] = creator

    def create(self, discount_type: str, config: Dict[str, Any]) -> IDiscount:
        creator = self._creators.get(discount_type)
        if not creator:
            raise ValueError(f"Неизвестный тип скидки: {discount_type}")
        return creator(config)


registry = DiscountRegistry()

registry.register("percent", lambda c: PercentDiscount(Decimal(str(c['value'])), c['name']))
registry.register("fixed", lambda c: FixedDiscount(Decimal(str(c['value'])),
                                                    Decimal(str(c['threshold'])), c['name']))
registry.register("threeForTwo", lambda c: ThreeForTwoDiscount(c['category'], c['name']))
registry.register("loyalty", lambda c: LoyaltyDiscount(Decimal(str(c['percent'])),
                                                        c['days'], c['name']))
registry.register("firstOrder", lambda c: FirstOrderDiscount(Decimal(str(c['percent'])), c['name']))
registry.register("freeDelivery", lambda c: FreeDeliveryDiscount(Decimal(str(c['threshold'])), c['name']))
registry.register("promoCode", lambda c: PromoCodeDiscount(
    c['code'], c['isPercent'], Decimal(str(c['value'])),
    datetime.strptime(c['expiry'], "%Y-%m-%d").date() if c.get('expiry') else None,
    c['name']
))


# ==========================================
# ДВИЖОК РАСЧЕТА
# ==========================================

class PricingEngine:
    def calculate(self, order: Order, discounts: List[IDiscount]) -> PricingResult:
        base_subtotal = sum(item.product.basePrice * item.quantity for item in order.items)
        base_total = round_money(base_subtotal + order.deliveryCost)

        context = DiscountContext(
            order=order,
            current_subtotal=base_subtotal,
            current_delivery=order.deliveryCost,
            applied_discounts=[]
        )

        # Этап 1: 3 по цене 2
        for d in discounts:
            if isinstance(d, ThreeForTwoDiscount):
                res = d.apply(context)
                if res:
                    self._apply_to_context(context, res)

        # Этап 2: Процентные скидки (конфликт обычная vs промокод)
        best_percent = None
        max_amount = Decimal('0.00')

        for d in discounts:
            if isinstance(d, PercentDiscount):
                res = d.apply(context)
                if res and res.amount > max_amount:
                    max_amount = res.amount
                    best_percent = (d, res)

        for d in discounts:
            if isinstance(d, PromoCodeDiscount) and d.is_percent and d.is_valid(context):
                amount = round_money(context.current_subtotal * d._value / Decimal('100'))
                if amount >= max_amount:
                    max_amount = amount
                    res = AppliedDiscount(d.name, amount, f"Промокод {d.code}: скидка {d._value}%")
                    best_percent = (d, res)

        if best_percent:
            d, res = best_percent
            if isinstance(d, PromoCodeDiscount):
                context.promo_code_used = True
            self._apply_to_context(context, res)

        # Этап 3: Лояльность и первый заказ
        for d in discounts:
            if isinstance(d, (LoyaltyDiscount, FirstOrderDiscount)):
                res = d.apply(context)
                if res:
                    self._apply_to_context(context, res)

        # Этап 4: Фиксированные скидки
        for d in discounts:
            if isinstance(d, FixedDiscount):
                res = d.apply(context)
                if res:
                    self._apply_to_context(context, res)

            if isinstance(d, PromoCodeDiscount) and not d.is_percent:
                res = d.apply(context)
                if res:
                    context.promo_code_used = True
                    self._apply_to_context(context, res)

        # Этап 5: Бесплатная доставка
        for d in discounts:
            if isinstance(d, FreeDeliveryDiscount):
                res = d.apply(context)
                if res:
                    self._apply_to_context(context, res)

        final_total = round_money(context.current_subtotal + context.current_delivery)
        if final_total < 0:
            final_total = Decimal('0.00')

        return PricingResult(
            baseTotal=base_total,
            appliedDiscounts=context.applied_discounts,
            finalTotal=final_total
        )

    def _apply_to_context(self, context: DiscountContext, discount: AppliedDiscount):
        if discount.name != "Бесплатная доставка":
            discount.amount = min(discount.amount, context.current_subtotal)
            context.current_subtotal -= discount.amount
        else:
            context.current_delivery = Decimal('0.00')
        context.applied_discounts.append(discount)


# ==========================================
# ТЕСТЫ С ВЫВОДОМ ВХОДА И ВЫХОДА
# ==========================================

class TestDiscountEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PricingEngine()
        self.today = date(2026, 9, 24)

    def _create_order(self, items, delivery=Decimal('500'), is_first=False,
                      last_purchase=None, promo=None):
        customer = Customer(id="c1", lastPurchaseDate=last_purchase, isFirstOrder=is_first)
        return Order(id="o1", customer=customer, items=items, promoCode=promo,
                     createdAt=self.today, deliveryCost=delivery)

    def _print_separator(self, test_name):
        print("\n" + "=" * 70)
        print(f"ТЕСТ: {test_name}")
        print("=" * 70)

    def _print_input(self, items, discounts, delivery, promo, last_purchase, is_first):
        print("\nВХОД:")
        print(f"  Товары:")
        for item in items:
            print(f"    - {item.product.name}: {item.quantity} шт × {item.product.basePrice} = {item.product.basePrice * item.quantity}")
        print(f"  Доставка: {delivery}")
        print(f"  Промокод: {promo if promo else 'нет'}")
        print(f"  Первая покупка: {is_first}")
        print(f"  Последняя покупка: {last_purchase if last_purchase else 'нет'}")
        print(f"  Скидки:")
        for d in discounts:
            print(f"    - {d.name}")

    def _print_output(self, result):
        print("\nВЫХОД:")
        print(f"  Базовая сумма: {result.baseTotal}")
        print(f"  Применённые скидки:")
        if result.appliedDiscounts:
            for d in result.appliedDiscounts:
                print(f"    - {d.name}: {d.amount} ({d.reason})")
        else:
            print(f"    (нет)")
        print(f"  Итого к оплате: {result.finalTotal}")

    def test_percent_discount(self):
        self._print_separator("Процентная скидка 10%")

        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [PercentDiscount(Decimal('10'), "10%")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Итого = 2300.00 (2000 - 200 + 500)")
        self.assertEqual(res.finalTotal, Decimal('2300.00'))
        self.assertEqual(len(res.appliedDiscounts), 1)
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_fixed_discount_below_threshold(self):
        self._print_separator("Фиксированная скидка не применяется ниже порога")

        p = Product("1", "Товар", Decimal('100'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FixedDiscount(Decimal('50'), Decimal('500'), "50 от 500")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Скидка не применится (сумма 100 < порога 500)")
        self.assertEqual(len(res.appliedDiscounts), 0)
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_three_for_two(self):
        self._print_separator("3 по цене 2")

        p = Product("1", "Книга", Decimal('300'), "Книги")
        items = [CartItem(p, 3)]
        discounts = [ThreeForTwoDiscount("Книги", "3 по цене 2")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Бесплатная книга = 300, Итого = 1100.00 (600 + 500)")
        self.assertEqual(res.appliedDiscounts[0].amount, Decimal('300.00'))
        self.assertEqual(res.finalTotal, Decimal('1100.00'))
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_promo_vs_percent(self):
        self._print_separator("Промокод vs процентная скидка")

        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [
            PercentDiscount(Decimal('5'), "5%"),
            PromoCodeDiscount("PROMO10", True, Decimal('10'), None, "Промо 10%")
        ]

        self._print_input(items, discounts, Decimal('500'), "PROMO10", None, False)

        order = self._create_order(items, delivery=Decimal('500'), promo="PROMO10")
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Выберется промокод 10% (200) вместо 5% (100)")
        self.assertEqual(res.appliedDiscounts[0].name, "Промо 10%")
        self.assertEqual(res.appliedDiscounts[0].amount, Decimal('200.00'))
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_rounding_half_to_even(self):
        self._print_separator("Округление half to even")

        p = Product("1", "Товар", Decimal('10.015'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [PercentDiscount(Decimal('10'), "10%")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: 20.03 × 10% = 2.003 → округление до 2.00 (half to even)")
        self.assertEqual(res.appliedDiscounts[0].amount, Decimal('2.00'))
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_loyalty_boundary(self):
        self._print_separator("Лояльность ровно 30 дней")

        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 1)]
        last_date = date(2026, 8, 25)
        discounts = [LoyaltyDiscount(Decimal('5'), 30, "Лояльность")]

        self._print_input(items, discounts, Decimal('500'), None, last_date, False)

        order = self._create_order(items, delivery=Decimal('500'), last_purchase=last_date)
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Скидка применится (ровно 30 дней назад)")
        self.assertEqual(len(res.appliedDiscounts), 1)
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_free_delivery_strict_boundary(self):
        self._print_separator("Бесплатная доставка строго больше порога")

        p = Product("1", "Товар", Decimal('5000'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FreeDeliveryDiscount(Decimal('5000'), "Бесплатная доставка")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Скидка не применится (5000 не строго больше 5000)")
        self.assertEqual(len(res.appliedDiscounts), 0)
        print("✓ ТЕСТ ПРОЙДЕН")

    def test_lower_bound(self):
        self._print_separator("Скидка не уходит в минус")

        p = Product("1", "Товар", Decimal('100'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FixedDiscount(Decimal('500'), Decimal('50'), "500 от 50")]

        self._print_input(items, discounts, Decimal('500'), None, None, False)

        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)

        self._print_output(res)

        print(f"\nОЖИДАЕМО: Скидка ограничена суммой товаров, Итого = 500.00 (0 + 500 доставка)")
        self.assertEqual(res.finalTotal, Decimal('500.00'))
        print("✓ ТЕСТ ПРОЙДЕН")


# ==========================================
# ДЕМОНСТРАЦИЯ
# ==========================================

def run_demo():
    print("\n" + "=" * 70)
    print("ДЕМОНСТРАЦИЯ РАСЧЕТА ЗАКАЗА")
    print("=" * 70)

    engine = PricingEngine()

    config = [
        {"type": "percent", "value": 10, "name": "Осенняя распродажа"},
        {"type": "fixed", "value": 500, "threshold": 3000, "name": "500 от 3000"},
        {"type": "threeForTwo", "category": "Книги", "name": "3 по цене 2"},
        {"type": "loyalty", "percent": 5, "days": 30, "name": "Лояльность"},
        {"type": "freeDelivery", "threshold": 5000, "name": "Бесплатная доставка"},
        {"type": "firstOrder", "percent": 10, "name": "Первый заказ"}
    ]

    discounts = [registry.create(c['type'], c) for c in config]

    book = Product("p1", "Python для начинающих", Decimal('1000'), "Книги")
    mug = Product("p2", "Кружка", Decimal('500'), "Посуда")

    customer = Customer(id="c1", lastPurchaseDate=date(2026, 9, 10), isFirstOrder=False)

    order = Order(
        id="ord_123",
        customer=customer,
        items=[CartItem(book, 3), CartItem(mug, 2)],
        promoCode=None,
        createdAt=date(2026, 9, 24),
        deliveryCost=Decimal('600')
    )

    print("\nВХОД:")
    print(f"  Товары:")
    for item in order.items:
        print(f"    - {item.product.name}: {item.quantity} шт × {item.product.basePrice} = {item.product.basePrice * item.quantity}")
    print(f"  Доставка: {order.deliveryCost}")
    print(f"  Промокод: нет")
    print(f"  Первая покупка: {order.customer.isFirstOrder}")
    print(f"  Последняя покупка: {order.customer.lastPurchaseDate}")
    print(f"  Скидки:")
    for d in discounts:
        print(f"    - {d.name}")

    result = engine.calculate(order, discounts)

    print("\nВЫХОД:")
    print(f"  Базовая сумма: {result.baseTotal}")
    print(f"  Применённые скидки:")
    for d in result.appliedDiscounts:
        print(f"    - {d.name}: {d.amount} ({d.reason})")
    print(f"  Итого к оплате: {result.finalTotal}")
    print("=" * 70)


# ==========================================
# КОНСОЛЬНЫЙ ИНТЕРФЕЙС
# ==========================================

def run_tests_with_output():
    """Запуск тестов с выводом в консоль."""
    print("\n" + "=" * 70)
    print("ЗАПУСК ТЕСТОВ")
    print("=" * 70)

    # Создаём тестовый набор
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDiscountEngine)

    # Запускаем с выводом в stdout
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=0)
    runner.run(suite)

    print("\n" + "=" * 70)
    print("ТЕСТЫ ЗАВЕРШЕНЫ")
    print("=" * 70)


def main_menu():
    while True:
        print("\n" + "=" * 70)
        print("МАРКЕТПЛЕЙС 'ШТУЧКИ-ДРЮЧКИ' - ДВИЖОК СКИДОК")
        print("=" * 70)
        print("1. Запустить тесты (с выводом входа и выхода)")
        print("2. Запустить демонстрацию расчёта")
        print("3. Выход")
        print("=" * 70)

        choice = input("Выберите действие (1-3): ").strip()

        if choice == '1':
            run_tests_with_output()
        elif choice == '2':
            run_demo()
        elif choice == '3':
            print("\nВыход из программы.")
            break
        else:
            print("\nНекорректный ввод. Попробуйте снова.")


if __name__ == "__main__":
    main_menu()