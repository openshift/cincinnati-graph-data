#!/bin/sh

set -e

MAJOR_MINOR="${1}"

if test -z "${MAJOR_MINOR}"
then
	cat <<-EOF >&2
		This script creates the necessary files for for a new x.y minor release.
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
		  ${0} 4.10
		${MAJOR_MINOR} should have a single period.
	EOF
	exit 1
fi

PREVIOUS_MAJOR="${MAJOR}"
PREVIOUS_MINOR="$((MINOR - 1))"

if test "${MAJOR}" = "${PREVIOUS_MAJOR}"
then
	FILTER="${MAJOR}[.](${PREVIOUS_MINOR}|${MINOR})[.][0-9].*"
else
	FILTER="(${MAJOR}[.]${MINOR}|${PREVIOUS_MAJOR}[.]${PREVIOUS_MINOR})[.][0-9].*"
fi

cat <<EOF > "build-suggestions/${MAJOR_MINOR}.yaml"
min_versions:
- ${PREVIOUS_MAJOR}.${PREVIOUS_MINOR}.0-rc.0
- ${MAJOR}.${MINOR}.0-ec.0
EOF

cat <<EOF > "channels/candidate-${MAJOR_MINOR}.yaml"
feeder:
  delay: PT0H
  filter: ${FILTER}
  name: candidate
name: candidate-${MAJOR_MINOR}
versions: []
EOF

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"
exec "${DIR}/stabilization-changes.py"
