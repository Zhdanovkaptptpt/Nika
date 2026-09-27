import unittest
from datetime import date
from decimal import Decimal
from core import (
    Product, CartItem, Customer, Order, PricingEngine,
    Percent, Fixed, ThreeForTwo, Promo, Loyalty, FreeDelivery
)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.eng = PricingEngine()
        self.today = date(2026, 9, 24)

    def _order(self, items, deliv=Decimal('500'), first=False, last_purchase=None, promo=None):
        return Order("o1", Customer("c1", last_purchase, first), items, promo, self.today, deliv)

    def _print_result(self, test_name, order, result):
        print(f"\n{'=' * 60}")
        print(f"ТЕСТ: {test_name}")
        print(f"{'=' * 60}")
        print("ВХОД:")
        for item in order.items:
            total = item.product.base_price * item.quantity
            print(f"  - {item.product.name}: {item.quantity} шт × {item.product.base_price} = {total}")
        print(f"  Доставка: {order.delivery_cost}")
        print(f"  Промокод: {order.promo_code or 'нет'}")
        print(f"  Первый заказ: {order.customer.is_first_order}")
        if order.customer.last_purchase_date:
            days = (order.created_at - order.customer.last_purchase_date).days
            print(f"  Последняя покупка: {days} дн. назад")

        print("\nВЫХОД:")
        print(f"  Базовая сумма: {result.base_total}")
        if result.applied_discounts:
            print(f"  Применённые скидки:")
            for d in result.applied_discounts:
                print(f"    - {d.name}: -{d.amount} ({d.reason})")
        else:
            print(f"  Скидки не применены")
        print(f"  ИТОГО: {result.final_total}")
        print(f"{'=' * 60}\n")

    def test_1_pos(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('1000'), "C"), 2)])
        res = self.eng.calculate(order, [Percent(10, "10%")])
        self._print_result("Позитивный тест процентной скидки", order, res)
        self.assertEqual(res.applied_discounts[0].amount, Decimal('200.00'))

    def test_2_neg(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('0'), "C"), 1)])
        res = self.eng.calculate(order, [Percent(10, "10%")])
        self._print_result("Негативный тест (скидка не применяется)", order, res)
        self.assertEqual(len(res.applied_discounts), 0)

    def test_3_3x2_then_pct(self):
        order = self._order([CartItem(Product("1", "Книга", Decimal('300'), "Books"), 3)])
        discounts = [ThreeForTwo("Books", "3x2"), Percent(10, "10%")]
        res = self.eng.calculate(order, discounts)
        self._print_result("3 по 2 + процент", order, res)
        self.assertEqual(res.applied_discounts[0].name, "3x2")
        self.assertEqual(res.applied_discounts[1].amount, Decimal('60.00'))

    def test_4_promo_vs_pct_max(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('1000'), "C"), 2)], promo="P10")
        discounts = [Percent(5, "5%"), Promo("P10", True, 10, None, "Promo10")]
        res = self.eng.calculate(order, discounts)
        self._print_result("Промокод vs процент (максимум)", order, res)
        self.assertEqual(res.applied_discounts[0].name, "Promo10")
        self.assertEqual(res.applied_discounts[0].amount, Decimal('200.00'))

    def test_5_lower_bound(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('100'), "C"), 1)])
        res = self.eng.calculate(order, [Fixed(500, 50, "Fix")])
        self._print_result("Нижняя граница (не уходит в минус)", order, res)
        self.assertEqual(res.final_total, Decimal('500.00'))

    def test_6_rounding(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('10.015'), "C"), 2)])
        res = self.eng.calculate(order, [Percent(10, "10%")])
        self._print_result("Округление half to even", order, res)
        self.assertEqual(res.applied_discounts[0].amount, Decimal('2.00'))

    def test_7_boundary_fixed(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('2000'), "C"), 1)])
        res = self.eng.calculate(order, [Fixed(500, 2000, "Fix")])
        self._print_result("Граница фиксированной скидки", order, res)
        self.assertEqual(len(res.applied_discounts), 1)

    def test_8_boundary_loyalty(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('1000'), "C"), 1)],
                            last_purchase=date(2026, 8, 25))
        res = self.eng.calculate(order, [Loyalty(5, 30, "Loy")])
        self._print_result("Граница лояльности (30 дней)", order, res)
        self.assertEqual(len(res.applied_discounts), 1)

    def test_9_boundary_promo(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('1000'), "C"), 1)], promo="P")
        res = self.eng.calculate(order, [Promo("P", True, 10, "2026-09-24", "Promo")])
        self._print_result("Граница промокода (дата окончания)", order, res)
        self.assertEqual(len(res.applied_discounts), 1)

    def test_10_boundary_delivery(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('5000'), "C"), 1)])
        res = self.eng.calculate(order, [FreeDelivery(5000, "FreeDel")])
        self._print_result("Граница доставки (строго больше)", order, res)
        self.assertEqual(len(res.applied_discounts), 0)

    def test_11_breakdown(self):
        order = self._order([
            CartItem(Product("1", "Книга", Decimal('1000'), "Books"), 3),
            CartItem(Product("2", "Кружка", Decimal('500'), "Mugs"), 2)
        ], deliv=Decimal('600'), last_purchase=date(2026, 9, 10))
        res = self.eng.calculate(order, [ThreeForTwo("Books", "3x2"), Loyalty(5, 30, "Loy")])
        self._print_result("Breakdown (полный разбор)", order, res)
        self.assertEqual(res.base_total, Decimal('4600.00'))
        self.assertEqual(len(res.applied_discounts), 2)
        self.assertEqual(res.applied_discounts[0].amount, Decimal('1000.00'))
        self.assertEqual(res.final_total, Decimal('3450.00'))

    def test_12_promo_vs_pct_tie(self):
        order = self._order([CartItem(Product("1", "Товар", Decimal('1000'), "C"), 2)], promo="P10")
        res = self.eng.calculate(order, [Percent(10, "10%"), Promo("P10", True, 10, None, "Promo10")])
        self._print_result("Промокод vs процент (равенство)", order, res)
        self.assertEqual(res.applied_discounts[0].name, "Promo10")


if __name__ == '__main__':
    unittest.main()