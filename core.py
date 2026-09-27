import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import List, Optional, Dict, Callable


def gen_id() -> str:
    return uuid.uuid4().hex[:16]


def rnd(v: Decimal) -> Decimal:
    return v.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)


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
    def stage(self) -> str:
        pass

    @property
    def is_percent_promo(self) -> bool:
        return False

    @property
    def is_fixed_promo(self) -> bool:
        return False

    @property
    def is_loyalty(self) -> bool:
        return False

    @property
    def is_first_order(self) -> bool:
        return False

    @abstractmethod
    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        pass

    def get_potential(self, ctx: DiscountContext) -> Decimal:
        return Decimal('0')


class ThreeForTwo(IDiscount):
    def __init__(self, cat: str, name: str):
        self.cat = cat
        self.name = name

    @property
    def stage(self):
        return '3x2'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        prices = sorted([
            i.product.base_price
            for i in ctx.order.items
            if i.product.category == self.cat
            for _ in range(i.quantity)
        ])
        if len(prices) < 3:
            return None
        free_count = len(prices) // 3
        amt = rnd(sum(prices[:free_count]))
        if amt > 0:
            amt = min(amt, ctx.current_subtotal)
            ctx.current_subtotal -= amt
            return AppliedDiscount(self.name, amt, f"Категория {self.cat}: {free_count} бесплатно")
        return None


class Percent(IDiscount):
    def __init__(self, pct: Decimal, name: str):
        self.pct = Decimal(str(pct))
        self.name = name

    @property
    def stage(self):
        return 'percent'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        amt = rnd(ctx.current_subtotal * self.pct / 100)
        if amt > 0:
            amt = min(amt, ctx.current_subtotal)
            ctx.current_subtotal -= amt
            return AppliedDiscount(self.name, amt, f"Скидка {self.pct}%")
        return None

    def get_potential(self, ctx: DiscountContext) -> Decimal:
        return rnd(ctx.current_subtotal * self.pct / 100)


class Fixed(IDiscount):
    def __init__(self, val: Decimal, thresh: Decimal, name: str):
        self.val = Decimal(str(val))
        self.thresh = Decimal(str(thresh))
        self.name = name

    @property
    def stage(self):
        return 'fixed'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.current_subtotal >= self.thresh:
            amt = min(self.val, ctx.current_subtotal)
            ctx.current_subtotal -= amt
            return AppliedDiscount(self.name, amt, f"Скидка {self.val} от {self.thresh}")
        return None


class Promo(IDiscount):
    def __init__(self, code: str, is_pct: bool, val: Decimal, exp: Optional[str], name: str):
        self.code = code
        self.is_pct = is_pct
        self.val = Decimal(str(val))
        self.exp = date.fromisoformat(exp) if exp else None
        self.name = name

    @property
    def stage(self):
        return 'percent' if self.is_pct else 'fixed'

    @property
    def is_percent_promo(self):
        return self.is_pct

    @property
    def is_fixed_promo(self):
        return not self.is_pct

    def is_valid(self, ctx: DiscountContext) -> bool:
        if ctx.promo_code_used:
            return False
        if ctx.order.promo_code != self.code:
            return False
        if self.exp and ctx.order.created_at > self.exp:
            return False
        return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if not self.is_valid(ctx):
            return None
        ctx.promo_code_used = True
        if self.is_pct:
            amt = rnd(ctx.current_subtotal * self.val / 100)
            reason = f"Промокод {self.code}: {self.val}%"
        else:
            amt = min(self.val, ctx.current_subtotal)
            reason = f"Промокод {self.code}: фикс. {self.val}"
        if amt > 0:
            ctx.current_subtotal -= amt
            return AppliedDiscount(self.name, amt, reason)
        return None

    def get_potential(self, ctx: DiscountContext) -> Decimal:
        if self.is_valid(ctx) and self.is_pct:
            return rnd(ctx.current_subtotal * self.val / 100)
        return Decimal('0')


class Loyalty(IDiscount):
    def __init__(self, pct: Decimal, days: int, name: str):
        self.pct = Decimal(str(pct))
        self.days = days
        self.name = name

    @property
    def stage(self):
        return 'percent'

    @property
    def is_loyalty(self):
        return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        last = ctx.order.customer.last_purchase_date
        if not last or last > ctx.order.created_at:
            return None
        diff = (ctx.order.created_at - last).days
        if 0 <= diff <= self.days:
            amt = rnd(ctx.current_subtotal * self.pct / 100)
            if amt > 0:
                amt = min(amt, ctx.current_subtotal)
                ctx.current_subtotal -= amt
                return AppliedDiscount(self.name, amt, f"Покупка была {diff} дн. назад")
        return None


class FirstOrder(IDiscount):
    def __init__(self, pct: Decimal, name: str):
        self.pct = Decimal(str(pct))
        self.name = name

    @property
    def stage(self):
        return 'percent'

    @property
    def is_first_order(self):
        return True

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.order.customer.is_first_order:
            amt = rnd(ctx.current_subtotal * self.pct / 100)
            if amt > 0:
                amt = min(amt, ctx.current_subtotal)
                ctx.current_subtotal -= amt
                return AppliedDiscount(self.name, amt, "Скидка на первый заказ 10%")
        return None


class FreeDelivery(IDiscount):
    def __init__(self, thresh: Decimal, name: str):
        self.thresh = Decimal(str(thresh))
        self.name = name

    @property
    def stage(self):
        return 'delivery'

    def apply(self, ctx: DiscountContext) -> Optional[AppliedDiscount]:
        if ctx.current_subtotal > self.thresh and ctx.current_delivery > 0:
            amt = ctx.current_delivery
            ctx.current_delivery = Decimal('0')
            return AppliedDiscount(self.name, amt, f"Бесплатная доставка > {self.thresh}")
        return None


class Registry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.creators = {}
        return cls._instance

    def register(self, t: str, c: Callable):
        self.creators[t] = c

    def create(self, t: str, cfg: Dict) -> IDiscount:
        if t not in self.creators:
            raise ValueError(f"Неизвестный тип скидки: {t}")
        return self.creators[t](cfg)


reg = Registry()
reg.register("percent", lambda c: Percent(c['value'], c['name']))
reg.register("fixed", lambda c: Fixed(c['value'], c['threshold'], c['name']))
reg.register("threeForTwo", lambda c: ThreeForTwo(c['category'], c['name']))
reg.register("loyalty", lambda c: Loyalty(c['percent'], c['days'], c['name']))
reg.register("firstOrder", lambda c: FirstOrder(c['percent'], c['name']))
reg.register("freeDelivery", lambda c: FreeDelivery(c['threshold'], c['name']))
reg.register("promoCode", lambda c: Promo(c['code'], c['isPercent'], c['value'], c.get('expiry'), c['name']))


class Factory:
    @staticmethod
    def create(cfg_list: List[Dict]) -> List[IDiscount]:
        return [reg.create(c['type'], c) for c in cfg_list]


class PricingEngine:
    def calculate(self, order: Order, discounts: List[IDiscount]) -> PricingResult:
        base_sub = sum(i.product.base_price * i.quantity for i in order.items)
        base_total = rnd(base_sub + order.delivery_cost)
        ctx = DiscountContext(order, base_sub, order.delivery_cost)

        stages = {'3x2': [], 'percent': [], 'fixed': [], 'delivery': []}
        for d in discounts:
            stages[d.stage].append(d)

        for d in stages['3x2']:
            res = d.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        best_pct = None
        max_amt = Decimal('0')
        for d in stages['percent']:
            if not d.is_loyalty and not d.is_first_order:
                amt = d.get_potential(ctx)
                if amt > max_amt or (amt == max_amt and amt > 0 and d.is_percent_promo):
                    max_amt = amt
                    best_pct = d
        if best_pct and max_amt > 0:
            res = best_pct.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        for d in stages['percent'] + stages['fixed']:
            if d.is_fixed_promo or d.stage == 'fixed':
                res = d.apply(ctx)
                if res:
                    ctx.applied_discounts.append(res)

        for d in stages['percent']:
            if d.is_loyalty or d.is_first_order:
                res = d.apply(ctx)
                if res:
                    ctx.applied_discounts.append(res)

        for d in stages['delivery']:
            res = d.apply(ctx)
            if res:
                ctx.applied_discounts.append(res)

        final_total = rnd(max(Decimal('0'), ctx.current_subtotal) + ctx.current_delivery)
        return PricingResult(base_total, ctx.applied_discounts, final_total)