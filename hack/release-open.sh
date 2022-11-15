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

PREVIOUS_MINOR="$((MINOR - 1))"

cat <<EOF > "build-suggestions/${MAJOR_MINOR}.yaml"
default:
  minor_min: ${MAJOR}.${PREVIOUS_MINOR}.0-rc.0
  minor_max: ${MAJOR}.${PREVIOUS_MINOR}.9999
  minor_block_list: []
  z_min: ${MAJOR_MINOR}.0-ec.0
  z_max: ${MAJOR_MINOR}.9999
  z_block_list: []
EOF

cat <<EOF > "channels/candidate-${MAJOR_MINOR}.yaml"
feeder:
  delay: PT0H
  filter: ${MAJOR}[.](${PREVIOUS_MINOR}|${MINOR})[.][0-9].*
  name: candidate
name: candidate-${MAJOR_MINOR}
versions: []
EOF

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"
exec "${DIR}/stabilization-changes.py"
