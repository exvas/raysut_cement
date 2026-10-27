# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Safety net: re-read recent CrossChex punches and import any that never reached ERPNext."""

from datetime import datetime, timedelta, timezone

import frappe

from raysut_cement.raysut_cement.crosschex_cloud.api.attendance import create_attendance_log
from raysut_cement.raysut_cement.crosschex_cloud.client import fetch_records
from raysut_cement.raysut_cement.settings import is_enabled


def reconcile_missing_checkins(days_back=2, dry_run=False):
	if not is_enabled("enable_crosschex"):
		return {"skipped": True, "reason": "CrossChex disabled in Raysut Attendance Settings"}
	settings = frappe.get_single("Crosschex Settings")
	if not settings.enable_realtime_sync:
		return {"skipped": True, "reason": "Sync disabled"}

	end_utc = datetime.now(timezone.utc)
	begin_utc = end_utc - timedelta(days=int(days_back))
	results = {"devices_checked": 0, "records_fetched": 0, "missing": 0, "imported": 0, "errors": []}

	for config in settings.api_configurations:
		try:
			records = fetch_records(config, begin_utc, end_utc)
			missing = _missing_records(records)
			results["devices_checked"] += 1
			results["records_fetched"] += len(records)
			results["missing"] += len(missing)
			if missing and not dry_run:
				_processed, created, _errors = create_attendance_log(missing)
				results["imported"] += created
		except Exception as e:
			results["errors"].append(f"{config.configuration_name}: {e}")
			frappe.log_error(title="CrossChex Reconciliation Error", message=f"{config.configuration_name}: {e}")

	return results


def _missing_records(records):
	by_uuid = {r.get("uuid"): r for r in records if r.get("uuid")}
	if not by_uuid:
		return []
	existing = set(
		frappe.get_all(
			"Employee Checkin",
			filters={"custom_crosschex_uuid": ("in", list(by_uuid))},
			pluck="custom_crosschex_uuid",
		)
	)
	return [r for uuid, r in by_uuid.items() if uuid not in existing]


def scheduled_reconciliation_job():
	results = reconcile_missing_checkins(days_back=2)
	if results.get("imported"):
		frappe.get_doc(
			{
				"doctype": "CrossChex Log",
				"log_type": "Reconciliation",
				"status": "Success" if not results["errors"] else "Partial Success",
				"processing_status": "Completed",
				"records_processed": results["missing"],
				"checkins_created": results["imported"],
				"error_message": "\n".join(results["errors"]) or None,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
