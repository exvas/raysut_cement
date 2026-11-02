# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Data for the Raysut Dashboard page: one day at a glance, plus the month so far."""

from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, getdate, nowdate

from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import get_employees

PRESENT = ("Present", "Work From Home")
TREND_DAYS = 14
OT_MONTHS = 6


@frappe.whitelist()
def get_dashboard(date=None, company=None):
	company = company or frappe.defaults.get_user_default("Company") or frappe.get_all("Company", pluck="name", limit=1)[0]
	employees = {e.name: e for e in get_employees(frappe._dict(company=company, status="Active"))}
	names = list(employees) or [""]

	requested = getdate(date or nowdate())
	day = requested
	if not frappe.db.exists("Attendance", {"attendance_date": day, "docstatus": 1, "company": company}):
		# nothing marked yet (attendance is created once the day is over): show the latest marked day
		latest = frappe.get_all(
			"Attendance",
			filters={"attendance_date": ("<=", day), "docstatus": 1, "company": company},
			pluck="attendance_date",
			order_by="attendance_date desc",
			limit=1,
		)
		day = getdate(latest[0]) if latest else day

	today = attendance_on(day, names)
	month_start = get_first_day(day)
	month = frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [month_start, day])},
		fields=["employee", "status", "working_hours", "custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours",
				"under_time_minutes", "late_entry", "custom_missing_punch"],
	)

	return {
		"company": company,
		"companies": frappe.get_list("Company", pluck="name", order_by="name"),
		"requested_date": requested,
		"date": day,
		"is_holiday": is_company_holiday(company, day),
		"kpi": day_kpis(employees, today),
		"month": month_kpis(month),
		"locations": breakdown(employees, today, "branch"),
		"departments": breakdown(employees, today, "department")[:12],
		"trend": trend(names, day),
		"ot_by_month": ot_by_month(names, day),
		"top_overtime": top_overtime(employees, month),
		"exceptions": exceptions(employees, today),
		"punches": punches_on(day, names),
	}


def day_status(r):
	"""How the dashboard counts a day: a worked day with one punch is a missing punch, not present, until it is fixed."""
	if not r:
		return "not_marked"
	if r.custom_missing_punch and r.status in (*PRESENT, "Half Day"):
		return "missing_punch"
	return {"Absent": "absent", "On Leave": "on_leave", "Half Day": "half_day"}.get(r.status, "present" if r.status in PRESENT else None)


DRILL_DOWN = {
	"active": lambda r: True,
	"present": lambda r: day_status(r) == "present",
	"absent": lambda r: day_status(r) == "absent",
	"on_leave": lambda r: day_status(r) == "on_leave",
	"half_day": lambda r: day_status(r) == "half_day",
	"not_marked": lambda r: not r,
	"late": lambda r: r and r.late_entry,
	"missing_punch": lambda r: day_status(r) == "missing_punch",
	"holiday_work": lambda r: r and r.custom_is_holiday_work,
}


@frappe.whitelist()
def get_kpi_employees(date, company, kpi, location=None):
	"""The employees behind one of the day's figures (a KPI card or a location cell), same counting as the cards."""
	if kpi not in DRILL_DOWN:
		frappe.throw(_("Unknown figure {0}").format(kpi))
	employees = {e.name: e for e in get_employees(frappe._dict(company=company, status="Active"))}
	if location:
		employees = {n: e for n, e in employees.items() if (e.branch or _("Not Set")) == location}
	day = getdate(date)
	by_employee = {r.employee: r for r in attendance_on(day, list(employees) or [""])}
	out = []
	for name, e in employees.items():
		r = by_employee.get(name)
		if not DRILL_DOWN[kpi](r):
			continue
		out.append(
			{"employee": name, "employee_name": e.employee_name, "department": e.department, "designation": e.designation,
			 "attendance": r.name if r else None,
			 "status": (_("Missing Punch") if day_status(r) == "missing_punch" else r.status) if r else _("Not Marked"),
			 "leave_type": r.leave_type if r else None, "in_time": r.in_time if r else None,
			 "out_time": r.out_time if r else None, "working_hours": flt(r.working_hours, 2) if r else 0,
			 "late_minutes": cint(r.late_minutes) if r else 0, "missing_punch": cint(r.custom_missing_punch) if r else 0}
		)
	return sorted(out, key=lambda x: ((x["department"] or "~"), x["employee_name"] or ""))


def punches_on(day, names):
	"""The day's punches of the employees shown; the last one tells whether the day's data is complete."""
	filters = {"time": ("between", [day, f"{day} 23:59:59"]), "employee": ("in", names)}
	last = frappe.get_all("Employee Checkin", filters=filters, pluck="time", order_by="time desc", limit=1)
	return {"on_day": frappe.db.count("Employee Checkin", filters), "last": last[0] if last else None, "last_sync": last_device_sync()}


def last_device_sync():
	value = frappe.db.get_single_value("Crosschex Settings", "last_sync_time")
	return value if value and getdate(value).year > 2000 else None  # never synced reads back as 0001-01-01


def attendance_on(day, names):
	return frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "attendance_date": day, "employee": ("in", names)},
		fields=["name", "employee", "status", "leave_type", "late_entry", "late_minutes", "custom_missing_punch",
				"custom_is_holiday_work", "in_time", "out_time", "working_hours", "shift"],
	)


def is_company_holiday(company, day):
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	return bool(holiday_list and frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": day}))


def day_kpis(employees, rows):
	status = Counter(day_status(r) for r in rows)
	marked = {r.employee for r in rows}
	return {
		"active": len(employees),
		"present": status["present"],
		"missing_punch": status["missing_punch"],
		"half_day": status["half_day"],
		"absent": status["absent"],
		"on_leave": status["on_leave"],
		"not_marked": len(set(employees) - marked),
		"late": sum(1 for r in rows if r.late_entry),
		"holiday_work": sum(1 for r in rows if r.custom_is_holiday_work),
	}


def month_kpis(rows):
	worked = sum(
		flt(r.custom_worked_hours) or (flt(r.working_hours) if r.status in (*PRESENT, "Half Day") else 0) for r in rows
	)
	return {
		"worked_hours": round(worked, 1),
		"ot1_hours": round(sum(flt(r.custom_ot1_hours) for r in rows), 1),
		"ot2_hours": round(sum(flt(r.custom_ot2_hours) for r in rows), 1),
		"under_time_hours": round(sum(cint(r.under_time_minutes) for r in rows) / 60, 1),
		"late_days": sum(1 for r in rows if r.late_entry),
		"missing_punch_days": sum(1 for r in rows if r.custom_missing_punch),
	}


def breakdown(employees, rows, field):
	"""Headcount and the day's statuses per branch (location) or department."""
	by_employee = {r.employee: r for r in rows}
	groups = defaultdict(Counter)
	for name, e in employees.items():
		group = groups[e.get(field) or _("Not Set")]
		group["headcount"] += 1
		group[day_status(by_employee.get(name)) or "not_marked"] += 1
	out = []
	for name, c in groups.items():
		row = {"name": name, **{k: c[k] for k in ("headcount", "present", "missing_punch", "absent", "on_leave", "half_day", "not_marked")}}
		row["present_pct"] = round(100 * (c["present"] + 0.5 * c["half_day"]) / c["headcount"]) if c["headcount"] else 0
		out.append(row)
	return sorted(out, key=lambda r: -r["headcount"])


def trend(names, day):
	start = add_days(day, -(TREND_DAYS - 1))
	counts = defaultdict(Counter)
	for r in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, day])},
		fields=["attendance_date", "status", "custom_missing_punch"],
	):
		counts[r.attendance_date][day_status(r)] += 1
	dates = [getdate(add_days(start, i)) for i in range(TREND_DAYS)]
	return {
		"labels": [d.strftime("%d %b") for d in dates],
		"present": [counts[d]["present"] for d in dates],
		"missing_punch": [counts[d]["missing_punch"] for d in dates],
		"absent": [counts[d]["absent"] for d in dates],
		"on_leave": [counts[d]["on_leave"] for d in dates],
	}


def ot_by_month(names, day):
	start = get_first_day(add_months(day, -(OT_MONTHS - 1)))
	totals = defaultdict(lambda: [0.0, 0.0])
	for r in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, day]),
				 "custom_worked_hours": (">", 0)},
		fields=["attendance_date", "custom_ot1_hours", "custom_ot2_hours"],
	):
		key = r.attendance_date.strftime("%Y-%m")
		totals[key][0] += flt(r.custom_ot1_hours)
		totals[key][1] += flt(r.custom_ot2_hours)
	months = [getdate(add_months(start, i)) for i in range(OT_MONTHS)]
	return {
		"labels": [m.strftime("%b %Y") for m in months],
		"ot1": [round(totals[m.strftime("%Y-%m")][0]) for m in months],
		"ot2": [round(totals[m.strftime("%Y-%m")][1]) for m in months],
	}


def top_overtime(employees, rows, limit=10):
	totals = defaultdict(lambda: [0.0, 0.0])
	for r in rows:
		totals[r.employee][0] += flt(r.custom_ot1_hours)
		totals[r.employee][1] += flt(r.custom_ot2_hours)
	ranked = sorted(totals.items(), key=lambda item: -(item[1][0] + item[1][1]))[:limit]
	return [
		{"employee": name, "employee_name": employees[name].employee_name, "department": employees[name].department,
		 "ot1": round(ot1, 1), "ot2": round(ot2, 1)}
		for name, (ot1, ot2) in ranked if ot1 + ot2 > 0
	]


def exceptions(employees, rows, limit=15):
	"""The day's late arrivals and missing punches, for follow-up."""
	out = []
	for r in rows:
		if r.custom_missing_punch or r.late_entry:
			e = employees[r.employee]
			out.append(
				{"employee": r.employee, "employee_name": e.employee_name, "department": e.department,
				 "issue": _("Missing Punch") if r.custom_missing_punch else _("Late {0} min").format(cint(r.late_minutes)),
				 "in_time": r.in_time}
			)
	return sorted(out, key=lambda x: x["issue"])[:limit]
