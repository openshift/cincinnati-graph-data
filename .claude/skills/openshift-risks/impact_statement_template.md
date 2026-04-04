# Impact Statement Request Template

This template is from the [OpenShift Update-Blocker Lifecycle Enhancement](https://github.com/openshift/enhancements/tree/master/enhancements/update/update-blocker-lifecycle).

When adding the `ImpactStatementRequested` label to a bug, paste the following statement into the bug as a comment.

---

## Template

We're asking the following questions to evaluate whether or not {ISSUE_KEY} warrants changing update recommendations from either the previous X.Y or X.Y.Z.
The ultimate goal is to avoid recommending an update which introduces new risk or reduces cluster functionality in any way.
In the absence of a declared update risk (the status quo), there is some risk that the existing fleet updates into the at-risk releases.
Depending on the bug and estimated risk, leaving the update risk undeclared may be acceptable.

Sample answers are provided to give more context and the `ImpactStatementRequested` label has been added to {ISSUE_KEY}.
When responding, please move this ticket to `Code Review`.
The expectation is that the assignee answers these questions.

### Which 4.y.z to 4.y'.z' updates increase vulnerability?

* **reasoning**: This allows us to populate [`from` and `to` in conditional update recommendations][graph-data-block] for "the `$SOURCE_RELEASE` to `$TARGET_RELEASE` update is exposed.
* **example**: Customers upgrading from any 4.y (or specific 4.y.z) to 4.(y+1).z'.  Use `oc adm upgrade` to show your current cluster version.

### Which types of clusters?

* **reasoning**: This allows us to populate [`matchingRules` in conditional update recommendations][graph-data-block] for "clusters like `$THIS`".
* **example**: GCP clusters with thousands of namespaces, approximately 5% of the subscribed fleet.  Check your vulnerability with `oc ...` or the following PromQL `count (...) > 0`. If PromQL is provided and the underlying bug might impact updates out of a [4.19](https://docs.redhat.com/en/documentation/openshift_container_platform/4.19/html-single/release_notes/index#ocp-4-19-monitoring-metrics-collection-profiles-ga) or newer cluster, please list [the metrics collection profiles](https://docs.redhat.com/en/documentation/openshift_container_platform/4.19/html-single/monitoring/index#choosing-a-metrics-collection-profile_configuring-performance-and-scalability) with which the PromQL works.

---

**The two questions above are sufficient to declare an initial update risk, and we would like as much detail as possible on them as quickly as you can get it.**

Perfectly crisp responses are nice, but are not required.
For example "it seems like these platforms are involved, because..." in a day 1 draft impact statement is helpful, even if you follow up with "actually, it was these other platforms" on day 3.
In the absence of a response within 7 days, we may or may not declare a conditional update risk based on our current understanding of the issue.

---

If you can, answers to the following questions will make the conditional risk declaration more actionable for customers.

### What is the impact?  Is it serious enough to warrant removing update recommendations?

* **reasoning**: This allows us to populate [`name` and `message` in conditional update recommendations][graph-data-block] for "...because if you update, `$THESE_CONDITIONS` may cause `$THESE_UNFORTUNATE_SYMPTOMS`".
* **example**: Around 2 minute disruption in edge routing for 10% of clusters.  Check with `oc ...`.
* **example**: Up to 90 seconds of API downtime.  Check with `curl ...`.
* **example**: etcd loses quorum and you have to restore from backup.  Check with `ssh ...`.

### How involved is remediation?

* **reasoning**: This allows administrators who are already vulnerable, or who chose to waive conditional-update risks, to recover their cluster.
  And even moderately serious impacts might be acceptable if they are easy to mitigate.
* **example**: Issue resolves itself after five minutes.
* **example**: Admin can run a single: `oc ...`.
* **example**: Admin must SSH to hosts, restore from backups, or other non standard admin activities.

### Is this a regression?

* **reasoning**: Updating between two vulnerable releases may not increase exposure (unless rebooting during the update increases vulnerability, etc.).
  We only qualify update recommendations if the update increases exposure.
* **example**: No, it has always been like this we just never noticed.
* **example**: Yes, from 4.y.z to 4.y+1.z Or 4.y.z to 4.y.z+1.

---

[graph-data-block]: https://github.com/openshift/cincinnati-graph-data/tree/master#block-edges

---

## How to Use This Template

1. Copy the template above (from "We're asking the following questions..." to the end)
2. Replace `{ISSUE_KEY}` with the actual Jira issue key (e.g., `MCO-1834`)
3. Paste it as a comment on the Jira issue
4. Add the `ImpactStatementRequested` label to the issue
5. Remove the `UpgradeBlocker` label if present (or keep it per workflow)

