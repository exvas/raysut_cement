# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta, timezone

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, get_datetime, now_datetime

from raysut_cement.raysut_cement.crosschex_cloud.api.attendance import create_attendance_log
from raysut_cement.raysut_cement.crosschex_cloud.client import fetch_records, get_token, system_to_utc
from raysut_cement.raysut_cement.settings import is_enabled

MANAGER_ROLES = ("System Manager", "HR Manager")


class CrosschexSettings(Document):
	def validate(self):
		for idx, config in enumerate(self.api_configurations, start=1):
			if config.api_url and not config.api_url.endswith("/"):
				config.api_url += "/"
			if self.enable_realtime_sync:
				if not config.api_url:
					frappe.throw(f"API URL is required for configuration row {idx}")
				if not config.api_key:
					frappe.throw(f"API Key is required for configuration row {idx}")
				if not config.api_secret:
					frappe.throw(f"API Secret is required for configuration row {idx}")

		if self.enable_realtime_sync and not self.api_configurations:
			frappe.throw("Please add at least one API Configuration before enabling sync")


def _get_config(config_row_name):
	settings = frappe.get_single("Crosschex Settings")
	for config in settings.api_configurations:
		if config.name == config_row_name:
			return config
	frappe.throw("Save Crosschex Settings before testing or syncing this row")


@frappe.whitelist()
def test_individual_api_config(config_row_name, **kwargs):
	"""Fetch a fresh token for one configuration row and store it."""
	frappe.only_for(MANAGER_ROLES)
	config = _get_config(config_row_name)
	try:
		get_token(config, force=True)
	except Exception as e:
		frappe.db.commit()
		return {"success": False, "error": str(e)}
	frappe.db.commit()
	return {
		"success": True,
		"expires": config.token_expires,
		"message": f"Connection to {config.configuration_name or config.api_url} successful!",
	}


@frappe.whitelist()
def get_crosschex_status():
	settings = frappe.get_single("Crosschex Settings")
	return {
		"sync_enabled": settings.enable_realtime_sync,
		"last_sync": settings.last_sync_time,
		"last_status": settings.last_sync_status,
		"connection_status": settings.connection_status,
		"device_count": len(settings.api_configurations),
	}


@frappe.whitelist()
def sync_individual_device(config_row_name, **kwargs):
	frappe.only_for(MANAGER_ROLES)
	if not is_enabled("enable_crosschex"):
		frappe.throw(_("CrossChex Cloud Integration is disabled in Raysut Attendance Settings"))
	return _sync_config(_get_config(config_row_name), frappe.get_single("Crosschex Settings"))


def _sync_config(config, settings):
	"""Pull punches for one configuration row.

	Every run re-reads from midnight of the last sync day; duplicates are skipped by
	UUID. This catches punches that offline devices upload hours later.
	"""
	try:
		now = now_datetime()
		if config.last_sync_time:
			begin_local = datetime.combine(get_datetime(config.last_sync_time).date(), datetime.min.time())
		else:
			begin_local = now - timedelta(hours=int(settings.sync_hours_back or 24))

		records = fetch_records(config, system_to_utc(begin_local), datetime.now(timezone.utc))
		processed, created, errors = create_attendance_log(records)
		status = f"{processed} records read, {created} check-ins created, {errors} errors"
		config.db_set({"last_sync_time": now, "last_sync_status": status}, update_modified=False)
		frappe.db.commit()
		return {"success": True, "processed": processed, "created": created, "errors": errors, "message": status}
	except Exception as e:
		config.db_set("last_sync_status", f"Error: {e}"[:140], update_modified=False)
		frappe.db.commit()
		frappe.log_error(title=f"CrossChex Sync Error - {config.configuration_name}")
		return {"success": False, "error": str(e)}


def scheduled_attendance_sync():
	"""Runs every minute; only syncs once sync_frequency minutes have passed since the last run."""
	if not is_enabled("enable_crosschex"):
		return
	settings = frappe.get_single("Crosschex Settings")
	if not settings.enable_realtime_sync or not settings.api_configurations:
		return

	if settings.last_sync_time:
		elapsed = (now_datetime() - get_datetime(settings.last_sync_time)).total_seconds()
		if elapsed < flt(settings.sync_frequency or 15) * 60:
			return

	summary = []
	for config in settings.api_configurations:
		result = _sync_config(config, settings)
		summary.append(
			f"{config.configuration_name}: {result['processed']} records"
			if result["success"]
			else f"{config.configuration_name}: Error - {result['error']}"
		)

	any_connected = any(
		frappe.db.get_value("CrossChex API Configuration", c.name, "connection_status") == "Connected"
		for c in settings.api_configurations
	)
	settings.db_set(
		{
			"last_sync_time": now_datetime(),
			"last_sync_status": ("Auto-sync: " + "; ".join(summary))[:140],
			"connection_status": "Connected" if any_connected else "Disconnected",
		},
		update_modified=False,
	)
	frappe.db.commit()


def check_and_refresh_token():
	"""Hourly: renew tokens that are missing or expire within the next 30 minutes."""
	if not is_enabled("enable_crosschex"):
		return
	settings = frappe.get_single("Crosschex Settings")
	if not settings.enable_realtime_sync:
		return
	for config in settings.api_configurations:
		try:
			get_token(config)
		except Exception:
			frappe.log_error(title=f"CrossChex token refresh failed - {config.configuration_name}")
	frappe.db.commit()


def purge_old_logs():
	"""Daily: delete CrossChex Log entries older than log_retention_days."""
	days = frappe.db.get_single_value("Crosschex Settings", "log_retention_days") or 30
	frappe.db.delete("CrossChex Log", {"creation": ("<", add_days(now_datetime(), -int(days)))})
	frappe.db.commit()
