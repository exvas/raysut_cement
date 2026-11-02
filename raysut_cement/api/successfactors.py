# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Read-only API for SAP SuccessFactors (directly or through SAP CPI) to pull attendance.

	GET /api/method/raysut_cement.api.successfactors.attendance
	GET /api/method/raysut_cement.api.successfactors.punches
	GET /api/method/raysut_cement.api.successfactors.employees

Authorization: token <api_key>:<api_secret> of a user with the "SuccessFactors Integration" role.
Every response is {"message": {"data": [...], "page", "page_size", "total", "has_more"}}.
Times are ISO 8601 with the site's UTC offset (Asia/Muscat, +04:00). The full contract is in the
API specification handed to SAP.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, get_datetime, get_system_timezone, getdate

ROLE = "SuccessFactors Integration"
MAX_DAYS = 62
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 500


@frappe.whitelist(methods=["GET"])
def attendance(from_date, to_date, employee=None, modified_since=None, page=1, page_size=DEFAULT_PAGE_SIZE):
	"""One record per employee per day that has submitted attendance."""
	check_access()
	from_date, to_date = date_range(from_date, to_date)
	filters = {"docstatus": 1, "attendance_date": ("between", [from_date, to_date])}
	add_common_filters(filters, employee, modified_since)
	rows, meta = fetch(
		"Attendance", filters,
		["name", "employee", "employee_name", "company", "department", "attendance_date", "status", "leave_type",
		 "shift", "in_time", "out_time", "working_hours", "custom_ot1_hours", "custom_ot2_hours", "under_time_minutes",
		 "late_entry", "late_minutes", "custom_missing_punch", "custom_is_holiday_work", "modified"],
		"attendance_date asc, employee asc", page, page_size,
	)
	ids = employee_ids({r.employee for r in rows})
	meta["data"] = [
		{
			"attendance_id": r.name,
			**ids.get(r.employee, {}),
			"employee_name": r.employee_name,
			"company": r.company,
			"department": r.department,
			"date": str(r.attendance_date),
			"status": r.status,
			"leave_type": r.leave_type,
			"shift": r.shift,
			"check_in": iso(r.in_time),
			"check_out": iso(r.out_time),
			"worked_hours": flt(r.working_hours, 2),
			"ot1_hours": flt(r.custom_ot1_hours, 2),
			"ot2_hours": flt(r.custom_ot2_hours, 2),
			"under_time_hours": round(cint(r.under_time_minutes) / 60, 2),
			"late": bool(r.late_entry),
			"late_minutes": cint(r.late_minutes),
			"missing_punch": bool(r.custom_missing_punch),
			"holiday_work": bool(r.custom_is_holiday_work),
			"last_modified": iso(r.modified),
		}
		for r in rows
	]
	return meta


@frappe.whitelist(methods=["GET"])
def punches(from_date, to_date, employee=None, modified_since=None, page=1, page_size=DEFAULT_PAGE_SIZE):
	"""Raw clock-in / clock-out events from the attendance devices."""
	check_access()
	from_date, to_date = date_range(from_date, to_date)
	filters = {"time": ("between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"])}
	add_common_filters(filters, employee, modified_since)
	rows, meta = fetch(
		"Employee Checkin", filters, ["name", "employee", "time", "log_type", "device_id", "modified"],
		"time asc, employee asc", page, page_size,
	)
	ids = employee_ids({r.employee for r in rows})
	meta["data"] = [
		{
			"punch_id": r.name,
			**ids.get(r.employee, {}),
			"time": iso(r.time),
			"direction": r.log_type,  # IN, OUT or null when the device did not say
			"device": r.device_id,
			"last_modified": iso(r.modified),
		}
		for r in rows
	]
	return meta


@frappe.whitelist(methods=["GET"])
def employees(status="Active", modified_since=None, page=1, page_size=DEFAULT_PAGE_SIZE):
	"""The employees the attendance data refers to, with the IDs used in it."""
	check_access()
	filters = {}
	if status and status != "All":
		filters["status"] = status
	add_common_filters(filters, None, modified_since)
	rows, meta = fetch(
		"Employee", filters,
		["name", "employee_number", "sf_user_id", "employee_name", "status", "company", "department", "designation",
		 "default_shift", "date_of_joining", "relieving_date", "modified"],
		"name asc", page, page_size,
	)
	meta["data"] = [
		{
			"employee_id": r.name,
			"employee_number": r.employee_number,
			"sf_user_id": r.sf_user_id or r.employee_number,
			"employee_name": r.employee_name,
			"status": r.status,
			"company": r.company,
			"department": r.department,
			"designation": r.designation,
			"shift": r.default_shift,
			"date_of_joining": str(r.date_of_joining) if r.date_of_joining else None,
			"relieving_date": str(r.relieving_date) if r.relieving_date else None,
			"last_modified": iso(r.modified),
		}
		for r in rows
	]
	return meta


# ---------------------------------------------------------------- helpers


def check_access():
	if not set(frappe.get_roles()) & {ROLE, "System Manager"}:
		frappe.throw(_("Not permitted: the API user needs the {0} role").format(ROLE), frappe.PermissionError)


def date_range(from_date, to_date):
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("from_date must not be after to_date"))
	if date_diff(to_date, from_date) >= MAX_DAYS:
		frappe.throw(_("Ask for at most {0} days per call").format(MAX_DAYS))
	return from_date, to_date


def add_common_filters(filters, employee, modified_since):
	if employee:
		# accepts the ERPNext ID, the E No. or the SuccessFactors user ID
		filters["employee"] = resolve_employee(employee)
	if modified_since:
		filters["modified"] = (">", local_datetime(modified_since))


def resolve_employee(value):
	for field in ("name", "sf_user_id", "employee_number"):
		name = frappe.db.get_value("Employee", {field: value})
		if name:
			return name
	frappe.throw(_("Unknown employee {0}").format(value), frappe.DoesNotExistError)


def fetch(doctype, filters, fields, order_by, page, page_size):
	page, page_size = max(cint(page), 1), min(max(cint(page_size), 1), MAX_PAGE_SIZE)
	total = frappe.db.count(doctype, filters)
	rows = frappe.get_all(
		doctype, filters=filters, fields=fields, order_by=order_by,
		limit_start=(page - 1) * page_size, limit_page_length=page_size,
	)
	return rows, {"page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}


def employee_ids(names):
	if not names:
		return {}
	return {
		e.name: {"employee_id": e.name, "employee_number": e.employee_number, "sf_user_id": e.sf_user_id or e.employee_number}
		for e in frappe.get_all("Employee", {"name": ("in", list(names))}, ["name", "employee_number", "sf_user_id"])
	}


def iso(value):
	"""Site-local datetime -> ISO 8601 with the UTC offset, e.g. 2026-10-07T07:08:00+04:00."""
	if not value:
		return None
	return get_datetime(value).replace(microsecond=0, tzinfo=ZoneInfo(get_system_timezone())).isoformat()


def local_datetime(value):
	"""An ISO timestamp (any offset, or none = site time) -> naive site-local datetime for filtering."""
	value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
	if value.tzinfo:
		value = value.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return value
