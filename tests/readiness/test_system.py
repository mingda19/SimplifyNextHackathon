"""Happy paths and adversarial inputs against the real local services.

Assertions describe required behavior. Failures are findings, not mocks or
expected-failure markers; see docs/READINESS_AUDIT.md for the observed results.
"""
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg2.extras import Json


def item(sku=None, **changes):
    return {"sku": sku or f"QA-{uuid.uuid4().hex[:10]}", "name": "QA item",
            "category": "QA", "unit": "pack", "on_hand": 20,
            "opening_expiry_date": "2099-01-01", "opening_source": "DONATED",
            "reorder_point": 10, "avg_daily_draw": 2, "unit_cost_sgd": 2.40, **changes}


@pytest.fixture
def charity(api):
    body = {"email": f"qa-{uuid.uuid4().hex}@example.org", "password": "ReadinessTest123",
            "display_name": "QA Charity"}
    response = api("auth", "POST", "/auth/signup", json=body)
    assert response.status_code == 201, response.text
    return body, response.json(), {"Authorization": "Bearer " + response.json()["token"]}


def test_signup_login_reload_and_wrong_password(api, charity):
    body, created, headers = charity
    login = api("auth", "POST", "/auth/login", json={"email": body["email"].upper(), "password": body["password"]})
    assert login.status_code == 200
    assert login.json()["user"]["id"] == created["user"]["id"]
    me = api("auth", "GET", "/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "charity"
    wrong = api("auth", "POST", "/auth/login", json={"email": body["email"], "password": "wrong"})
    assert wrong.status_code == 401
    assert api("auth", "POST", "/auth/signup", json=body).status_code == 409


@pytest.mark.parametrize("password", ["", "short", "abcdefghij", "ABCDEFGHIJ", "1234567890", "Password123"])
def test_weak_password_is_rejected(api, password):
    response = api("auth", "POST", "/auth/signup", json={"email": "weak@example.org",
                   "password": password, "display_name": "QA"})
    assert response.status_code == 422


def test_recipient_cannot_administer_accounts(api, charity):
    _, _, headers = charity
    body = {"email": f"recipient-{uuid.uuid4().hex}@example.org", "password": "ReadinessTest123", "display_name": "QA recipient"}
    assert api("auth", "POST", "/auth/recipients", headers=headers, json=body).status_code == 201
    logged = api("auth", "POST", "/auth/login", json={k: body[k] for k in ("email", "password")}).json()
    recipient_headers = {"Authorization": "Bearer " + logged["token"]}
    assert api("auth", "GET", "/auth/recipients", headers=recipient_headers).status_code == 403


def test_self_signup_cannot_choose_recipient_role(api):
    response = api("auth", "POST", "/auth/signup", json={"email": "role@example.org", "password": "ReadinessTest123",
                   "display_name": "QA", "role": "recipient"})
    assert response.status_code == 400


def test_revoked_request_link_cannot_be_recorded_as_used(api, charity):
    _, _, headers = charity
    created = api("auth", "POST", "/auth/request-links", headers=headers).json()
    path = "/auth/request-links/" + created["token"]
    assert api("auth", "GET", path).status_code == 200
    assert api("auth", "DELETE", path, headers=headers).status_code == 200
    assert api("auth", "GET", path).status_code == 404
    response = api("auth", "POST", path + "/used")
    assert response.status_code in (404, 410), response.text


@pytest.mark.parametrize("service,path", [("inventory", "/inventory"), ("feedback", "/feedback"), ("agent", "/agent/runs")])
def test_private_reads_require_authentication(api, service, path):
    response = api(service, "GET", path, authenticated=False)
    assert response.status_code in (401, 403), f"Anonymous {service} read returned {response.status_code}"


def test_inventory_mutation_requires_authentication(api):
    response = api("inventory", "POST", "/inventory", json=item(), authenticated=False)
    assert response.status_code in (401, 403), f"Anonymous inventory creation returned {response.status_code}"


@pytest.mark.parametrize("field,value", [("on_hand", -1), ("avg_daily_draw", -1), ("unit_cost_sgd", -1),
                                         ("on_hand", 1.5), ("name", "   "), ("on_hand", True),
                                         ("on_hand", 2**31), ("on_hand", 10**100)])
def test_invalid_inventory_inputs_are_validation_errors(api, field, value):
    response = api("inventory", "POST", "/inventory", json=item(**{field: value}))
    assert response.status_code == 422, f"{field}={value!r}: {response.status_code} {response.text}"


def test_reserved_alerts_sku_cannot_create_an_unaddressable_item(api):
    response = api("inventory", "POST", "/inventory", json=item("alerts"))
    assert response.status_code == 422, response.text


def test_incoming_stock_is_allocatable(api):
    payload = item(on_hand=0)
    assert api("inventory", "POST", "/inventory", json=payload).status_code == 201
    path = "/inventory/" + payload["sku"]
    # The old PATCH is rejected; the Incoming tab records an explicit receipt.
    assert api("inventory", "PATCH", path, json={"on_hand": 10}).status_code == 422
    receipt = api("inventory", "POST", path + "/receive", json={
        "qty": 10, "expiry_date": "2099-01-01", "source": "DONATED"})
    assert receipt.status_code == 201, receipt.text
    assert api("inventory", "POST", path + "/allocate", json={
        "qty": 3, "lot_id": receipt.json()["lot_id"]}).status_code == 200
    detail = api("inventory", "GET", path).json()
    assert sum(lot["qty"] for lot in detail["lots"]) == detail["on_hand"], detail


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_feedback_is_rejected(api, text):
    response = api("feedback", "POST", "/feedback", json={"beneficiary_id": "QA-EMPTY", "text": text})
    assert response.status_code == 422, response.text


def test_feedback_is_stored_and_canned_extraction_is_aggregated(api):
    beneficiary = "QA-" + uuid.uuid4().hex
    response = api("feedback", "POST", "/feedback", json={"beneficiary_id": beneficiary,
                   "text": "We ran out of rice again", "lang": "en", "channel": "web"})
    assert response.status_code == 202
    feedback_id = response.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        entries = api("feedback", "GET", "/feedback").json()
        row = next(r for r in entries if r["id"] == feedback_id)
        if row["extraction_status"] != "pending":
            break
        time.sleep(0.1)
    assert row["extraction_status"] == "done", row
    assert "RICE-5KG" in row["mentioned_skus"], row
    needs = api("feedback", "GET", "/feedback/unmet-needs").json()
    # FAKE_LLM mentions rice but its ONLY unmet need is gluten-free bread.
    # Do not mistake that intentional canned response for live NLP accuracy.
    assert any(need["need"] == "gluten-free bread" and need["gap"] for need in needs["ranked"])


def test_aggregation_counts_distinct_people_and_resolves_each_need(api, stack):
    prefix = "QA-AGG-" + uuid.uuid4().hex
    need = "rice " + prefix
    for person in ("one", "one", "two"):
        stack["sql"]("""INSERT INTO feedback.feedback_entries
            (beneficiary_id, text, extraction_status, urgency, unmet_needs, summary_en)
            VALUES (%s, 'need rice', 'done', 4, %s, 'need rice')""",
            (prefix + person, Json([{"need": need, "confidence": 0.9, "suggested_category": "staples"}])))
    ranked = api("feedback", "GET", "/feedback/unmet-needs").json()["ranked"]
    result = next(row for row in ranked if row["need"] == need)
    assert result["frequency"] == 2 and result["score"] == 8
    assert result["mentioned_skus"] == ["RICE-5KG"] and not result["gap"]


def test_concurrent_orders_cannot_oversell_vendor_stock(api, stack):
    stack["sql"]("UPDATE vendor_offers SET available_qty=250 WHERE vendor_id='VENDOR-COMMUNITY' AND sku='RICE-5KG'")
    def order(_):
        return api("inventory", "POST", "/vendor/VENDOR-COMMUNITY/order", json={"sku": "RICE-5KG", "qty": 250}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(order, range(2)))
    assert sorted(statuses) == [200, 409]
    assert stack["sql"]("SELECT available_qty FROM vendor_offers WHERE vendor_id='VENDOR-COMMUNITY' AND sku='RICE-5KG'")[0][0] == 0


def test_negative_agent_list_limit_is_rejected(api):
    response = api("agent", "GET", "/agent/runs", params={"limit": -1})
    assert response.status_code == 422, response.text


def test_agent_run_cannot_be_approved_anonymously(api):
    response = api("agent", "POST", "/agent/runs", json={"charity_type": "B"})
    assert response.status_code == 202
    thread_id = response.json()["thread_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        row = api("agent", "GET", "/agent/runs/" + thread_id).json()
        if row["status"] != "running":
            break
        time.sleep(0.1)
    assert row["status"] == "pending_approval", row
    approved = api("agent", "POST", f"/agent/runs/{thread_id}/decision",
                   json={"decision": "approved", "decided_by": "forged@example.org"}, authenticated=False)
    assert approved.status_code in (401, 403), approved.text


def test_pricing_calibration_statistics_match_the_active_gate(api):
    import json
    from pathlib import Path
    forecast = api("pricing", "GET", "/price/forecast").json()
    artifact = json.loads((Path(__file__).resolve().parents[2] /
                          "services/price_forecaster/artifacts/calibration.json").read_text())
    active_threshold = artifact["confidence_thresholds"][f"{forecast['gate']['threshold']:.2f}"]
    cal = forecast["calibration"]
    if artifact["realised"]["test"]["threshold"] != active_threshold:
        # Unmeasured statistics must not be relabelled as results at the active gate.
        assert cal["test_dir_acc_at_gate"] is None
        assert cal["test_n_at_gate"] is None
        assert not cal["statistics_available_at_gate"]
    else:
        assert cal["test_n_at_gate"] == artifact["realised"]["test"]["n"]



@pytest.mark.parametrize("query", [{"series": "NOT-A-COMMODITY"}, {"horizon_months": 1}, {"horizon_months": 0}])
def test_pricing_rejects_unknown_series_and_unsupported_horizons(api, query):
    response = api("pricing", "GET", "/price/forecast", params=query)
    assert response.status_code == (404 if "series" in query else 422)


def test_all_real_forecasts_satisfy_the_contract(api):
    response = api("pricing", "GET", "/price/forecast/all")
    assert response.status_code == 200, response.text
    forecasts = response.json()["forecasts"]
    assert len(forecasts) == 26
    for forecast in forecasts:
        assert 0 <= forecast["confidence"] <= 1
        assert forecast["data_lag_months"] >= 0
        assert forecast["recommendation"] in {"BUY_NOW", "DEFER", "NEUTRAL"}
        assert math.isfinite(forecast["latest_index"])
        if not forecast["gate"]["passed"]:
            assert forecast["recommendation"] == "NEUTRAL"


@pytest.mark.parametrize("vendor,payload,expected,code", [
    ("VENDOR-HARVEST", {"sku": "RICE-5KG", "qty": 200}, 400, "MOQ_NOT_MET"),
    ("VENDOR-COMMUNITY", {"sku": "MILK-UHT-1L", "qty": 100}, 409, "OUT_OF_STOCK"),
    ("VENDOR-SLOW", {"sku": "RICE-5KG", "qty": 250}, 422, "LEAD_TIME_EXCEEDED"),
])
def test_real_vendor_error_contract(api, vendor, payload, expected, code):
    response = api("inventory", "POST", f"/vendor/{vendor}/quote", json=payload)
    assert response.status_code == expected
    assert set(response.json()) == {"code", "message", "remedy_hint", "alternatives"}
    assert response.json()["code"] == code
    assert response.json()["alternatives"]


def test_expired_lot_is_rejected(api):
    response = api("inventory", "POST", "/inventory/BEANS-CANNED-400G/allocate",
                   json={"lot_id": "LOT-BEANS-CANNED-400G-EXPIRED", "qty": 1})
    assert response.status_code == 410
    assert response.json()["code"] == "LOT_EXPIRED"


def test_rate_limit_retry_after(api):
    headers = {"X-Demo-Rate-Limit": "qa-" + uuid.uuid4().hex}
    body = {"sku": "RICE-5KG", "qty": 50}
    response = api("inventory", "POST", "/vendor/VENDOR-RAPID/quote", json=body, headers=headers)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    delay = int(response.headers["Retry-After"])
    assert 0 < delay <= 5
    time.sleep(delay)
    assert api("inventory", "POST", "/vendor/VENDOR-RAPID/quote", json=body, headers=headers).status_code == 200


@pytest.mark.parametrize('service,path,method,body', [
    ('inventory', '/inventory', 'GET', None),
    ('feedback', '/feedback', 'GET', None),
    ('agent', '/agent/runs', 'GET', None),
    ('agent', '/agent/runs', 'POST', {'charity_type': 'B'}),
    ('agent', '/agent/runs/nonexistent/decision', 'POST', {'decision': 'approved'}),
])
def test_recipient_cannot_access_private_workflows(api, charity, service, path, method, body):
    _, _, headers = charity
    person = {'email': f'permission-{uuid.uuid4().hex}@example.org',
              'password': 'ReadinessTest123', 'display_name': 'Recipient'}
    assert api('auth', 'POST', '/auth/recipients', headers=headers, json=person).status_code == 201
    token = api('auth', 'POST', '/auth/login', json={k: person[k] for k in ('email', 'password')}).json()['token']
    response = api(service, method, path, headers={'Authorization': 'Bearer ' + token}, json=body)
    assert response.status_code == 403


def test_service_credential_cannot_approve(api, stack):
    response = api('agent', 'POST', '/agent/runs/nonexistent/decision', authenticated=False,
                   headers={'X-Service-Token': stack['env']['SERVICE_AUTH_TOKEN']},
                   json={'decision': 'approved'})
    assert response.status_code == 401


def test_concurrent_same_order_key_commits_once(api, stack):
    stack['sql']('DELETE FROM operations')
    stack['sql']('DELETE FROM orders')
    stack['sql']("UPDATE vendor_offers SET available_qty=10000 WHERE vendor_id='VENDOR-COMMUNITY' AND sku='RICE-5KG'")
    body = {'sku': 'RICE-5KG', 'qty': 250, 'expected_unit_price_sgd': 2.25}
    headers = {'Idempotency-Key': 'concurrent-' + uuid.uuid4().hex}
    def order(_):
        return api('inventory', 'POST', '/vendor/VENDOR-COMMUNITY/order', json=body, headers=headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(order, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert stack['sql']('SELECT count(*) FROM orders')[0][0] == 1
    changed = api('inventory', 'POST', '/vendor/VENDOR-COMMUNITY/order',
                  json={**body, 'qty': 251}, headers=headers)
    assert changed.status_code == 409 and changed.json()['code'] == 'IDEMPOTENCY_CONFLICT'


def test_price_change_requires_new_approval(api, stack):
    response = api('inventory', 'POST', '/vendor/VENDOR-HARVEST/order',
                   json={'sku': 'RICE-5KG', 'qty': 250, 'expected_unit_price_sgd': 0.01},
                   headers={'Idempotency-Key': 'price-' + uuid.uuid4().hex})
    assert response.status_code == 409 and response.json()['code'] == 'PRICE_CHANGED'


def test_monthly_budget_cannot_be_overspent_by_concurrent_orders(api, stack):
    stack['sql']('DELETE FROM operations')
    stack['sql']('DELETE FROM orders')
    stack['sql']("UPDATE vendor_offers SET available_qty=10000 WHERE sku='RICE-5KG'")
    # Eight orders cost S$4,500. The next S$562.50 order must be refused.
    for _ in range(8):
        response = api('inventory', 'POST', '/vendor/VENDOR-COMMUNITY/order', json={'sku': 'RICE-5KG', 'qty': 250})
        assert response.status_code == 200, response.text
    def order(_):
        return api('inventory', 'POST', '/vendor/VENDOR-COMMUNITY/order', json={'sku': 'RICE-5KG', 'qty': 250})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(order, range(2)))
    assert all(r.status_code == 409 and r.json()['code'] == 'MONTHLY_BUDGET_EXCEEDED' for r in responses)
    assert stack['sql']('SELECT sum(qty * unit_price_sgd) FROM orders')[0][0] == 4500


def test_public_link_enforces_revocation_and_separates_participants(api, charity, stack):
    _, _, headers = charity
    link = api('auth', 'POST', '/auth/request-links', headers=headers).json()['token']
    def submit(participant):
        return api('feedback', 'POST', '/feedback', authenticated=False, json={
            'request_link': link, 'participant_id': participant, 'beneficiary_id': 'FORGED', 'text': 'Need rice'})
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    responses = [submit(first_id), submit(first_id), submit(second_id)]
    assert all(r.status_code == 202 for r in responses)
    ids = [r.json()['id'] for r in responses]
    rows = stack['sql']('SELECT beneficiary_id FROM feedback.feedback_entries WHERE id=ANY(%s) ORDER BY id', (ids,))
    assert rows[0][0] == rows[1][0] and rows[0][0] != rows[2][0]
    assert all(row[0].startswith('ANON-') for row in rows)
    assert api('auth', 'DELETE', '/auth/request-links/' + link, headers=headers).status_code == 200
    assert submit(first_id).status_code == 403


def test_concurrent_approvals_use_signed_identity_and_commit_once(api, charity, stack):
    _, created, headers = charity
    stack['sql']('DELETE FROM operations')
    stack['sql']('DELETE FROM orders')
    stack['sql']("UPDATE vendor_offers SET available_qty=10000 WHERE sku='RICE-5KG'")
    response = api('agent', 'POST', '/agent/runs', headers=headers, json={'charity_type': 'B'})
    assert response.status_code == 202
    thread_id = response.json()['thread_id']
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        row = api('agent', 'GET', '/agent/runs/' + thread_id, headers=headers).json()
        if row['status'] != 'running':
            break
        time.sleep(.1)
    assert row['status'] == 'pending_approval', row
    assert isinstance(row['summary'], dict)
    assert stack['sql']('SELECT count(*) FROM orders')[0][0] == 0
    def approve(_):
        return api('agent', 'POST', f'/agent/runs/{thread_id}/decision', headers=headers,
                   json={'decision': 'approved', 'decided_by': 'forged@example.org'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(approve, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    assert stack['sql']('SELECT count(*) FROM orders')[0][0] == 1
    saved = api('agent', 'GET', '/agent/runs/' + thread_id).json()
    assert saved['decided_by'] == created['user']['email']
    assert saved['outcome']['total_sgd'] > 0
