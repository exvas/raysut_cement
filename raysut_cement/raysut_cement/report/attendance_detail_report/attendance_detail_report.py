# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""The TAMS "Detail Report": every day of a range for each employee, with a day code (PR, AB, OF, a
leave code, ...), In and Out, worked / total / base / regular hours, OT1, OT2, under time, remarks and
the In / Out exceptions against the shift (E = early, L = late), then a TOTAL row. Hours read as TAMS
writes them, hours.minutes: 8.07 is 8 hours 7 minutes.
"""

import datetime
import re

import frappe
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, to_timedelta

from raysut_cement.raysut_cement.attendance.overtime import get_shift, required_hours
from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import get_employees

MAX_DAYS = 366
WORKED = ("Present", "Work From Home", "Half Day")
# leave type -> the short code on the report; any other type gets its initials
LEAVE_CODES = {
	"Annual Leave": "AL",
	"Sick Leave": "SL",
	"Sick Leave - Unpaid": "SLU",
	"Emergency Leave": "EL",
	"Special Leave": "SPL",
	"Special Leave - Hajj": "SPH",
	"Special Leave - Marriage": "SPM",
	"Special Leave - Maternity": "SPML",
	"Special Leave - Study": "SPS",
	"Lieu Leave": "LL",
	"Leave Without Pay": "LWP",
	"Leave Without Pay (RCC)": "LWP",
	"Casual Leave": "CL",
	"Compensatory Off": "CO",
	"Privilege Leave": "PL",
	"Maternity Leave": "ML",
	"Paternity Leave": "PTL",
	"Compassionate Leave": "CPL",
	"Official Duty": "OD",
	"Official Mission": "OM",
	"Accident Leave": "ACL",
	"Accompany Patient 15 Days": "AP",
	"Accompany Patient 30 Days": "AP",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.from_date and filters.to_date):
		return get_columns(filters), []
	start, end = getdate(filters.from_date), getdate(filters.to_date)
	if start > end:
		frappe.throw(_("From Date must be before To Date"))
	if date_diff(end, start) >= MAX_DAYS:
		frappe.throw(_("Pick at most {0} days").format(MAX_DAYS))

	employees = get_employees(frappe._dict(filters, status="All"))
	employees = [e for e in employees if in_service(e, start, end)]
	if not employees:
		return get_columns(filters), []

	names = [e.name for e in employees]
	extra = {
		e.name: e
		for e in frappe.get_all(
			"Employee", {"name": ("in", names)}, ["name", "employee_number", "attendance_device_id"]
		)
	}
	attendance = {}
	for a in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, end])},
		fields=[
			"name", "employee", "attendance_date", "status", "leave_type", "shift", "in_time", "out_time",
			"working_hours", "custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours", "under_time_minutes",
			"custom_missing_punch", "custom_is_holiday_work", "late_entry",
		],
		order_by="attendance_date, modified",
	):
		attendance[(a.employee, getdate(a.attendance_date))] = a

	holidays = get_holidays(employees, start, end)
	rows = []
	for e in employees:
		info = {
			"employee": e.name,
			"employee_name": e.employee_name,
			"emp_no": extra[e.name].employee_number or e.name,
			"card_no": extra[e.name].attendance_device_id or extra[e.name].employee_number or "",
			"department": e.department or "",
			"designation": e.designation or "",
		}
		days, totals = [], {"reg": 0, "ot1": 0, "ot2": 0, "ut": 0, "wk": 0, "tot": 0}
		day = max(start, getdate(e.date_of_joining)) if e.date_of_joining else start
		last = min(end, getdate(e.relieving_date)) if e.relieving_date else end
		while day <= last:
			row = day_row(e, day, attendance.get((e.name, day)), holidays.get(e.name, {}).get(day))
			for key in totals:
				totals[key] += row.pop(f"_{key}")
			row.update(info, sr=len(days) + 1)
			days.append(row)
			day = add_days(day, 1)
		rows += days
		rows.append({
			**info, "is_total": 1, "remarks": _("TOTAL"),
			**{key: hm(minutes, blank="0.00") for key, minutes in totals.items()},
		})
	return get_columns(filters, len(employees) > 1), rows


def in_service(e, start, end):
	return (not e.date_of_joining or getdate(e.date_of_joining) <= end) and (
		not e.relieving_date or getdate(e.relieving_date) >= start
	)


def day_row(e, day, a, holiday):
	"""One day: its code, times and hours, with the minutes behind the totals in _wk, _tot, ... ."""
	row = {"date": day, "day": day.strftime("%a"), "code": "", "remarks": "", "is_off": 0, "base": "-"}
	minutes = {"_wk": 0, "_tot": 0, "_reg": 0, "_ot1": 0, "_ot2": 0, "_ut": 0}
	remarks = []
	if not a:
		if holiday:
			row.update(code="OF", is_off=1)
			remarks.append(holiday)
		elif day <= getdate():
			row["code"] = "NM"
			remarks.append(_("Not marked"))
	elif a.status == "On Leave" or (a.status == "Half Day" and a.leave_type):
		row["code"] = leave_code(a.leave_type) if a.status == "On Leave" else "HD"
		remarks.append(a.leave_type or _("On Leave"))
	elif a.status == "Absent":
		row["code"] = "AB"
	else:
		missing = cint(a.custom_missing_punch)
		row["code"] = "MP" if missing else "HD" if a.status == "Half Day" else "WFH" if a.status == "Work From Home" else "PR"
		row["in_time"], row["out_time"] = clock(a.in_time), clock(a.out_time)
		if missing:
			remarks.append(_("Missing punch"))
		else:
			shift = get_shift(a.shift or e.default_shift) or frappe._dict()
			wk = to_minutes(a.working_hours)
			tot = to_minutes(a.custom_worked_hours or a.working_hours)
			holiday_work = cint(a.custom_is_holiday_work)
			base = 0 if holiday_work else to_minutes(required_hours(shift))
			minutes.update(
				_wk=wk, _tot=tot, _ot1=to_minutes(a.custom_ot1_hours), _ot2=to_minutes(a.custom_ot2_hours),
				_ut=cint(a.under_time_minutes), _reg=min(tot, base) if base else 0,
			)
			row["base"] = hm(base)
			if holiday_work:
				row["is_off"] = 1
				remarks.append(_("Holiday work") + (f" ({holiday})" if holiday else ""))
			if not cint(shift.get("custom_is_flexible_shift")) and shift.get("start_time") and shift.get("end_time"):
				row["in_excep"], row["out_excep"] = exceptions(a, day, shift)
		if a.status == "Half Day":
			remarks.append(_("Half day"))
	row.update({key[1:]: hm(value) for key, value in minutes.items()})
	row["remarks"] = ", ".join(r for r in remarks if r)
	return {**row, **minutes}


def exceptions(a, day, shift):
	"""In and Out against the shift's start and end: E 0.33 came 33 minutes early, L 0.03 left 3 minutes late."""
	start = datetime.datetime.combine(day, datetime.time()) + to_timedelta(shift.start_time)
	end = datetime.datetime.combine(day, datetime.time()) + to_timedelta(shift.end_time)
	if end <= start:
		end += datetime.timedelta(days=1)

	def excep(punch, ref):
		if not punch:
			return ""
		diff = round((get_datetime(punch) - ref).total_seconds() / 60)
		return "" if not diff else f"{'L' if diff > 0 else 'E'} {hm(abs(diff))}"

	return excep(a.in_time, start), excep(a.out_time, end)


def get_holidays(employees, start, end):
	"""employee -> {date: description} from each employee's holiday list(s) over the range."""
	years = [start] + [datetime.date(y, 1, 1) for y in range(start.year + 1, end.year + 1)]
	lists_of = {e.name: {holiday_list(e.name, as_on) for as_on in years} - {None, ""} for e in employees}
	lists = set().union(*lists_of.values())
	by_list = {}
	for h in frappe.get_all(
		"Holiday",
		filters={"parent": ("in", list(lists) or [""]), "holiday_date": ("between", [start, end])},
		fields=["parent", "holiday_date", "description", "weekly_off"],
	):
		text = frappe.utils.strip_html(h.description or "").strip()
		by_list.setdefault(h.parent, {})[getdate(h.holiday_date)] = text or (_("Weekly off") if h.weekly_off else _("Holiday"))
	out = {}
	for name, names in lists_of.items():
		for list_name in names:
			out.setdefault(name, {}).update(by_list.get(list_name, {}))
	return out


def holiday_list(employee, as_on):
	try:
		try:
			return get_holiday_list_for_employee(employee, raise_exception=False, as_on=as_on)
		except TypeError:  # v15: no as_on
			return get_holiday_list_for_employee(employee, raise_exception=False)
	except Exception:
		frappe.clear_last_message()
		return None


def leave_code(leave_type):
	if not leave_type:
		return "LV"
	if leave_type in LEAVE_CODES:
		return LEAVE_CODES[leave_type]
	share = re.search(r"(\d+)%", leave_type)
	if leave_type.startswith("Sick Leave") and share:
		return f"SL{share.group(1)}"
	return "".join(w[0] for w in re.findall(r"[A-Za-z]+", leave_type)).upper()[:4] or "LV"


def to_minutes(hours):
	return round(flt(hours) * 60)


def hm(minutes, blank="-"):
	"""Minutes as TAMS hours.minutes: 487 -> 8.07."""
	minutes = round(minutes or 0)
	return f"{minutes // 60}.{minutes % 60:02d}" if minutes else blank


def clock(value):
	return get_datetime(value).strftime("%-I:%M %p").lower() if value else ""


def get_columns(filters, many=True):
	def col(label, fieldname, fieldtype="Data", width=70, **kw):
		return {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **kw}

	columns = []
	if many:
		columns += [col("Emp. No", "emp_no", width=80), col("Employee Name", "employee_name", width=170)]
	def hours(label, fieldname, width=70):
		return col(label, fieldname, width=width, align="right")

	columns += [
		col("Sr", "sr", "Int", 50),
		col("Day", "day", width=55, align="left"),
		col("Date", "date", "Date", 95),
		col("Code", "code", width=60, align="left"),
		col("In Time", "in_time", width=85, align="left"),
		col("Out Time", "out_time", width=85, align="left"),
		hours("Wk Hrs", "wk"),
		hours("Tot Hrs", "tot"),
		hours("Base Hrs", "base"),
		hours("Reg Hrs", "reg"),
		hours("OT1", "ot1", 60),
		hours("OT2", "ot2", 60),
		hours("UT", "ut", 60),
		col("Remarks", "remarks", width=180, align="left"),
		col("In Excep", "in_excep", width=80, align="left"),
		col("Out Excep", "out_excep", width=80, align="left"),
		col("Employee", "employee", "Link", 110, options="Employee"),
	]
	return columns
