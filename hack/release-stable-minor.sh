#!/bin/sh

set -e

if ! git diff-index --exit-code --quiet HEAD --
then
	echo "This script must be run with clean git state" >&2
	exit 1
fi

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

# 4.even get extended update support: https://access.redhat.com/support/policy/updates/openshift#ocp4_phases
if test "$((MINOR % 2))" -eq 0
then
	echo "${MAJOR_MINOR} is an EUS release, will update stable and eus channels"
	CHANNELS="$(printf '%s\n%s' "${CHANNELS}" eus)"
else
	echo "${MAJOR_MINOR} is not an EUS release, will update stable channel only (there is no eus channel to update)"
fi

PREVIOUS_MINORS="$((MINOR - 1))"
if test "$((MINOR % 2))" -eq 0
then
	PREVIOUS_MINORS="$((MINOR - 2))|${PREVIOUS_MINORS}"
fi

FILTER="${MAJOR}[.](${PREVIOUS_MINORS}|${MINOR})[.][0-9].*"

echo "${CHANNELS}" | while read CHANNEL
do
	sed -i "s/filter: .*/filter: ${FILTER}/" "channels/${CHANNEL}-${MAJOR_MINOR}.yaml"
done

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"
I=1
STABILIZATION_LOG="$(mktemp)"
touch "${STABILIZATION_LOG}"

# Execute stabilization-changes.py until it stops making changes
while true; do
	echo "Running stabilization-changes.py: iteration ${I}" | tee -a "${STABILIZATION_LOG}"
	if ! "${DIR}"/stabilization-changes.py &>> "${STABILIZATION_LOG}"; then
		echo "FAIL: stabilization-changes.py output tail: (see full log in ${STABILIZATION_LOG})"
		tail "${STABILIZATION_LOG}"
		break
	fi
	if git diff-files --exit-code --quiet; then
		break
	fi
	git add .
	I=$((I + 1))
done
git restore --staged .

echo "See ${STABILIZATION_LOG} for stabilization-changes.py output if needed"
