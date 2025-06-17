#!/bin/sh
#
# Risk declaration until fixed release declared.  Usage:
#
#  $ hack/exposure-length.sh [RISK_NAME ...]
#
# With no RISK_NAMEs, it will list the duration of all the fixedIn
# risks.  With RISK_NAMEs, it will only list the duration of those
# risks.  For example:
#
#  $ hack/exposure-length.sh KeepalivedMulticastSkew DualStackNeedsController

DATE_CMD=${DATE_CMD:-"date"}
SED_CMD=${SED_CMD:-"sed"}

calculate_exposure() {
	RISK="$1"
	RISK_DECLARED="$(git log -G "^name: ${RISK}\$" --first-parent --date=short --format='%ad' blocked-edges | tail -n1)"
	FIX_PATH="$(grep -r40 "^name: ${RISK}\$" blocked-edges | "${SED_CMD}" -n 's/-fixedIn: .*//p' | head -n1)"
	FIX_DECLARED="$(git log -G "^fixedIn: " --first-parent --date=short --format='%ad' "${FIX_PATH}" | tail -n1)"
	RISK_DECLARED_SECONDS="$(${DATE_CMD} --date "${RISK_DECLARED}" '+%s')"
	FIX_DECLARED_SECONDS="$(${DATE_CMD} --date "${FIX_DECLARED}" '+%s')"
	DURATION_SECONDS=$((FIX_DECLARED_SECONDS - RISK_DECLARED_SECONDS))
	DURATION_DAYS=$((DURATION_SECONDS / 86400))
	printf '%s - %s (%s days): %s\n' "${RISK_DECLARED}" "${FIX_DECLARED}" "${DURATION_DAYS}" "${RISK}"
}

if test "$#" -eq 0
then
	RISKS="$(grep -h '^name: ' $(grep -rl fixedIn blocked-edges) | sort | uniq | "${SED_CMD}" 's/name: //')"
	set -- ${RISKS}
fi

while test "$#" -gt 0
do
	RISK="$1"
	shift
	calculate_exposure "${RISK}"
done
