# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Feature switches from Raysut Attendance Settings. A switch that was never saved counts as on."""

import frappe
from frappe.utils import cint

DOCTYPE = "Raysut Attendance Settings"
FEATURES = (
	"enable_crosschex",
	"enable_shift_scheduling",
	"enable_timetable_rules",
	"enable_checkin_summary",
	"enable_flexible_overtime",
)


def is_enabled(feature):
	# read the stored rows, not the doc: a loaded Single turns unsaved Check fields into 0
	value = frappe.db.get_singles_dict(DOCTYPE).get(feature)
	return True if value is None else bool(cint(value))


def boot_session(bootinfo):
	bootinfo.raysut_features = {feature: is_enabled(feature) for feature in FEATURES}
	hide_blocked_apps(bootinfo)


def get_hidden_apps(user=None):
	"""Apps whose every module the user's Module Profile blocks.

	ERPNext's own has_permission lets in every desk user, so blocking its modules is how an
	HR-only user is kept off its desktop tile and rail.
	"""
	blocked = set(frappe.get_cached_doc("User", user or frappe.session.user).get_blocked_modules())
	if not blocked:
		return set()

	hidden = set()
	for app in frappe.get_installed_apps():
		modules = set(frappe.get_all("Module Def", {"app_name": app}, pluck="name"))
		if app != "frappe" and modules and modules <= blocked:
			hidden.add(app)
	return hidden


def hide_blocked_apps(bootinfo):
	# v16 builds the desktop tiles and the rail from bootinfo.app_data; v15 has no such key
	hidden = get_hidden_apps()
	for app in bootinfo.get("app_data") or []:
		if app.get("app_name") in hidden:
			app.update(on_apps_screen=False, app_route="", desk_route="", dock=[])


@frappe.whitelist()
def get_apps():
	"""frappe.apps.get_apps without the apps get_hidden_apps keeps off the desk."""
	from frappe.apps import get_apps as core_get_apps

	hidden = get_hidden_apps()
	return [app for app in core_get_apps() if app.get("name") not in hidden]


def has_app_permission():
	"""Show the Raysut Cement app icon to HR and system managers only."""
	return bool({"System Manager", "HR Manager", "HR User"} & set(frappe.get_roles()))
