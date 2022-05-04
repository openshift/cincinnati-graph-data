#!/bin/sh

set -e

MAJOR_MINOR="${1}"

if test -z "${MAJOR_MINOR}"
then
	cat <<-EOF >&2
		This script stabilizes updates from 4.(y-1) to 4.y.
		Usage:
		  ${0} MAJOR_MINOR
		For example:
		  ${0} 4.10
	EOF
	exit 1
fi

CHANNELS="stable"

MAJOR="${MAJOR_MINOR%%.*}"
MINOR="${MAJOR_MINOR##*.}"
if test "${MAJOR_MINOR}" != "${MAJOR}.${MINOR}"
then
	cat <<-EOF >&2
		Usage:
		  ${0} MAJOR_MINOR
		For example:
		  ${0} 4.10
		${MAJOR_MINOR} should have a single period.
	EOF
	exit 1
fi

if test "$((MINOR % 2))" -eq 0
then
	# 4.even get extended update support: https://access.redhat.com/support/policy/updates/openshift#ocp4_phases
	CHANNELS="$(printf '%s\n%s' "${CHANNELS}" eus)"
fi

echo "${CHANNELS}" | while read CHANNEL
do
	PREVIOUS_MINORS="$((MINOR - 1))"
       	case "${CHANNEL}" in
	eus) PREVIOUS_MINORS="$((MINOR - 2))|${PREVIOUS_MINORS}"
	esac

	FILTER="${MAJOR}[.](${PREVIOUS_MINORS}|${MINOR})[.][0-9].*"
	sed -i "s/filter: .*/filter: ${FILTER}/" "channels/${CHANNEL}-${MAJOR_MINOR}.yaml"
done

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"
exec "${DIR}/stabilization-changes.py"
