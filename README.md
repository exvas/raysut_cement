### Raysut Cement

Attendance for Raysut Cement on ERPNext v15 / Frappe HRMS v15:

- **CrossChex Cloud integration** – punches from ANVIZ devices become `Employee Checkin` records (scheduled pull, optional webhook, reconciliation).
- **HikCentral-style scheduling** – Break Timetable → Timetable (`Shift Type`, Normal or Flexible) → Shift (`Shift Pattern`) → Schedule (`Shift Pattern Assignment`), which generates standard `Shift Assignment` records.
- **Flexible attendance** – minimum work time, latest check-in and break deduction, built on core HRMS auto attendance.

No core ERPNext/HRMS files are changed; everything is custom fields, new DocTypes, hooks and a `Shift Type` class override.

### Installation

Requires `erpnext` and `hrms`.

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site <site> install-app raysut_cement
bench --site <site> migrate
```

The scheduler must be enabled (`bench --site <site> enable-scheduler`).

### CrossChex Cloud (ANVIZ devices)

1. Set **Attendance Device ID** on every Employee to the employee's CrossChex number (`workno`). Leading zeros are ignored.
2. Open **Crosschex Settings**, add one row per CrossChex account (API URL, API Key, API Secret), save, then use **Test Connection** on the row.
3. Tick **Enable Realtime Sync** and choose the sync frequency. Punches are pulled every few minutes, re-checked every 4 hours, and logged in **CrossChex Log**.
4. Optional push mode: tick **Enable Webhook**, set a **Webhook Token**, and point CrossChex Cloud to
   `https://<site>/api/method/raysut_cement.raysut_cement.crosschex_cloud.api.attendance.make_attendace?token=<token>`.

Punches are stored in site time and are **not** marked `skip_auto_attendance`, so Shift Type auto attendance processes them. For ANVIZ devices use *Determine Check-in and Check-out = Alternating entries as IN and OUT during the same shift*.

### Scheduling (workspace "Crenya Attendance")

| HikCentral | ERPNext |
|---|---|
| Break Timetable | Break Timetable |
| Timetable | Shift Type + "Timetable Mode" (Normal / Flexible), colour and Break Period tab |
| Shift | Shift Pattern (Week / Day / Month cycle, drawn in the shift grid) |
| Schedule | Shift Pattern Assignment (Employee / Department / Branch / Designation / Employee Group) |

- Days without a timetable are rest days: no Shift Assignment is created, so no Absent is marked. Clear **Default Shift** on scheduled employees, otherwise HRMS falls back to it on rest days.
- A daily job extends every active schedule up to *Generate Days Ahead*, adds new joiners and stops at relieving dates.
- Editing a Shift Pattern regenerates future shifts (after today). Past shifts and manual Shift Assignments are never changed.
- Two timetables on one day need **HR Settings → Allow Multiple Shift Assignments for Same Date**.
- Reports: **Shift Roster** (schedule overview) and **Flexible Shift Work Hours**.

#### Sample setup

1. **Timetable "Example-Flexible"** – Timetable Mode *Flexible*, Valid Period 09:00 → 18:00 (Current Day), minimum 9 h 0 min, Enable Latest Check-in = *Next Day 23:59:59*, Enable Auto Attendance, Process Attendance After = go-live date, Automatically update Last Sync of Checkin.
2. **Timetable "Example-Normal"** – Timetable Mode *Normal*, 07:00 → 15:00 with the usual grace periods.
3. **Shift "flexible"** – Repeat By *Week*, every 1 week. Add *Example-Flexible* to the palette, select it and drag across Sunday–Thursday, then click Saturday. Friday stays empty (rest day).
4. **Schedule** – Shift Pattern Assignment for the department, Shift = *flexible*, Start Date = first day of the cycle, submit. Check the result in **Shift Roster**.

### Tests

```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app raysut_cement
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/raysut_cement
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
