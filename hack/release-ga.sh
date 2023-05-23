#!/bin/sh

set -e

MAJOR_MINOR="${1}"

if test -z "${MAJOR_MINOR}"
then
	cat <<-EOF >&2
		This script creates the necessary files for for a new x.y minor release which includes fast, stable and, when appropriate, EUS channel files with required metadata for automation.
		Usage:
		  ${0} MAJOR_MINOR
		For example:
		  ${0} 4.10
	EOF
	exit 1
fi

CHANNELS="$(printf '%s\n%s' fast stable)"

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

RELEASES="$(grep "^- ${MAJOR}[.]${MINOR}[.][0-9]" internal-channels/fast.yaml || (echo "failed to find ${MAJOR_MINOR} releases in internal-channels/fast.yaml" >&2; exit 1))"
if test -z "${RELEASES}"
then
	VERSIONS='versions: []'
else  # promote already-supported 4.y.* immediately, without waiting for cooking, because there will be no updates in stable/EUS that need cook-guarding
	VERSIONS="$(printf 'versions:\n%s' "${RELEASES}")"
	echo "${RELEASES}" >>internal-channels/stable.yaml
fi

echo "${CHANNELS}" | while read CHANNEL
do
	case "${CHANNEL}" in
	eus) FEEDER=stable;;
	*) FEEDER="${CHANNEL}";;
	esac

	case "${CHANNEL}" in
	fast)
		PREVIOUS_MINOR="$((MINOR - 1))"
		FILTER="${MAJOR}[.](${PREVIOUS_MINOR=}|${MINOR})[.][0-9].*"
		;;
	*) FILTER="${MAJOR}[.]${MINOR}[.][0-9].*";;
	esac

	cat <<-EOF > "channels/${CHANNEL}-${MAJOR_MINOR}.yaml"
		feeder:
		  delay: PT0H
		  filter: ${FILTER}
		  name: ${FEEDER}
		name: ${CHANNEL}-${MAJOR_MINOR}
		$VERSIONS
	EOF
done

# Bump minimal target version to GA one
sed -i -e "s|z_min: .*|z_min: ${MAJOR}.${MINOR}.0|" "build-suggestions/${MAJOR}.${MINOR}.yaml"

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"
exec "${DIR}/stabilization-changes.py"
