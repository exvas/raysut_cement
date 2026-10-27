# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_system_timezone, now_datetime

from raysut_cement.raysut_cement.crosschex_cloud import client
from raysut_cement.raysut_cement.crosschex_cloud.api import attendance
from raysut_cement.raysut_cement.crosschex_cloud.reconciliation import _missing_records


def local(utc_iso):
	return datetime.fromisoformat(utc_iso).astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


class NoCommitTestCase(FrappeTestCase):
	"""The import code commits in batches and log_error commits on its own; stop both
	so every test rolls back."""

	def setUp(self):
		for patcher in (patch.object(frappe.db, "commit"), patch.object(frappe, "log_error")):
			patcher.start()
			self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)


def webhook_record(uuid, checktime, workno="4711"):
	return {"uuid": uuid, "checktime": checktime, "employee": {"workno": workno}, "device": {"name": "Gate 1"}}


class TestCrossChexImport(NoCommitTestCase):
	def setUp(self):
		super().setUp()
		self.employee = make_employee("crosschex.test@example.com", attendance_device_id="4711")

	def test_webhook_and_api_records_normalise_the_same(self):
		from_webhook = attendance.normalise_record(webhook_record("u1", "2026-10-20T03:00:00+00:00"))
		from_api = attendance.normalise_record(
			{"emp_pin": "4711", "check_time": "2026-10-20T03:00:00+00:00", "id": "u1", "device": {"name": "Gate 1"}}
		)
		self.assertEqual(from_webhook, from_api)

	def test_punches_become_alternating_checkins_in_site_time(self):
		attendance.create_attendance_log(
			[
				webhook_record("cx-test-1", "2026-10-20T03:00:00+00:00"),
				webhook_record("cx-test-2", "2026-10-20T12:30:00+00:00"),
			]
		)
		logs = frappe.get_all(
			"Employee Checkin",
			filters={"employee": self.employee, "custom_crosschex_uuid": ("in", ["cx-test-1", "cx-test-2"])},
			fields=["time", "log_type", "device_id", "custom_crosschex_uuid"],
			order_by="time",
		)
		self.assertEqual([l.log_type for l in logs], ["IN", "OUT"])
		self.assertEqual(logs[0].time, local("2026-10-20T03:00:00+00:00"))
		self.assertEqual(logs[0].device_id, "Gate 1")
		self.assertEqual(logs[1].custom_crosschex_uuid, "cx-test-2")

	def test_late_uploaded_earlier_punch_is_in(self):
		attendance.create_attendance_log([webhook_record("cx-late-2", "2026-10-21T12:00:00+00:00")])
		attendance.create_attendance_log([webhook_record("cx-late-1", "2026-10-21T04:00:00+00:00")])
		log_type = frappe.db.get_value("Employee Checkin", {"custom_crosschex_uuid": "cx-late-1"}, "log_type")
		self.assertEqual(log_type, "IN")

	def test_duplicates_are_skipped(self):
		record = webhook_record("cx-dup", "2026-10-22T03:00:00+00:00")
		self.assertEqual(attendance.import_record(record), "created")
		self.assertEqual(attendance.import_record(record), "duplicate")
		same_time_new_uuid = webhook_record("cx-dup-other", "2026-10-22T03:00:00+00:00")
		self.assertEqual(attendance.import_record(same_time_new_uuid), "duplicate")

	def test_leading_zeros_in_workno_match(self):
		self.assertEqual(attendance.find_employee("004711"), self.employee)

	def test_unknown_employee_is_reported_not_imported(self):
		with self.assertRaises(LookupError):
			attendance.import_record(webhook_record("cx-ghost", "2026-10-20T03:00:00+00:00", workno="999999"))
		_processed, created, errors = attendance.create_attendance_log(
			[webhook_record("cx-ghost", "2026-10-20T03:00:00+00:00", workno="999999")]
		)
		self.assertEqual((created, errors), (0, 1))

	def test_reconciliation_finds_only_missing_uuids(self):
		attendance.import_record(webhook_record("cx-rec-1", "2026-10-23T03:00:00+00:00"))
		missing = _missing_records(
			[
				webhook_record("cx-rec-1", "2026-10-23T03:00:00+00:00"),
				webhook_record("cx-rec-2", "2026-10-23T12:00:00+00:00"),
			]
		)
		self.assertEqual([r["uuid"] for r in missing], ["cx-rec-2"])


class TestCrossChexWebhook(NoCommitTestCase):
	def set_webhook(self, enabled, token=None):
		settings = frappe.get_single("Crosschex Settings")
		settings.enable_realtime_sync = 0
		settings.enable_webhook = enabled
		settings.webhook_token = token
		settings.save(ignore_permissions=True)

	def test_disabled_webhook_rejects(self):
		self.set_webhook(0)
		with self.assertRaises(frappe.PermissionError):
			attendance.make_attendace(records=[])

	def test_wrong_token_rejects(self):
		self.set_webhook(1, "s3cret")
		with self.assertRaises(frappe.PermissionError):
			attendance.make_attendace(records=[], token="nope")

	def test_valid_token_is_logged(self):
		self.set_webhook(1, "s3cret")
		attendance.make_attendace(records=[{"uuid": "x"}], token="s3cret")
		log = frappe.get_last_doc("CrossChex Log")
		self.assertEqual(log.log_type, "Webhook")
		self.assertEqual(log.status, "Failed")
		self.assertEqual(log.records_processed, 1)


class TestCrossChexToken(NoCommitTestCase):
	def test_token_is_saved_and_expiry_converted_to_site_time(self):
		settings = frappe.get_single("Crosschex Settings")
		settings.enable_realtime_sync = 0
		settings.set("api_configurations", [])
		settings.append(
			"api_configurations",
			{"configuration_name": "Test", "api_url": "https://example.invalid", "api_key": "k", "api_secret": "s"},
		)
		settings.save(ignore_permissions=True)
		config = settings.api_configurations[0]

		expires_utc = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
		response = MagicMock(status_code=200)
		response.json.return_value = {
			"header": {"nameSpace": "authorize.token"},
			"payload": {"token": "tok-123", "expires": expires_utc.isoformat()},
		}
		with patch.object(client.requests, "post", return_value=response) as post:
			self.assertEqual(client.get_token(config), "tok-123")
			# second call uses the stored token instead of calling the API again
			self.assertEqual(client.get_token(config), "tok-123")
			self.assertEqual(post.call_count, 1)

		stored = frappe.get_doc("CrossChex API Configuration", config.name)
		self.assertEqual(stored.get_password("token"), "tok-123")
		self.assertEqual(stored.connection_status, "Connected")
		self.assertEqual(
			frappe.utils.get_datetime(stored.token_expires),
			expires_utc.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None),
		)
		self.assertGreater(frappe.utils.get_datetime(stored.token_expires), now_datetime())

	def test_auth_error_is_raised(self):
		response = MagicMock(status_code=200)
		response.json.return_value = {"header": {"nameSpace": "System"}, "payload": {"type": "AUTH_ERROR", "message": "bad"}}
		with patch.object(client.requests, "post", return_value=response):
			with self.assertRaises(client.CrossChexError):
				client.request_token("https://example.invalid/", "k", "wrong")
