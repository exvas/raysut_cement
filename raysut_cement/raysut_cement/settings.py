# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Feature switches from Raysut Attendance Settings. A switch that was never saved counts as on."""

import frappe
from frappe.utils import cint

DOCTYPE = "Raysut Attendance Settings"
FEATURES = ("enable_crosschex", "enable_shift_scheduling", "enable_timetable_rules", "enable_checkin_summary")


def is_enabled(feature):
	# read the stored rows, not the doc: a loaded Single turns unsaved Check fields into 0
	value = frappe.db.get_singles_dict(DOCTYPE).get(feature)
	return True if value is None else bool(cint(value))


def boot_session(bootinfo):
	bootinfo.raysut_features = {feature: is_enabled(feature) for feature in FEATURES}
