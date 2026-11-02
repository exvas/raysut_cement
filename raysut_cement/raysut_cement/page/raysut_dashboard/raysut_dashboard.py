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
		"punches": {
			"on_day": frappe.db.count("Employee Checkin", {"time": ("between", [day, f"{day} 23:59:59"])}),
			"last_sync": last_device_sync(),
		},
	}


def last_device_sync():
	value = frappe.db.get_single_value("Crosschex Settings", "last_sync_time")
	return value if value and getdate(value).year > 2000 else None  # never synced reads back as 0001-01-01


def attendance_on(day, names):
	return frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "attendance_date": day, "employee": ("in", names)},
		fields=["employee", "status", "leave_type", "late_entry", "late_minutes", "custom_missing_punch",
				"custom_is_holiday_work", "in_time", "working_hours", "shift"],
	)


def is_company_holiday(company, day):
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	return bool(holiday_list and frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": day}))


def day_kpis(employees, rows):
	status = Counter(r.status for r in rows)
	marked = {r.employee for r in rows}
	return {
		"active": len(employees),
		"present": sum(status[s] for s in PRESENT),
		"half_day": status["Half Day"],
		"absent": status["Absent"],
		"on_leave": status["On Leave"],
		"not_marked": len(set(employees) - marked),
		"late": sum(1 for r in rows if r.late_entry),
		"missing_punch": sum(1 for r in rows if r.custom_missing_punch),
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
	by_employee = {r.employee: r.status for r in rows}
	groups = defaultdict(Counter)
	for name, e in employees.items():
		group = groups[e.get(field) or _("Not Set")]
		group["headcount"] += 1
		status = by_employee.get(name)
		group[
			"present" if status in PRESENT else
			"absent" if status == "Absent" else
			"on_leave" if status == "On Leave" else
			"half_day" if status == "Half Day" else
			"not_marked"
		] += 1
	out = []
	for name, c in groups.items():
		row = {"name": name, **{k: c[k] for k in ("headcount", "present", "absent", "on_leave", "half_day", "not_marked")}}
		row["present_pct"] = round(100 * (c["present"] + 0.5 * c["half_day"]) / c["headcount"]) if c["headcount"] else 0
		out.append(row)
	return sorted(out, key=lambda r: -r["headcount"])


def trend(names, day):
	start = add_days(day, -(TREND_DAYS - 1))
	counts = defaultdict(Counter)
	for r in frappe.get_all(
		"Attendance",
		filters={"docstatus": 1, "employee": ("in", names), "attendance_date": ("between", [start, day])},
		fields=["attendance_date", "status"],
	):
		counts[r.attendance_date][r.status] += 1
	dates = [getdate(add_days(start, i)) for i in range(TREND_DAYS)]
	return {
		"labels": [d.strftime("%d %b") for d in dates],
		"present": [sum(counts[d][s] for s in PRESENT) for d in dates],
		"absent": [counts[d]["Absent"] for d in dates],
		"on_leave": [counts[d]["On Leave"] for d in dates],
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
