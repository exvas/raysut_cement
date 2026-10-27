# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Thin client for the CrossChex Cloud API (token + attendance records)."""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
import requests
from dateutil import parser
from frappe.utils import get_datetime, get_system_timezone, now_datetime

TIMEOUT = 60
PER_PAGE = 1000
MAX_PAGES = 20
TOKEN_REFRESH_MARGIN = timedelta(minutes=30)


class CrossChexError(Exception):
	pass


def utc_str(dt):
	return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def to_system_time(value):
	"""Parse an ISO 8601 timestamp and return a naive datetime in the site time zone."""
	dt = parser.isoparse(value) if isinstance(value, str) else value
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def system_to_utc(dt):
	"""Naive site-time datetime -> aware UTC datetime."""
	return dt.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(timezone.utc)


def _post(api_url, namespace, action, payload, token=None):
	body = {
		"header": {
			"nameSpace": namespace,
			"nameAction": action,
			"version": "1.0",
			"requestId": str(uuid.uuid4()),
			"timestamp": utc_str(datetime.now(timezone.utc)),
		},
		"payload": payload,
	}
	if token:
		body["authorize"] = {"type": "token", "token": token}

	url = api_url if api_url.endswith("/") else api_url + "/"
	response = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
	if response.status_code != 200:
		raise CrossChexError(f"CrossChex API returned HTTP {response.status_code}: {response.text[:300]}")

	data = response.json()
	if data.get("header", {}).get("nameSpace") == "System":
		error = data.get("payload", {})
		raise CrossChexError(f"{error.get('type', 'Unknown')}: {error.get('message', 'Unknown error')}")
	return data.get("payload", {})


def request_token(api_url, api_key, api_secret):
	payload = _post(api_url, "authorize.token", "token", {"api_key": api_key, "api_secret": api_secret})
	if not payload.get("token"):
		raise CrossChexError("CrossChex did not return a token")
	expires = to_system_time(payload["expires"]) if payload.get("expires") else None
	return payload["token"], expires


def get_token(config, force=False):
	"""Return a valid token for a CrossChex API Configuration row, refreshing and saving it if needed."""
	token = config.get_password("token", raise_exception=False)
	if not force and token and config.token_expires:
		if get_datetime(config.token_expires) - now_datetime() > TOKEN_REFRESH_MARGIN:
			return token

	api_secret = config.get_password("api_secret", raise_exception=False)
	if not (config.api_url and config.api_key and api_secret):
		raise CrossChexError("API URL, API Key and API Secret are required")

	try:
		token, expires = request_token(config.api_url, config.api_key, api_secret)
	except Exception:
		config.db_set("connection_status", "Error", update_modified=False)
		raise

	config.db_set(
		{
			"token": token,
			"token_expires": expires,
			"last_token_generated": now_datetime(),
			"connection_status": "Connected",
		},
		update_modified=False,
	)
	return token


def fetch_records(config, begin_utc, end_utc):
	"""Fetch all attendance records between two aware UTC datetimes, following pagination."""
	token = get_token(config)
	records, page = [], 1
	while page <= MAX_PAGES:
		payload = _post(
			config.api_url,
			"attendance.record",
			"getrecord",
			{
				"begin_time": utc_str(begin_utc),
				"end_time": utc_str(end_utc),
				"order": "asc",
				"page": page,
				"per_page": PER_PAGE,
			},
			token=token,
		)
		batch = payload.get("list") or []
		records.extend(batch)
		total = payload.get("total")
		if len(batch) < PER_PAGE or (total is not None and len(records) >= int(total)):
			return records
		page += 1

	frappe.log_error(
		title="CrossChex Sync - page limit reached",
		message=f"{config.configuration_name}: stopped after {MAX_PAGES} pages ({len(records)} records)",
	)
	return records
