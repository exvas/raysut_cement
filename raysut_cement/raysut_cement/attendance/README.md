# Flexible Shift & Overtime

Switch: **Raysut Attendance Settings → Flexible Shift & Overtime** (on by default). Turned off,
Shift Types and Attendance behave as before.

## Shift Type settings (section "Flexible Shift & Overtime")

| Field | Meaning |
|---|---|
| Is Flexible Shift | No fixed start or end. The day's first punch is the IN, the last the OUT. |
| Day Start Time | When a new attendance day begins. A punch before it belongs to the previous date: with 05:00, a 02:30 punch on 11-Nov counts for 10-Nov. Required on a flexible shift. |
| Required Working Hours | Normal hours per day; more is overtime. Required on a flexible shift. On a fixed shift, blank means the start–end duration. |
| OT Min Hours | Overtime counts only when the extra hours reach this value. |
| OT Max Hours | Overtime per day is capped at this value (0 = no cap). |

On a flexible shift, Start/End Time are set from the Day Start (05:00 → 05:00 to 04:59) and the
check-in/check-out buffers are cleared; HR does not edit them. A shift can use either this or the
older Timetable Mode "Flexible", not both.

## How a flexible day is marked

- Shift for the day: the employee's Shift Assignment, else their Default Shift.
- The day's window is `[date + Day Start, next date + Day Start)`. Only windows that have ended are
  processed, so a day is marked once, with all its punches. Punches with "Skip Auto Attendance"
  (the imported TAMS history) are ignored, as are dates before the shift's Process Attendance After.
- Two or more punches: IN = first, OUT = last, worked hours = OUT − IN. Status is Present, or
  Absent / Half Day if the Shift Type's thresholds for those are set and not reached.
- One punch: Present with **Missing Punch** ticked, worked hours 0, no overtime. HR reviews these.
- No punches: nothing is created here; core auto attendance marks the day Absent, and never on a
  holiday.
- The punches are linked to the Attendance (Employee Checkin → Attendance).
- Submitted Attendance is left alone, unless "Re-process" is ticked: then it is cancelled and
  re-created (On Leave is always kept).

It runs every hour for the last 3 days, inside core auto attendance before its absent marking, and
from **Attendance list → Process Flexible Attendance** (date range, optional employee, Re-process).

## OT1 and OT2 (every Attendance, flexible or fixed)

Worked out on save and submit, from the Attendance's working hours and its shift:

- **Holiday** (the date is in the employee's Holiday List, else the company's: weekly offs such as
  Friday, and public holidays): Holiday Work ticked, **OT2 = all worked hours**, OT1 = 0. No min or
  max applies.
- **Working day**: `extra = worked − required`. OT1 = 0 if `extra < OT Min`; `OT Max` if
  `extra > OT Max` (and OT Max > 0); otherwise `extra`. OT2 = 0.
- Missing punch, Absent or On Leave: no overtime.
- Hours are rounded to 2 decimals.

Punches on a holiday now create Attendance (core HRMS would skip the day), so holiday work is paid.

## OT Policy

Link an **OT Policy** on the Shift Type (field "OT Policy") to replace OT Min / OT Max with:

| Setting | Effect |
|---|---|
| Minimum OT (Minutes) | Extra time below this is not overtime. |
| Round OT To / Rounding | 15, 30 or 60 minutes; Down, Nearest or Up. |
| Max OT1 per Day | Cap on OT1 (0 = none). |
| Move OT1 Beyond (Hours) to OT2 | OT1 above this many hours a day becomes OT2 (0 = off). |
| Holiday Work is OT2 | All hours on a weekly off or public holiday are OT2. Off: the day is treated like a normal day. |
| Max OT2 per Day | Cap on OT2 (0 = none). |
| OT1 / OT2 Rate | Multipliers for payroll; shown for export, not applied to the hours. |

After changing a policy, recalculate past days with `recalculate_overtime` (System Manager).

## Flexible Check-in (flexi grace period)

For a normal shift such as General 07:00–15:00 where staff may arrive up to 10:00 and then work
8 hours from their arrival. On the Shift Type, section **Flexible Check-in Settings**:

1. Tick **Enable Flexible Check-in**.
2. **Grace Period Ends At**: the last check-in that is not late (10:00). Must be after the shift
   start and before its end.
3. **Required Working Hours**: 8.
4. **Count Work From**: for a check-in before 07:00, count from the punch ("Actual Check-in") or
   only from 07:00 ("Shift Start Time").
5. **Action if Check-in After Grace**: Mark Late, Mark Half Day or Mark Absent.
6. **Under Time Tolerance**: a shortfall up to this many minutes is ignored.
7. Optional **OT Policy** (above) for the overtime.
8. Set **Allow check-out after shift end time** long enough for the latest arrival to finish: the
   form tells you the minimum (10:00 + 8 h − 15:00 = 180 minutes); more lets later overtime count.

Per day, from the first IN and last OUT that core auto attendance linked to the shift:

- Start = the check-in (or the shift start, per Count Work From). Expected checkout = start +
  required hours (crossing midnight is fine). Worked = last OUT − start, minus unpaid breaks.
- Check-in up to the grace time: not late. After it: late, Late (Minutes) = check-in − grace end,
  and the chosen action.
- Under time = required − worked, when that exceeds the tolerance.
- OT1 / OT2 from the extra hours, as above.
- No check-out: Missing Punch ticked, no worked hours, under time or overtime.

The Attendance shows Expected Checkout, Required Work Hours, Late (Minutes), Under Time (Minutes),
OT1, OT2 and "Flexible Check-in Applied". It works in the hourly run and with **Mark Attendance**
on the Shift Type; a day already marked is not marked twice. Shifts without the tick are unchanged.

## Reports (Crenya Attendance → Reports)

**Consolidated Attendance** — the Consolidated Monthly Attendance Report. Every day of the period
is counted once per employee:

| Column | Meaning |
|---|---|
| PR | Present (and Work From Home). Half Day = 0.5 PR + 0.5 of its leave type, else 0.5 AB. |
| AB | Absent |
| WO / HL | Weekly off / public holiday from the holiday list, with no attendance that day |
| NM | Not Marked: no attendance, leave or holiday (highlighted) |
| AL, SL, … | Leave days by type, using Leave Type → Report Abbreviation (blank: initials). Only types with a value are shown unless "Show zero leave columns" is ticked. LV = leave without a type. |
| Late Count, Late, Under Time, OT1, OT2, Total Worked Hr | Sums of the stored values, as HH:MM |
| Total Days / Days Not Employed | PR + AB + WO + HL + NM + leaves, and the days before joining or after relieving |

A row whose Total Days + Days Not Employed differs from the days in the period (for example two
attendances on one day) is shown in red. Filters: dates (this month), company, branch, department
(with its sub-departments), shift type, employee, employment type, status, group by (subtotals),
PDF paper size. A user limited to some branches or departments sees only those employees.

- Click an employee's name to open **Daily Attendance** for that employee and period.
- **Print / PDF**: A3 landscape (A4 via the Paper Size filter) with logo, filters, repeating
  column headings, legend, signature blocks and "Page X of Y".
- **Excel**: Menu → Export. Tick "Include hidden columns" for the decimal-hour columns payroll uses.
- **SAP Export** button: CSV of Employee ID, period, PR, AB, leave totals, OT1, OT2 and under
  time in decimal hours.

**Daily Attendance** — one row per attendance: check-in, check-out, expected checkout, worked,
late, under time, OT1, OT2 and flags (missing punch, holiday work).

**Under Time** — per employee: days with under time and the total, for a date range, branch and
department.
