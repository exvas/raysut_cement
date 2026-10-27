# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Turn CrossChex Cloud punch records into Employee Checkin entries."""

import hmac
import json

import frappe

from raysut_cement.raysut_cement.crosschex_cloud.client import to_system_time
from raysut_cement.raysut_cement.settings import is_enabled

COMMIT_EVERY = 100


def normalise_record(record):
	"""Map a webhook or API record to {workno, checktime, uuid, device}."""
	employee = record.get("employee") if isinstance(record.get("employee"), dict) else {}
	device = record.get("device") if isinstance(record.get("device"), dict) else {}
	return frappe._dict(
		workno=(
			record.get("emp_pin")
			or record.get("employee_id")
			or record.get("empno")
			or record.get("emp_code")
			or record.get("pin")
			or record.get("workno")
			or employee.get("workno")
			or employee.get("pin")
			or employee.get("emp_pin")
		),
		checktime=record.get("checktime") or record.get("check_time") or record.get("time"),
		uuid=record.get("uuid") or record.get("id") or record.get("record_id"),
		device=device.get("name") or "",
	)


def find_employee(workno):
	"""Active Employee whose attendance_device_id matches the CrossChex workno (leading zeros ignored)."""
	value = str(workno).strip()
	candidates = {value}
	if value.isdigit():
		candidates.add(str(int(value)))
	return frappe.db.get_value(
		"Employee", {"attendance_device_id": ("in", list(candidates)), "status": "Active"}, "name"
	)


def determine_log_type(employee, checkin_time):
	"""Alternate IN/OUT from the employee's previous punch on the same day; the first punch is IN."""
	previous = frappe.db.sql(
		"""
		SELECT log_type FROM `tabEmployee Checkin`
		WHERE employee = %s AND DATE(time) = %s AND time < %s
		ORDER BY time DESC LIMIT 1
		""",
		(employee, checkin_time.date(), checkin_time),
	)
	if not previous:
		return "IN"
	return "OUT" if previous[0][0] == "IN" else "IN"


def import_record(raw):
	"""Create one Employee Checkin. Returns "created" or "duplicate"; raises on bad data."""
	record = normalise_record(raw)
	if not record.workno:
		raise ValueError("No employee number (workno) in record")
	if not record.checktime:
		raise ValueError("No checktime in record")

	if record.uuid and frappe.db.exists("Employee Checkin", {"custom_crosschex_uuid": record.uuid}):
		return "duplicate"

	employee = find_employee(record.workno)
	if not employee:
		raise LookupError(f"No active Employee with Attendance Device ID {record.workno}")

	checkin_time = to_system_time(record.checktime)
	if frappe.db.exists("Employee Checkin", {"employee": employee, "time": checkin_time}):
		return "duplicate"

	frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"time": checkin_time,
			"log_type": determine_log_type(employee, checkin_time),
			"device_id": record.device,
			"custom_crosschex_uuid": record.uuid,
		}
	).insert(ignore_permissions=True)
	return "created"


def create_attendance_log(records):
	"""Import a batch of records. Returns (processed, created, errors)."""
	if isinstance(records, str):
		records = json.loads(records)

	processed = created = errors = 0
	for raw in records:
		processed += 1
		try:
			if import_record(raw) == "created":
				created += 1
		except LookupError as e:
			errors += 1
			_log_missing_employee_once(e, raw)
		except Exception as e:
			errors += 1
			frappe.log_error(title="CrossChex - record not imported", message=f"{e}\n\n{json.dumps(raw, default=str)}")
		if processed % COMMIT_EVERY == 0:
			frappe.db.commit()

	frappe.db.commit()
	return processed, created, errors


def _log_missing_employee_once(error, raw):
	"""Unknown device IDs repeat on every sync; log each one at most once a day."""
	cache_key = f"crosschex_missing_emp_{normalise_record(raw).workno}"
	if frappe.cache.get_value(cache_key):
		return
	frappe.cache.set_value(cache_key, 1, expires_in_sec=86400)
	frappe.log_error(title="CrossChex - employee not found", message=f"{error}\n\n{json.dumps(raw, default=str)}")


@frappe.whitelist(allow_guest=True)
def make_attendace(**kwargs):
	"""Webhook endpoint for CrossChex Cloud (name kept as configured in CrossChex)."""
	settings = frappe.get_cached_doc("Crosschex Settings")
	if not is_enabled("enable_crosschex") or not settings.enable_webhook:
		raise frappe.PermissionError("CrossChex webhook is disabled")

	expected = settings.get_password("webhook_token", raise_exception=False)
	supplied = kwargs.get("token") or frappe.get_request_header("X-Webhook-Token") or ""
	if expected and not hmac.compare_digest(str(supplied), expected):
		raise frappe.PermissionError("Invalid CrossChex webhook token")

	records = kwargs.get("records")
	log = frappe.get_doc(
		{
			"doctype": "CrossChex Log",
			"log_type": "Webhook",
			"status": "Processing",
			"request_method": frappe.request.method if getattr(frappe, "request", None) else "POST",
			"webhook_source": "CrossChex Cloud",
			"request_payload": json.dumps(records, default=str) if not isinstance(records, str) else records,
		}
	).insert(ignore_permissions=True)

	try:
		if not records:
			raise ValueError("Payload has no 'records'")
		processed, created, errors = create_attendance_log(records)
		log.update(
			{
				"records_processed": processed,
				"checkins_created": created,
				"status": "Success" if not errors else ("Partial Success" if created else "Failed"),
				"processing_status": "Completed",
				"error_message": f"{errors} records failed - see Error Log" if errors else None,
			}
		)
	except Exception as e:
		log.update({"status": "Failed", "processing_status": "Completed", "error_message": str(e)})
		frappe.log_error(title="CrossChex Webhook")
	log.save(ignore_permissions=True)
	frappe.db.commit()

	# Always answer 200 so CrossChex does not keep retrying a payload we have logged
	frappe.local.response["code"] = 200
	frappe.local.response["msg"] = f"Processed {log.records_processed or 0} records, created {log.checkins_created or 0} check-ins"
