import unittest
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from datetime import date
from typing import List, Optional


# ==========================================
# 1. МОДЕЛИ ДАННЫХ (упрощённые)
# ==========================================

def round_money(val: Decimal) -> Decimal:
    """Банковское округление до копеек."""
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


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


# ==========================================
# 2. КОНТЕКСТ РАСЧЁТА
# ==========================================

class DiscountContext:
    def __init__(self, order: Order):
        self.order = order
        self.items_total = sum(
            item.product.base_price * item.quantity for item in order.items
        )
        self.delivery_cost = order.delivery_cost
        self.applied_discounts: List[AppliedDiscount] = []
        self.promo_used = False


# ==========================================
# 3. СТРАТЕГИИ СКИДОК (7 типов)
# ==========================================

class BaseDiscount:
    """Базовый класс для всех скидок."""
    name: str = ""
    stage: str = ""  # 'three_for_two', 'percent', 'fixed', 'delivery'
    is_promo: bool = False
    is_loyalty: bool = False
    is_first_order: bool = False

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        raise NotImplementedError


class ThreeForTwoDiscount(BaseDiscount):
    """3 по цене 2."""
    stage = 'three_for_two'

    def __init__(self, category: str, name: str):
        self.category = category
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        items_in_cat = [i for i in ctx.order.items if i.product.category == self.category]
        if not items_in_cat:
            return None

        total_qty = sum(i.quantity for i in items_in_cat)
        free_qty = total_qty // 3
        if free_qty == 0:
            return None

        sorted_prices = sorted([i.product.base_price for i in items_in_cat for _ in range(i.quantity)])
        discount_amount = sum(sorted_prices[:free_qty])

        if discount_amount > 0:
            discount_amount = min(discount_amount, ctx.items_total)
            ctx.items_total -= discount_amount
            return AppliedDiscount(self.name, discount_amount, f"Категория {self.category}: {free_qty} бесплатно")
        return None


class PercentDiscount(BaseDiscount):
    """Процентная скидка."""
    stage = 'percent'

    def __init__(self, percent: Decimal, name: str):
        self.percent = percent
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        amount = round_money(ctx.items_total * self.percent / 100)
        if amount > 0:
            amount = min(amount, ctx.items_total)
            ctx.items_total -= amount
            return AppliedDiscount(self.name, amount, f"Скидка {self.percent}%")
        return None


class FixedDiscount(BaseDiscount):
    """Фиксированная скидка."""
    stage = 'fixed'

    def __init__(self, value: Decimal, threshold: Decimal, name: str):
        self.value = value
        self.threshold = threshold
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.items_total >= self.threshold:
            amount = min(self.value, ctx.items_total)
            ctx.items_total -= amount
            return AppliedDiscount(self.name, amount, f"Скидка {self.value} руб. от {self.threshold}")
        return None


class PromoCodeDiscount(BaseDiscount):
    """Промокод."""
    is_promo = True

    def __init__(self, code: str, discount_type: str, value: Decimal, expiry: Optional[date], name: str):
        self.code = code
        self.discount_type = discount_type
        self.stage = 'percent' if discount_type == 'percent' else 'fixed'
        self.value = value
        self.expiry = expiry
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.promo_used or ctx.order.promo_code != self.code:
            return None
        if self.expiry and ctx.order.created_at > self.expiry:
            return None

        amount = Decimal('0')
        if self.discount_type == 'percent':
            amount = round_money(ctx.items_total * self.value / 100)
        else:
            if ctx.items_total >= self.value:
                amount = self.value

        if amount > 0:
            amount = min(amount, ctx.items_total)
            ctx.items_total -= amount
            ctx.promo_used = True
            return AppliedDiscount(self.name, amount, f"Промокод {self.code}")
        return None


class LoyaltyDiscount(BaseDiscount):
    """Лояльность (5% если последняя покупка <= 30 дней)."""
    stage = 'percent'
    is_loyalty = True

    def __init__(self, name: str):
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        last = ctx.order.customer.last_purchase_date
        if not last or last > ctx.order.created_at:
            return None

        days_diff = (ctx.order.created_at - last).days
        if days_diff <= 30:
            amount = round_money(ctx.items_total * 5 / 100)
            if amount > 0:
                amount = min(amount, ctx.items_total)
                ctx.items_total -= amount
                return AppliedDiscount(self.name, amount, f"Последняя покупка была {days_diff} дней назад")
        return None


class FirstOrderDiscount(BaseDiscount):
    """Первый заказ (10%)."""
    stage = 'percent'
    is_first_order = True

    def __init__(self, name: str):
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.order.customer.is_first_order:
            amount = round_money(ctx.items_total * 10 / 100)
            if amount > 0:
                amount = min(amount, ctx.items_total)
                ctx.items_total -= amount
                return AppliedDiscount(self.name, amount, "Скидка за первый заказ 10%")
        return None


class FreeDeliveryDiscount(BaseDiscount):
    """Бесплатная доставка."""
    stage = 'delivery'

    def __init__(self, threshold: Decimal, name: str):
        self.threshold = threshold
        self.name = name

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.items_total > self.threshold and ctx.delivery_cost > 0:
            amount = ctx.delivery_cost
            ctx.delivery_cost = Decimal('0')
            return AppliedDiscount(self.name, amount, f"Бесплатная доставка от {self.threshold}")
        return None


# ==========================================
# 4. ФАБРИКА И СИНГЛТОН
# ==========================================

class DiscountFactory:
    """Создаёт скидки по конфигурации."""

    @staticmethod
    def create(config: dict) -> BaseDiscount:
        t = config['type']
        name = config.get('name', t)

        if t == 'percent':
            return PercentDiscount(Decimal(str(config['value'])), name)
        elif t == 'fixed':
            return FixedDiscount(Decimal(str(config['value'])), Decimal(str(config['threshold'])), name)
        elif t == 'threeForTwo':
            return ThreeForTwoDiscount(config['category'], name)
        elif t == 'loyalty':
            return LoyaltyDiscount(name)
        elif t == 'freeDelivery':
            return FreeDeliveryDiscount(Decimal(str(config['threshold'])), name)
        elif t == 'promo':
            expiry = date.fromisoformat(config['expiry']) if config.get('expiry') else None
            return PromoCodeDiscount(
                config['code'], config['discount_type'],
                Decimal(str(config['value'])), expiry, name
            )
        raise ValueError(f"Неизвестный тип скидки: {t}")


class ConfigRegistry:
    """Синглтон для хранения конфигурации."""
    _instance = None
    _configs = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_configs(self, configs: list):
        self._configs = configs

    def get_strategies(self) -> List[BaseDiscount]:
        return [DiscountFactory.create(c) for c in self._configs]


# ==========================================
# 5. ДВИЖОК РАСЧЁТА
# ==========================================

class PricingEngine:
    def calculate(self, order: Order, strategies: List[BaseDiscount]) -> PricingResult:
        ctx = DiscountContext(order)
        base_total = ctx.items_total + ctx.delivery_cost

        # Группируем по этапам
        stages = {
            'three_for_two': [s for s in strategies if s.stage == 'three_for_two'],
            'percent': [s for s in strategies if s.stage == 'percent'],
            'fixed': [s for s in strategies if s.stage == 'fixed'],
            'delivery': [s for s in strategies if s.stage == 'delivery']
        }

        # 1. 3 по цене 2
        for s in stages['three_for_two']:
            self._try_apply(s, ctx)

        # 2. Процентные (выбираем лучшую между обычной и промокодом)
        percent_strategies = stages['percent']
        regular_percents = [s for s in percent_strategies if not s.is_promo and not s.is_loyalty and not s.is_first_order]
        promo_percents = [s for s in percent_strategies if s.is_promo]

        candidates = regular_percents + promo_percents
        best_strategy = None
        best_amount = Decimal('0')

        for s in candidates:
            potential = self._calculate_potential(s, ctx)
            if potential > best_amount or (potential == best_amount and s.is_promo):
                best_amount = potential
                best_strategy = s

        if best_strategy and best_amount > 0:
            self._try_apply(best_strategy, ctx)

        # Лояльность и первый заказ (суммируются)
        for s in percent_strategies:
            if s.is_loyalty or s.is_first_order:
                self._try_apply(s, ctx)

        # 3. Фиксированные
        for s in stages['fixed']:
            self._try_apply(s, ctx)

        # 4. Доставка
        for s in stages['delivery']:
            self._try_apply(s, ctx)

        final_total = round_money(ctx.items_total + ctx.delivery_cost)

        return PricingResult(
            base_total=round_money(base_total),
            applied_discounts=ctx.applied_discounts,
            final_total=final_total
        )

    def _calculate_potential(self, strategy: BaseDiscount, ctx: DiscountContext) -> Decimal:
        """Считает выгоду без изменения контекста."""
        if isinstance(strategy, PercentDiscount):
            return round_money(ctx.items_total * strategy.percent / 100)
        if isinstance(strategy, PromoCodeDiscount) and strategy.discount_type == 'percent':
            if ctx.order.promo_code == strategy.code and not ctx.promo_used:
                if not strategy.expiry or ctx.order.created_at <= strategy.expiry:
                    return round_money(ctx.items_total * strategy.value / 100)
        return Decimal('0')

    def _try_apply(self, strategy: BaseDiscount, ctx: DiscountContext):
        result = strategy.apply(ctx)
        if result and result.amount > 0:
            ctx.applied_discounts.append(result)


# ==========================================
# 6. ИНТЕРАКТИВНЫЙ ВВОД ДАННЫХ
# ==========================================

def input_decimal(prompt: str) -> Decimal:
    while True:
        try:
            return Decimal(input(prompt))
        except:
            print("Введите число (например: 1000.50)")


def input_int(prompt: str) -> int:
    while True:
        try:
            val = int(input(prompt))
            if val > 0:
                return val
            print("Число должно быть больше 0")
        except:
            print("Введите целое число")


def input_date(prompt: str) -> Optional[date]:
    val = input(prompt + " (или Enter если нет): ").strip()
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except:
        print("Формат: YYYY-MM-DD (например: 2026-09-10)")
        return input_date(prompt)


def create_order_interactive() -> Order:
    print("\n=== СОЗДАНИЕ ЗАКАЗА ===\n")

    # Создаём товары
    items = []
    num_products = input_int("Сколько разных товаров в корзине? ")

    for i in range(num_products):
        print(f"\n--- Товар {i+1} ---")
        prod_id = input(f"ID товара: ")
        prod_name = input(f"Название: ")
        prod_price = input_decimal("Цена за единицу: ")
        prod_category = input(f"Категория: ")
        quantity = input_int("Количество: ")

        product = Product(prod_id, prod_name, prod_price, prod_category)
        items.append(CartItem(product, quantity))

    # Создаём покупателя
    print("\n--- Покупатель ---")
    cust_id = input("ID покупателя: ")
    last_purchase = input_date("Дата последней покупки")
    is_first = input("Первый заказ? (да/нет): ").lower() == 'да'

    customer = Customer(cust_id, last_purchase, is_first)

    # Создаём заказ
    print("\n--- Заказ ---")
    order_id = input("Номер заказа: ")
    promo = input("Промокод (или Enter если нет): ").strip() or None
    created = input_date("Дата оформления")
    delivery = input_decimal("Стоимость доставки: ")

    return Order(order_id, customer, items, promo, created, delivery)


def run_demo():
    """Демонстрация с предустановленными данными."""
    print("--- ДЕМО РАСЧЕТА ---\n")

    registry = ConfigRegistry()
    registry.load_configs([
        {"type": "threeForTwo", "category": "Книги", "name": "3 по цене 2"},
        {"type": "percent", "value": 10, "name": "Осенняя распродажа"},
        {"type": "fixed", "value": 500, "threshold": 3000, "name": "500 руб от 3000"},
        {"type": "loyalty", "name": "Лояльность"},
        {"type": "freeDelivery", "threshold": 5000, "name": "Бесплатная доставка"},
        {"type": "promo", "code": "PROMO15", "discount_type": "percent", "value": 15, "expiry": "2026-12-31", "name": "Промокод PROMO15"}
    ])
    strategies = registry.get_strategies()

    product1 = Product("1", "Война и мир", Decimal('1000'), "Книги")
    product2 = Product("2", "Преступление и наказание", Decimal('800'), "Книги")
    product3 = Product("3", "Идиот", Decimal('900'), "Книги")

    items = [
        CartItem(product1, 2),
        CartItem(product2, 1),
        CartItem(product3, 1)
    ]

    customer = Customer("C1", date(2026, 9, 10), is_first_order=False)
    order = Order("O1", customer, items, "PROMO15", date(2026, 9, 24), Decimal('500'))

    engine = PricingEngine()
    result = engine.calculate(order, strategies)

    print(f"\nBase Total: {result.base_total}")
    for d in result.applied_discounts:
        print(f" - {d.name}: -{d.amount} ({d.reason})")
    print(f"Final Total: {result.final_total}\n")


def run_interactive():
    """Интерактивный режим с вводом данных."""
    print("\n=== ИНТЕРАКТИВНЫЙ РЕЖИМ ===\n")

    registry = ConfigRegistry()
    registry.load_configs([
        {"type": "threeForTwo", "category": "Книги", "name": "3 по цене 2"},
        {"type": "percent", "value": 10, "name": "Осенняя распродажа"},
        {"type": "fixed", "value": 500, "threshold": 3000, "name": "500 руб от 3000"},
        {"type": "loyalty", "name": "Лояльность"},
        {"type": "freeDelivery", "threshold": 5000, "name": "Бесплатная доставка"},
        {"type": "promo", "code": "PROMO15", "discount_type": "percent", "value": 15, "expiry": "2026-12-31", "name": "Промокод PROMO15"}
    ])
    strategies = registry.get_strategies()

    order = create_order_interactive()

    engine = PricingEngine()
    result = engine.calculate(order, strategies)

    print("\n=== РЕЗУЛЬТАТ РАСЧЁТА ===")
    print(f"Base Total: {result.base_total}")
    if result.applied_discounts:
        print("\nПрименённые скидки:")
        for d in result.applied_discounts:
            print(f" - {d.name}: -{d.amount} ({d.reason})")
    else:
        print("\nСкидки не применены")
    print(f"\nFinal Total: {result.final_total}")


# ==========================================
# 7. ТЕСТЫ
# ==========================================

class TestDiscountEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PricingEngine()
        self.base_date = date(2026, 9, 24)

    def _make_order(self, items, delivery=0, promo=None, is_first=False, last_purchase=None):
        cust = Customer("C1", last_purchase, is_first)
        return Order("O1", cust, items, promo, self.base_date, Decimal(str(delivery)))

    def test_3_for_2_and_percent(self):
        p = Product("1", "Book", Decimal('1000'), "Books")
        items = [CartItem(p, 3)]
        order = self._make_order(items)

        strats = [ThreeForTwoDiscount("Books", "3for2"), PercentDiscount(Decimal('10'), "10%")]
        res = self.engine.calculate(order, strats)

        self.assertEqual(res.final_total, Decimal('1800'))
        self.assertEqual(len(res.applied_discounts), 2)

    def test_promo_vs_percent_choose_max(self):
        p = Product("1", "Item", Decimal('1000'), "A")
        order = self._make_order([CartItem(p, 1)], promo="BEST")

        strats = [
            PercentDiscount(Decimal('10'), "Standard"),
            PromoCodeDiscount("BEST", "percent", Decimal('15'), None, "Promo")
        ]
        res = self.engine.calculate(order, strats)

        self.assertEqual(res.final_total, Decimal('850'))
        self.assertEqual(res.applied_discounts[0].name, "Promo")

    def test_lower_bound_no_negative(self):
        p = Product("1", "Item", Decimal('100'), "A")
        order = self._make_order([CartItem(p, 1)])
        strats = [FixedDiscount(Decimal('500'), Decimal('0'), "Huge")]
        res = self.engine.calculate(order, strats)
        self.assertEqual(res.final_total, Decimal('0'))

    def test_rounding_half_to_even(self):
        p = Product("1", "Item", Decimal('1'), "A")
        order = self._make_order([CartItem(p, 1)])
        strats = [PercentDiscount(Decimal('2.5'), "2.5%")]
        res = self.engine.calculate(order, strats)
        self.assertEqual(res.applied_discounts[0].amount, Decimal('0.02'))

    def test_boundaries(self):
        p = Product("1", "Item", Decimal('3000'), "A")
        order = self._make_order([CartItem(p, 1)])
        strats = [FixedDiscount(Decimal('100'), Decimal('3000'), "Fixed")]
        res = self.engine.calculate(order, strats)
        self.assertEqual(res.final_total, Decimal('2900'))

        p_cheap = Product("1", "Item", Decimal('5000'), "A")
        order_del = self._make_order([CartItem(p_cheap, 1)], delivery=500)
        strats_del = [FreeDeliveryDiscount(Decimal('5000'), "FreeDel")]
        res_del = self.engine.calculate(order_del, strats_del)
        self.assertEqual(res_del.final_total, Decimal('5500'))

        p_exp = Product("2", "Item", Decimal('5001'), "A")
        order_del2 = self._make_order([CartItem(p_exp, 1)], delivery=500)
        res_del2 = self.engine.calculate(order_del2, strats_del)
        self.assertEqual(res_del2.final_total, Decimal('5001'))


# ==========================================
# 8. ГЛАВНОЕ МЕНЮ
# ==========================================

if __name__ == '__main__':
    print("=" * 50)
    print("ДВИЖОК СКИДОК МАРКЕТПЛЕЙСА 'ШТУЧКИ-ДРЮЧКИ'")
    print("=" * 50)
    print("\nВыберите режим:")
    print("1 - Демо (готовый пример)")
    print("2 - Интерактивный ввод данных")
    print("3 - Запустить тесты")

    choice = input("\nВаш выбор (1/2/3): ").strip()

    if choice == '1':
        run_demo()
    elif choice == '2':
        run_interactive()
    elif choice == '3':
        unittest.main(argv=['first-arg-is-ignored'], exit=False)
    else:
        print("Неверный выбор")