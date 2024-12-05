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

PREVIOUS_MINOR="$((MINOR - 1))"
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

	PREVIOUS_MINORS="${PREVIOUS_MINOR}"
	if test "$((MINOR % 2))" -eq 0
	then
		PREVIOUS_MINORS="$((MINOR - 2))|${PREVIOUS_MINORS}"
	fi

	case "${CHANNEL}" in
	fast)
		FILTER="${MAJOR}[.](${PREVIOUS_MINORS}|${MINOR})[.][0-9].*"
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

unset GITHUB_TOKEN
unset WEBHOOK
DIR="$(dirname "${0}")"

# Execute stabilization-changes.py until it stops making changes
while "${DIR}/stabilization-changes.py" && ! git diff-files --exit-code --quiet; do
    git add .
done
git restore --staged .

# Extract the smallest (we assume it is listed first) version from the stable channel (the GA version) and bump the z_min to that version
LATEST=$(python -c "import sys, yaml; data = yaml.safe_load(sys.stdin); print(data['versions'][0])" < "channels/stable-${MAJOR_MINOR}.yaml")
# Use sed instead of doing this in python above to avoid clobbering the nice semantic ordering
sed -i -e "s|z_min: .*|z_min: ${LATEST}|" "build-suggestions/${MAJOR_MINOR}.yaml"
sed -i -e "s|minor_min: .*|minor_min: ${LATEST}|" "build-suggestions/${MAJOR}.$((MINOR + 1)).yaml"

grep "^- ${MAJOR}[.]${MINOR}[.]0-" "channels/candidate-${MAJOR_MINOR}.yaml" | sed 's/^- //' | while read VERSION
do
	cat <<-EOF > "blocked-edges/${VERSION}-PreRelease.yaml"
		to: ${VERSION}
		from: .*
		url: https://docs.openshift.com/container-platform/${MAJOR_MINOR}/release_notes/ocp-${MAJOR}-${MINOR}-release-notes.html
		name: PreRelease
		message: |-
		  This is a prerelease version, and you should update to ${LATEST} or later releases, even if that means updating to a newer ${MAJOR}.${PREVIOUS_MINOR} first.
		matchingRules:
		- type: Always
	EOF
done
