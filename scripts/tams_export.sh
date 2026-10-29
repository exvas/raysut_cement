#!/usr/bin/env bash
# Export a TAMS backup (.bak, SQL Server) into the files raysut_cement's tams_import reads.
#
#   MSSQL_SA_PASSWORD=... scripts/tams_export.sh /path/to/tams.bak OUT_DIR [FROM_DATE] [TO_DATE]
#
# Restores the backup into a throwaway SQL Server container (tams-mssql), then writes
# employees.tsv (active employees), checkins.tsv and timesheet.tsv for FROM_DATE..TO_DATE.
# Remove the container afterwards with `docker rm -f tams-mssql`.
set -euo pipefail

BAK=$1 OUT=$2 FROM=${3:-2026-01-01} TO=${4:-$(date +%F)}
: "${MSSQL_SA_PASSWORD:?set MSSQL_SA_PASSWORD to a strong password for the local container}"
mkdir -p "$OUT"

if ! docker ps --format '{{.Names}}' | grep -qx tams-mssql; then
	docker run -d --name tams-mssql --platform linux/amd64 -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD \
		-v "$(cd "$(dirname "$BAK")" && pwd)/$(basename "$BAK")":/backup/tams.bak:ro \
		mcr.microsoft.com/mssql/server:2022-latest >/dev/null
	until docker logs tams-mssql 2>&1 | grep -q "Recovery is complete"; do sleep 3; done
fi

sql() { docker exec -e SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" tams-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -Q "$1"; }
sql "IF DB_ID('Tams') IS NULL RESTORE DATABASE Tams FROM DISK='/backup/tams.bak' WITH
	MOVE 'TamsBckUp_Data' TO '/var/opt/mssql/data/Tams.mdf', MOVE 'TamsBckUp_Log' TO '/var/opt/mssql/data/Tams_0.ldf'"

export_tsv() {
	docker exec tams-mssql /opt/mssql-tools18/bin/bcp "$2" queryout "/tmp/$1" -S localhost -U sa \
		-P "$MSSQL_SA_PASSWORD" -d Tams -c -t '\t' -u | grep "rows copied"
	docker cp -q "tams-mssql:/tmp/$1" "$OUT/$1"
}

ACTIVE="JOIN Employee_Master e ON e.str_Status = 'Active'"

export_tsv employees.tsv "SELECT str_EmployeeCode,
	REPLACE(REPLACE(LTRIM(RTRIM(str_EmployeeName)), CHAR(9), ' '), CHAR(10), ' '), str_CardNo,
	ISNULL(str_JobTitle, ''), CONVERT(char(10), dtp_HireDate, 23), ISNULL(Dept, ''), str_Status
	FROM Employee_Master WHERE str_Status = 'Active' ORDER BY str_EmployeeCode"

export_tsv checkins.tsv "SELECT DISTINCT b.str_Address, CONVERT(char(19), b.dtp_DateTime, 120),
	LEFT(b.str_Mode, 4), ISNULL(b.Machine, '')
	FROM Backupdata b $ACTIVE AND e.str_CardNo = b.str_Address
	WHERE b.dtp_DateTime >= '$FROM' AND b.dtp_DateTime < DATEADD(day, 1, '$TO')"

export_tsv timesheet.tsv "SELECT t.str_EmployeeCode, CONVERT(char(10), t.dtp_Date, 23),
	ISNULL(p.str_ExpressCode, ''), ISNULL(CONVERT(char(19), t.dtp_InTime, 120), ''),
	ISNULL(CONVERT(char(19), t.dtp_OutTime, 120), ''), ISNULL(t.dbl_WrkHr, 0), ISNULL(t.dbl_OT1Hr, 0)
	FROM TimeSheet t $ACTIVE AND e.str_EmployeeCode = t.str_EmployeeCode
	LEFT JOIN Pay_Code_Master p ON p.int_PayCodeID = t.int_PayCodeID
	WHERE t.dtp_Date BETWEEN '$FROM' AND '$TO' ORDER BY t.str_EmployeeCode, t.dtp_Date"
