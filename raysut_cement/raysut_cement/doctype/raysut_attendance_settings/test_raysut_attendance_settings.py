# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from raysut_cement.raysut_cement.crosschex_cloud import reconciliation
from raysut_cement.raysut_cement.crosschex_cloud.api import attendance
from raysut_cement.raysut_cement.doctype.crosschex_settings import crosschex_settings
from raysut_cement.raysut_cement.scheduling import generator
from raysut_cement.raysut_cement.scheduling.test_scheduling import PAST_DAY, SchedulingTestCase
from raysut_cement.raysut_cement.settings import DOCTYPE, FEATURES, boot_session, get_apps, is_enabled


class TestRaysutAttendanceSettings(SchedulingTestCase):
	def switch(self, feature, value, doctype=DOCTYPE):
		frappe.db.set_single_value(doctype, feature, value)
		frappe.clear_document_cache(doctype, doctype)
		self.addCleanup(frappe.clear_document_cache, doctype, doctype)

	def test_unsaved_switches_count_as_on(self):
		frappe.db.delete("Singles", {"doctype": DOCTYPE})
		frappe.clear_document_cache(DOCTYPE, DOCTYPE)
		self.addCleanup(frappe.clear_document_cache, DOCTYPE, DOCTYPE)
		self.assertTrue(all(is_enabled(f) for f in FEATURES))

		self.switch("enable_checkin_summary", 0)
		bootinfo = frappe._dict()
		boot_session(bootinfo)
		self.assertFalse(bootinfo.raysut_features["enable_checkin_summary"])
		self.assertTrue(bootinfo.raysut_features["enable_crosschex"])

	def test_crosschex_off_stops_sync_reconciliation_and_webhook(self):
		self.switch("enable_crosschex", 0)
		with patch.object(frappe, "get_single") as get_single:
			crosschex_settings.scheduled_attendance_sync()
			crosschex_settings.check_and_refresh_token()
			get_single.assert_not_called()
		self.assertTrue(reconciliation.reconcile_missing_checkins()["skipped"])
		self.assertRaises(frappe.ValidationError, crosschex_settings.sync_individual_device, "any-row")

		self.switch("enable_webhook", 1, doctype="Crosschex Settings")
		self.assertRaises(frappe.PermissionError, attendance.make_attendace, records=[])

	def test_scheduling_off_blocks_schedules_and_jobs(self):
		shift = self.timetable("Day", "08:00:00", "16:00:00")
		pattern = self.pattern("Week", 1, [(0, "Monday", shift.name)])
		self.employee()
		active = self.schedule(pattern.name, PAST_DAY)

		self.switch("enable_shift_scheduling", 0)
		self.assertRaises(frappe.ValidationError, self.schedule, pattern.name, PAST_DAY)
		with patch.object(generator, "generate") as generate:
			generator.daily_generation()
			generate.assert_not_called()
		with patch.object(frappe, "enqueue") as enqueue:
			pattern.days[0].day_key = "Tuesday"
			pattern.save()
			enqueue.assert_not_called()
		from raysut_cement.raysut_cement.doctype.shift_pattern_assignment.shift_pattern_assignment import regenerate_now

		self.assertRaises(frappe.ValidationError, regenerate_now, active.name)

	def test_timetable_rules_off_uses_core_attendance(self):
		lunch = self.break_timetable(break_type="Fixed", break_start="13:00:00", break_end="14:00:00")
		shift = self.timetable("NormalBreak", "09:00:00", "17:00:00", working_hours_threshold_for_half_day=7.5,
			timetable_breaks=[{"break_timetable": lunch.name}])
		flex = self.flexible("Flex9", "09:00:00", "18:00:00", 9)

		self.switch("enable_timetable_rules", 0)
		att = self.run_flexible_day(shift, ["09:00", "17:00"])
		self.assertEqual((att.working_hours, att.status), (8.0, "Present"))
		self.assertFalse(att.break_deducted_minutes)
		flexible = self.run_flexible_day(flex, ["09:05", "18:00"])
		self.assertEqual(flexible.status, "Present")
		self.assertIsNone(flexible.flexible_remarks)

	def test_app_with_every_module_blocked_is_hidden(self):
		erpnext_modules = frappe.get_all("Module Def", {"app_name": "erpnext"}, pluck="name")
		user = frappe.get_cached_doc("User", frappe.session.user)
		apps = [frappe._dict(app_name=a, on_apps_screen=True, dock=[{"x": 1}]) for a in ("erpnext", "hrms")]

		with patch.object(type(user), "get_blocked_modules", return_value=erpnext_modules[1:]):
			boot_session(bootinfo := frappe._dict(app_data=apps))
			self.assertTrue(bootinfo.app_data[0].on_apps_screen)

		with (
			patch.object(type(user), "get_blocked_modules", return_value=erpnext_modules),
			patch("frappe.apps.get_apps", return_value=[{"name": "erpnext"}, {"name": "hrms"}]),
		):
			boot_session(bootinfo := frappe._dict(app_data=apps))
			erpnext, hrms = bootinfo.app_data
			self.assertEqual((erpnext.on_apps_screen, erpnext.dock), (False, []))
			self.assertTrue(hrms.on_apps_screen)
			self.assertEqual(get_apps(), [{"name": "hrms"}])
