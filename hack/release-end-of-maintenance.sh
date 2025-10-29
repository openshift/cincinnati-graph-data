#!/usr/bin/env bash

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
		This script marks a 4.y release as having completed its Maintenance phase, removing promotions into stable channels for 4.y.
		Usage:
		  ${0} MAJOR_MINOR
		For example:
		  ${0} 4.10
	EOF
	exit 1
fi

MAJOR="${MAJOR_MINOR%%.*}"
MINOR="${MAJOR_MINOR##*.}"
if test "${MAJOR_MINOR}" != "${MAJOR}.${MINOR}"
then
	cat <<-EOF >&2
		Usage:
		  ${0} MAJOR_MINOR
		For example:
		  ${0} 4.11
		${MAJOR_MINOR} should have a single period.
	EOF
	exit 1
fi

SED_CMD="${SED_CMD:-"sed"}"
"${SED_CMD}" -i '/feeder:/,/^[^ ]/{//!d};/feeder:/d' "channels/stable-${MAJOR}.${MINOR}.yaml"

FILTER="${MAJOR}[.]$((MINOR + 1))[.][0-9].*"
"${SED_CMD}" -i "s/filter: .*/filter: ${FILTER}/" "channels/stable-${MAJOR}.$((MINOR + 1)).yaml"

if test "$((MINOR % 2))" -eq 0
then
	FILTER="${MAJOR}[.]($((MINOR + 1))|$((MINOR + 2)))[.][0-9].*"
	"${SED_CMD}" -i "s/filter: .*/filter: ${FILTER}/" "channels/stable-${MAJOR}.$((MINOR + 2)).yaml"
fi
