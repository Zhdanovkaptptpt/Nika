import sys
import unittest
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import List, Optional, Dict, Callable


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


@dataclass
class Product:
    id: str
    name: str
    base_price: Decimal
    category: str


@dataclass
class CartItem:
    product: Product
    quantity: int


@dataclass
class Customer:
    id: str
    last_purchase_date: Optional[date]
    is_first_order: bool


@dataclass
class Order:
    id: str
    customer: Customer
    items: List[CartItem]
    promo_code: Optional[str]
    created_at: date
    delivery_cost: Decimal


@dataclass
class AppliedDiscount:
    name: str
    amount: Decimal
    reason: str


@dataclass
class PricingResult:
    base_total: Decimal
    applied_discounts: List[AppliedDiscount]
    final_total: Decimal


@dataclass
class DiscountContext:
    order: Order
    current_subtotal: Decimal
    current_delivery: Decimal
    applied_discounts: List[AppliedDiscount] = field(default_factory=list)
    promo_code_used: bool = False


class IDiscount(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass

    @property
    @abstractmethod
    def stage(self) -> str: pass

    @property
    def is_promo(self) -> bool: return False

    @property
    def is_loyalty(self) -> bool: return False

    @property
    def is_first_order(self) -> bool: return False

    @abstractmethod
    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]: pass

    def get_potential_amount(self, ctx: DiscountContext) -> Decimal:
        return Decimal('0')


class PercentDiscount(IDiscount):
    def __init__(self, percent: Decimal, name: str):
        self._percent = percent
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'percent'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        amount = round_money(ctx.current_subtotal * self._percent / Decimal('100'))
        if amount > 0:
            amount = min(amount, ctx.current_subtotal)
            ctx.current_subtotal -= amount
            return AppliedDiscount(self._name, amount, f"Скидка {self._percent}%")
        return None

    def get_potential_amount(self, ctx: DiscountContext) -> Decimal:
        return round_money(ctx.current_subtotal * self._percent / Decimal('100'))


class FixedDiscount(IDiscount):
    def __init__(self, value: Decimal, threshold: Decimal, name: str):
        self._value = value
        self._threshold = threshold
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'fixed'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.current_subtotal >= self._threshold:
            amount = min(self._value, ctx.current_subtotal)
            ctx.current_subtotal -= amount
            return AppliedDiscount(self._name, amount, f"Скидка {self._value} от {self._threshold}")
        return None


class ThreeForTwoDiscount(IDiscount):
    def __init__(self, category: str, name: str):
        self._category = category
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'three_for_two'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        prices = []
        for item in ctx.order.items:
            if item.product.category == self._category:
                prices.extend([item.product.base_price] * item.quantity)
        if len(prices) < 3:
            return None
        prices.sort()
        free_count = len(prices) // 3
        if free_count == 0:
            return None
        amount = round_money(sum(prices[:free_count]))
        if amount > 0:
            amount = min(amount, ctx.current_subtotal)
            ctx.current_subtotal -= amount
            return AppliedDiscount(self._name, amount, f"Категория {self._category}: {free_count} бесплатно")
        return None


class PromoCodeDiscount(IDiscount):
    def __init__(self, code: str, is_percent: bool, value: Decimal, expiry: Optional[date], name: str):
        self._code = code
        self._is_percent = is_percent
        self._value = value
        self._expiry = expiry
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'percent' if self._is_percent else 'fixed'

    @property
    def is_promo(self) -> bool: return True

    @property
    def code(self) -> str: return self._code

    @property
    def is_percent(self) -> bool: return self._is_percent

    @property
    def value(self) -> Decimal: return self._value

    def is_valid(self, ctx: DiscountContext) -> bool:
        if ctx.promo_code_used: return False
        if ctx.order.promo_code != self._code: return False
        if self._expiry and ctx.order.created_at > self._expiry: return False
        return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if not self.is_valid(ctx): return None
        ctx.promo_code_used = True
        if self._is_percent:
            amount = round_money(ctx.current_subtotal * self._value / Decimal('100'))
            reason = f"Промокод {self._code}: {self._value}%"
        else:
            amount = min(self._value, ctx.current_subtotal)
            reason = f"Промокод {self._code}: фикс. {self._value}"
        if amount > 0:
            ctx.current_subtotal -= amount
            return AppliedDiscount(self._name, amount, reason)
        return None

    def get_potential_amount(self, ctx: DiscountContext) -> Decimal:
        if self.is_valid(ctx) and self._is_percent:
            return round_money(ctx.current_subtotal * self._value / Decimal('100'))
        return Decimal('0')


class LoyaltyDiscount(IDiscount):
    def __init__(self, percent: Decimal, days: int, name: str):
        self._percent = percent
        self._days = days
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'percent'

    @property
    def is_loyalty(self) -> bool: return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        last = ctx.order.customer.last_purchase_date
        if not last or last > ctx.order.created_at: return None
        days_diff = (ctx.order.created_at - last).days
        if 0 <= days_diff <= self._days:
            amount = round_money(ctx.current_subtotal * self._percent / Decimal('100'))
            if amount > 0:
                amount = min(amount, ctx.current_subtotal)
                ctx.current_subtotal -= amount
                return AppliedDiscount(self._name, amount, f"Покупка была {days_diff} дн. назад")
        return None


class FirstOrderDiscount(IDiscount):
    def __init__(self, percent: Decimal, name: str):
        self._percent = percent
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'percent'

    @property
    def is_first_order(self) -> bool: return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.order.customer.is_first_order:
            amount = round_money(ctx.current_subtotal * self._percent / Decimal('100'))
            if amount > 0:
                amount = min(amount, ctx.current_subtotal)
                ctx.current_subtotal -= amount
                return AppliedDiscount(self._name, amount, "Скидка на первый заказ 10%")
        return None


class FreeDeliveryDiscount(IDiscount):
    def __init__(self, threshold: Decimal, name: str):
        self._threshold = threshold
        self._name = name

    @property
    def name(self) -> str: return self._name

    @property
    def stage(self) -> str: return 'delivery'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.current_subtotal > self._threshold and ctx.current_delivery > 0:
            amount = ctx.current_delivery
            ctx.current_delivery = Decimal('0')
            return AppliedDiscount(self._name, amount, f"Бесплатная доставка > {self._threshold}")
        return None


class DiscountRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._creators: Dict[str, Callable] = {}
        return cls._instance

    def register(self, discount_type: str, creator: Callable):
        self._creators[discount_type] = creator

    def create(self, discount_type: str, config: Dict) -> IDiscount:
        creator = self._creators.get(discount_type)
        if not creator:
            raise ValueError(f"Неизвестный тип скидки: {discount_type}")
        return creator(config)


registry = DiscountRegistry()
registry.register("percent", lambda c: PercentDiscount(Decimal(str(c['value'])), c['name']))
registry.register("fixed", lambda c: FixedDiscount(Decimal(str(c['value'])), Decimal(str(c['threshold'])), c['name']))
registry.register("threeForTwo", lambda c: ThreeForTwoDiscount(c['category'], c['name']))
registry.register("loyalty", lambda c: LoyaltyDiscount(Decimal(str(c['percent'])), c['days'], c['name']))
registry.register("firstOrder", lambda c: FirstOrderDiscount(Decimal(str(c['percent'])), c['name']))
registry.register("freeDelivery", lambda c: FreeDeliveryDiscount(Decimal(str(c['threshold'])), c['name']))
registry.register("promoCode", lambda c: PromoCodeDiscount(
    c['code'], c['isPercent'], Decimal(str(c['value'])),
    date.fromisoformat(c['expiry']) if c.get('expiry') else None, c['name']
))


class PricingEngine:
    def calculate(self, order: Order, discounts: List[IDiscount]) -> PricingResult:
        base_subtotal = sum(item.product.base_price * item.quantity for item in order.items)
        base_total = round_money(base_subtotal + order.delivery_cost)

        ctx = DiscountContext(
            order=order,
            current_subtotal=base_subtotal,
            current_delivery=order.delivery_cost,
            applied_discounts=[]
        )

        stages = {'three_for_two': [], 'percent': [], 'fixed': [], 'delivery': []}
        for d in discounts:
            stages[d.stage].append(d)

        for d in stages['three_for_two']:
            res = d.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        best_discount = None
        max_amount = Decimal('0')
        for d in stages['percent']:
            if d.is_promo or (not d.is_loyalty and not d.is_first_order):
                amount = d.get_potential_amount(ctx)
                if amount > max_amount or (amount == max_amount and amount > 0 and d.is_promo):
                    max_amount = amount
                    best_discount = d
        if best_discount and max_amount > 0:
            res = best_discount.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        for d in stages['percent']:
            if d.is_loyalty or d.is_first_order:
                res = d.apply(ctx)
                if res:
                    ctx.applied_discounts.append(res)

        for d in stages['fixed']:
            res = d.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        for d in stages['delivery']:
            res = d.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        final_total = round_money(max(Decimal('0'), ctx.current_subtotal + ctx.current_delivery))
        return PricingResult(
            base_total=base_total,
            applied_discounts=ctx.applied_discounts,
            final_total=final_total
        )


class TestDiscountEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PricingEngine()
        self.today = date(2026, 9, 24)

    def _create_order(self, items, delivery=Decimal('500'), is_first=False, last_purchase=None, promo=None):
        customer = Customer(id="c1", last_purchase_date=last_purchase, is_first_order=is_first)
        return Order(id="o1", customer=customer, items=items, promo_code=promo,
                     created_at=self.today, delivery_cost=delivery)

    def _print(self, title, items, discounts, delivery, promo, last_purchase, is_first, result, expected):
        print(f"ТЕСТ: {title}")
        print("ВХОД:")
        for item in items:
            print(f"  - {item.product.name}: {item.quantity} шт × {item.product.base_price}")
        print(f"  Доставка: {delivery} | Промо: {promo or 'нет'} | 1-й заказ: {is_first} | Посл. покупка: {last_purchase or 'нет'}")
        print("ВЫХОД:")
        print(f"  База: {result.base_total}")
        for d in result.applied_discounts:
            print(f"  - {d.name}: -{d.amount} ({d.reason})")
        print(f"  ИТОГО: {result.final_total}")
        print(f"  ОЖИДАЕМО: {expected}")
        print("ПРОЙДЕН\n")

    # 1. Каждая стратегия - позитив
    def test_strategies_positive(self):
        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [PercentDiscount(Decimal('10'), "10%")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.final_total, Decimal('2300.00'))
        self._print("Стратегии: позитив (процент применяется)", items, discounts, 500, None, None, False, res, "2300.00")

    # 2. Каждая стратегия - негатив
    def test_strategies_negative(self):
        p = Product("1", "Товар", Decimal('0'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [PercentDiscount(Decimal('10'), "10%")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(len(res.applied_discounts), 0)
        self._print("Стратегии: негатив (не применяется)", items, discounts, 500, None, None, False, res, "0 применённых")

    # 3. 3 по цене 2 + процент
    def test_three_then_percent(self):
        p = Product("1", "Книга", Decimal('300'), "Книги")
        items = [CartItem(p, 3)]
        discounts = [
            ThreeForTwoDiscount("Книги", "3 по 2"),
            PercentDiscount(Decimal('10'), "10%")
        ]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.applied_discounts[0].name, "3 по 2")
        self.assertEqual(res.applied_discounts[1].name, "10%")
        self.assertEqual(res.applied_discounts[1].amount, Decimal('60.00'))
        self.assertEqual(res.final_total, Decimal('1040.00'))
        self._print("3 по 2 + процент (порядок)", items, discounts, 500, None, None, False, res, "1040.00")

    # 4. Промокод + процент (выбор максимума)
    def test_promo_vs_percent(self):
        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [
            PercentDiscount(Decimal('5'), "5%"),
            PromoCodeDiscount("PROMO10", True, Decimal('10'), None, "Промо 10%")
        ]
        order = self._create_order(items, delivery=Decimal('500'), promo="PROMO10")
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.applied_discounts[0].name, "Промо 10%")
        self.assertEqual(res.applied_discounts[0].amount, Decimal('200.00'))
        self.assertEqual(res.final_total, Decimal('2300.00'))
        self._print("Промокод vs процент (максимум)", items, discounts, 500, "PROMO10", None, False, res, "2300.00")

    # 5. Нижняя граница
    def test_lower_bound(self):
        p = Product("1", "Товар", Decimal('100'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FixedDiscount(Decimal('500'), Decimal('50'), "500 от 50")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.final_total, Decimal('500.00'))
        self._print("Нижняя граница (не уходит в минус)", items, discounts, 500, None, None, False, res, "500.00")

    # 6. Округление
    def test_rounding(self):
        p = Product("1", "Товар", Decimal('10.015'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [PercentDiscount(Decimal('10'), "10%")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.applied_discounts[0].amount, Decimal('2.00'))
        self._print("Округление half to even", items, discounts, 500, None, None, False, res, "Скидка 2.00")

    # 7. Границы - порог фиксированной скидки
    def test_boundary_fixed(self):
        p = Product("1", "Товар", Decimal('2000'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FixedDiscount(Decimal('500'), Decimal('2000'), "500 от 2000")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(len(res.applied_discounts), 1)
        self._print("Граница: порог фиксированной скидки", items, discounts, 500, None, None, False, res, "скидка применена")

    # 8. Границы - ровно 30 дней лояльности
    def test_boundary_loyalty(self):
        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [LoyaltyDiscount(Decimal('5'), 30, "Лояльность")]
        order = self._create_order(items, delivery=Decimal('500'), last_purchase=date(2026, 8, 25))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(len(res.applied_discounts), 1)
        self._print("Граница: ровно 30 дней лояльности", items, discounts, 500, None, date(2026, 8, 25), False, res, "скидка применена")

    # 9. Границы - дата окончания промокода
    def test_boundary_promo(self):
        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [PromoCodeDiscount("PROMO", True, Decimal('10'), date(2026, 9, 24), "Промо")]
        order = self._create_order(items, delivery=Decimal('500'), promo="PROMO")
        res = self.engine.calculate(order, discounts)
        self.assertEqual(len(res.applied_discounts), 1)
        self._print("Граница: дата окончания промокода", items, discounts, 500, "PROMO", None, False, res, "скидка применена")

    # 10. Границы - строгое условие доставки
    def test_boundary_delivery(self):
        p = Product("1", "Товар", Decimal('5000'), "Cat")
        items = [CartItem(p, 1)]
        discounts = [FreeDeliveryDiscount(Decimal('5000'), "Бесплатная доставка")]
        order = self._create_order(items, delivery=Decimal('500'))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(len(res.applied_discounts), 0)
        self._print("Граница: строгое условие доставки", items, discounts, 500, None, None, False, res, "НЕ применена")

    # 11. Breakdown - названия, суммы, причины, порядок
    def test_breakdown(self):
        p1 = Product("1", "Книга", Decimal('1000'), "Книги")
        p2 = Product("2", "Кружка", Decimal('500'), "Посуда")
        items = [CartItem(p1, 3), CartItem(p2, 2)]
        discounts = [
            ThreeForTwoDiscount("Книги", "3 по 2"),
            LoyaltyDiscount(Decimal('5'), 30, "Лояльность")
        ]
        order = self._create_order(items, delivery=Decimal('600'), last_purchase=date(2026, 9, 10))
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.base_total, Decimal('4600.00'))
        self.assertEqual(len(res.applied_discounts), 2)
        self.assertEqual(res.applied_discounts[0].name, "3 по 2")
        self.assertEqual(res.applied_discounts[0].amount, Decimal('1000.00'))
        self.assertEqual(res.applied_discounts[1].name, "Лояльность")
        self.assertEqual(res.applied_discounts[1].amount, Decimal('150.00'))
        self.assertEqual(res.final_total, Decimal('3450.00'))
        self._print("Breakdown: полный разбор", items, discounts, 600, None, date(2026, 9, 10), False, res, "3450.00")

    # 12. Промокод vs процент (равенство - выбирается промокод)
    def test_promo_vs_percent_equal(self):
        p = Product("1", "Товар", Decimal('1000'), "Cat")
        items = [CartItem(p, 2)]
        discounts = [
            PercentDiscount(Decimal('10'), "10%"),
            PromoCodeDiscount("PROMO10", True, Decimal('10'), None, "Промо 10%")
        ]
        order = self._create_order(items, delivery=Decimal('500'), promo="PROMO10")
        res = self.engine.calculate(order, discounts)
        self.assertEqual(res.applied_discounts[0].name, "Промо 10%")
        self._print("Промокод vs процент (равенство → промо)", items, discounts, 500, "PROMO10", None, False, res, "промо выбран")


def run_demo():
    print("ДЕМОНСТРАЦИЯ РАСЧЁТА ЗАКАЗА")
    config = [
        {"type": "percent", "value": 10, "name": "Осенняя распродажа"},
        {"type": "threeForTwo", "category": "Книги", "name": "3 по цене 2"},
        {"type": "loyalty", "percent": 5, "days": 30, "name": "Лояльность"},
        {"type": "freeDelivery", "threshold": 3000, "name": "Бесплатная доставка"}
    ]
    discounts = [registry.create(c['type'], c) for c in config]
    book = Product("p1", "Python для начинающих", Decimal('1000'), "Книги")
    mug = Product("p2", "Кружка", Decimal('500'), "Посуда")
    customer = Customer(id="c1", last_purchase_date=date(2026, 9, 10), is_first_order=False)
    order = Order(
        id="ord_123", customer=customer,
        items=[CartItem(book, 3), CartItem(mug, 2)],
        promo_code=None, created_at=date(2026, 9, 24), delivery_cost=Decimal('600')
    )
    print("\nВХОДНЫЕ ДАННЫЕ:")
    for item in order.items:
        print(f"  - {item.product.name}: {item.quantity} шт × {item.product.base_price} = {item.product.base_price * item.quantity}")
    print(f"  Доставка: {order.delivery_cost}")
    print(f"  Последняя покупка: {order.customer.last_purchase_date}")
    engine = PricingEngine()
    result = engine.calculate(order, discounts)
    print("\nРЕЗУЛЬТАТ (Breakdown):")
    print(f"  Базовая сумма: {result.base_total}")
    for d in result.applied_discounts:
        print(f"  - {d.name}: -{d.amount} ({d.reason})")
    print(f"  ИТОГО К ОПЛАТЕ: {result.final_total}")


def run_tests():
    print("ЗАПУСК UNIT-ТЕСТОВ (12 тестов)")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDiscountEngine)
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=0)
    runner.run(suite)
    print("=" * 60 + "\n")


def main_menu():
    while True:
        print(" МАРКЕТПЛЕЙС 'ШТУЧКИ-ДРЮЧКИ' - ДВИЖОК СКИДОК ")
        print(" 1. Запустить демонстрацию расчёта ")
        print(" 2. Запустить тесты (12 тестов с выводом) ")
        print(" 3. Выход ")
        choice = input("Выберите действие (1-3): ").strip()
        if choice == '1':
            run_demo()
        elif choice == '2':
            run_tests()
        elif choice == '3':
            print("\nВыход из программы. Удачи!\n")
            break
        else:
            print("\n Неверный ввод. Пожалуйста, выберите 1, 2 или 3.")


if __name__ == "__main__":
    main_menu()