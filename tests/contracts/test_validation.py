"""Contract tests that do not require databases, service processes or model APIs."""
from datetime import date, timedelta
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'services'))
sys.path.insert(0, str(ROOT / 'services/inventory'))
from app.schemas import ItemCreate, ItemUpdate, ReceiptRequest, VendorQuoteRequest
from orchestrator.state import PlanStep
from app.services.pricing import calculate_local_price
from decimal import Decimal


def item(**values):
    return dict(sku='QA-RICE', name='Rice', category='Staples', unit='bag',
                reorder_point=10, avg_daily_draw=2, unit_cost_sgd='2.40', **values)


@pytest.mark.parametrize('value', [-1, 1.5, True, '', 2**31, 10**100])
@pytest.mark.parametrize('field', ['on_hand', 'reorder_point', 'avg_daily_draw'])
def test_stock_integers_are_strict_and_bounded(field, value):
    payload = item()
    payload[field] = value
    with pytest.raises(ValidationError):
        ItemCreate(**payload)
    with pytest.raises(ValidationError):
        ItemUpdate(**{field: value})


@pytest.mark.parametrize('sku', ['alerts', 'ALERTS', '../x', 'a/b', 'a?b', ' ', '#x'])
def test_invalid_or_reserved_skus(sku):
    payload = item()
    payload['sku'] = sku
    with pytest.raises(ValidationError):
        ItemCreate(**payload)


def test_opening_stock_requires_lot_metadata():
    with pytest.raises(ValidationError):
        ItemCreate(**item(on_hand=1))
    assert ItemCreate(**item(on_hand=1, opening_expiry_date='2099-01-01',
                            opening_source='DONATED')).on_hand == 1


@pytest.mark.parametrize('qty', [True, 0, -1, 2**31, 1.5])
def test_vendor_and_receipt_quantities(qty):
    with pytest.raises(ValidationError):
        VendorQuoteRequest(sku='RICE', qty=qty)
    with pytest.raises(ValidationError):
        ReceiptRequest(qty=qty, expiry_date='2099-01-01', source='DONATED')


def test_expired_receipt_is_rejected():
    with pytest.raises(ValidationError):
        ReceiptRequest(qty=2, expiry_date=date.today()-timedelta(days=1), source='PURCHASED')


@pytest.mark.parametrize('step', [
    {'action': 'place_order', 'qty': 0, 'vendor_id': 'VENDOR'},
    {'action': 'place_order', 'qty': -1, 'vendor_id': 'VENDOR'},
    {'action': 'place_order', 'qty': True, 'vendor_id': 'VENDOR'},
    {'action': 'place_order', 'qty': 1},
    {'action': 'request_quote', 'qty': 1, 'vendor_id': ' '},
    {'action': 'reallocate_lot', 'qty': 1},
])
def test_non_executable_plan_steps(step):
    with pytest.raises(ValidationError):
        PlanStep(sku='RICE', **step)


def test_flag_and_allocation_steps():
    assert PlanStep(action='flag_for_human', sku='GAP').qty == 0
    assert PlanStep(action='reallocate_lot', sku='RICE', qty=1, lot_id='LOT').lot_id == 'LOT'


def test_money_uses_displayed_unit_price():
    price = calculate_local_price(unit_cost_sgd=Decimal('2.50'), vendor_multiplier=Decimal('1'),
                                  qty=250, bulk_discount_threshold=250, bulk_discount_rate=Decimal('.10'))
    assert price.unit_price_sgd == Decimal('2.25')
    assert price.total_price_sgd == Decimal('562.50')


def test_fake_adaptation_compares_live_vendor_prices():
    from orchestrator.fixtures import fake_adaptation
    step = {'action': 'place_order', 'sku': 'RICE-5KG', 'qty': 200, 'vendor_id': 'VENDOR-HARVEST'}
    result = fake_adaptation(step, {'code': 'MOQ_NOT_MET', 'alternatives': [
        {'vendor_id': 'VENDOR-HARVEST', 'minimum_qty': 250, 'unit_price_sgd': 2.4},
        {'vendor_id': 'VENDOR-COMMUNITY', 'suggested_qty': 250, 'unit_price_sgd': 2.25, 'available_qty': 1600},
    ]})
    revised = PlanStep.model_validate(result['revised_step'])
    assert revised.qty == 250 and revised.vendor_id == 'VENDOR-COMMUNITY'
