---
name: openshift-risks
description: Manage OpenShift upgrade risks following the Update-Blocker Lifecycle. Skill 0 runs autonomously on cron to process all queues. Skill 1 creates Impact Statement Request tickets. Skill 2 creates blocked-edges YAML from completed Impact Statements.
disable-model-invocation: false
---

# OpenShift Upgrade Risk Management

This skill implements the [OpenShift Update-Blocker Lifecycle](https://github.com/openshift/enhancements/tree/master/enhancements/update/update-blocker-lifecycle) for managing upgrade risks.

## Skills Overview

| Skill | Name | Mode | Description |
|-------|------|------|-------------|
| **Skill 0** | Autonomous Orchestrator | Cron/Scheduled | Processes all queues automatically, handles full lifecycle |
| **Skill 1** | Request Impact Statement | Manual/Auto | Creates Impact Statement Request tickets for UpgradeBlocker bugs |
| **Skill 2** | Create Blocked-Edges | Manual/Auto | Generates blocked-edges YAML from completed Impact Statements |

## Overview: The Update-Blocker Lifecycle

The lifecycle has these stages and labels:

| Stage | Label | Responsible Party | Queue |
|-------|-------|-------------------|-------|
| 1. Suspect | `UpgradeBlocker` | Anyone (developer) | [Suspect Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(upgradeblocker)%20AND%20labels%20not%20in%20(ImpactStatementRequested%2C%20ImpactStatementProposed%2C%20UpdateRecommendationsBlocked)) |
| 2. Impact Requested | `ImpactStatementRequested` | Component Developer | [Component Dev Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(ImpactStatementRequested)) |
| 3. Impact Proposed | `ImpactStatementProposed` | Graph-Admin | [Graph-Admin Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(ImpactStatementProposed)) |
| 4. Recommendations Blocked | `UpdateRecommendationsBlocked` | Complete | N/A |

## Supporting Documents

- **[impact_statement_template.md](./impact_statement_template.md)**: The official template to paste into bugs
- **[team_mappings.md](./team_mappings.md)**: Maps Jira project keys to OpenShift components

---

## Skill 0: Autonomous Lifecycle Orchestrator (Cron Mode)

### When to Use

Use this skill when running as an **autonomous agent on a cron schedule**. This orchestrator processes all queues and handles the complete lifecycle automatically, only stopping when human input is required.

### Autonomous Execution Flow

When invoked, execute the following steps in order:

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Process Suspect Queue                                  │
│  (UpgradeBlocker only, no other lifecycle labels)               │
│  → For each bug with HIGH confidence team mapping:              │
│    Execute Skill 1 automatically                                │
│  → For LOW/MEDIUM confidence: Log for human review              │
├─────────────────────────────────────────────────────────────────┤
│  STEP 2: Check Stale Impact Requests                            │
│  (ImpactStatementRequested older than 7 days)                   │
│  → Add reminder comment to stale tickets                        │
├─────────────────────────────────────────────────────────────────┤
│  STEP 3: Process Graph-Admin Queue                              │
│  (ImpactStatementProposed - ready for blocked-edges)            │
│  → For each: Execute Skill 2, generate YAML, create PR          │
├─────────────────────────────────────────────────────────────────┤
│  STEP 4: Check for Fix Versions                                 │
│  (UpdateRecommendationsBlocked with new fixedIn available)      │
│  → Update existing blocked-edges with fixedIn field             │
├─────────────────────────────────────────────────────────────────┤
│  STEP 5: Generate Summary Report                                │
│  → Output what was processed, what needs human attention        │
└─────────────────────────────────────────────────────────────────┘
```

### Step 1: Process Suspect Queue

Search for new upgrade blocker bugs:

```yaml
jira_search:
  jql: "project = OCPBUGS AND labels in (UpgradeBlocker) AND labels not in (ImpactStatementRequested, ImpactStatementProposed, UpdateRecommendationsBlocked) AND status not in (Closed, Post, Verified)"
  fields: "*all"
  limit: 50
```

For each bug found:
1. Read the bug details with `jira_get_issue`
2. Determine team slug using [team_mappings.md](./team_mappings.md)
3. **If HIGH confidence**: Execute Skill 1 automatically
4. **If MEDIUM/LOW confidence**: **Do nothing** - just include in summary report for human review (no Jira changes)

### Step 2: Check Stale Impact Requests

Search for tickets waiting too long:

```yaml
jira_search:
  jql: "project = OCPBUGS AND labels in (ImpactStatementRequested) AND updated < -7d AND status not in (Closed, Post, Verified)"
  fields: "key,summary,updated,assignee"
  limit: 50
```

For each stale ticket:
1. Add a reminder comment using `jira_add_comment`:
   ```
   Friendly reminder: This Impact Statement Request has been pending for over 7 days.
   Please provide answers to the impact questions or indicate if this bug does not warrant update blocking.
   ```

### Step 3: Process Graph-Admin Queue

Search for bugs ready for blocked-edges:

```yaml
jira_search:
  jql: "project = OCPBUGS AND labels in (ImpactStatementProposed) AND status not in (Closed, Post, Verified)"
  fields: "*all"
  limit: 50
```

For each bug:
1. Read the impact statement answers
2. Execute Skill 2 to generate blocked-edges YAML
3. **Output the YAML files** for the user/CI to commit
4. **Do NOT auto-update labels** until PR is merged (requires human confirmation)

### Step 4: Check for Fix Versions

Search for blocked bugs that now have fixes:

```yaml
jira_search:
  jql: "project = OCPBUGS AND labels in (UpdateRecommendationsBlocked) AND fixVersion is not EMPTY AND resolution = Unresolved"
  fields: "key,fixVersions,summary"
  limit: 50
```

For each:
1. Check if existing blocked-edges YAML has `fixedIn`
2. If not, propose an update to add `fixedIn` to the last affected version

### Step 5: Generate Summary Report

Output a structured report:

```markdown
## Autonomous Run Summary - {TIMESTAMP}

### Processed Successfully
| Bug | Action Taken | Team |
|-----|--------------|------|
| OCPBUGS-12345 | Created Impact Statement Request MCO-9999 | MCO |
| OCPBUGS-67890 | Generated blocked-edges YAML | SDN |

### Skipped - Needs Human Review (no Jira changes made)
| Bug | Component | Reason | Suggested Team Slug |
|-----|-----------|--------|---------------------|
| OCPBUGS-11111 | (none) | Could not determine team | ? |
| OCPBUGS-22222 | "Installer" | Ambiguous component | CORS or OSASINFRA? |

### Stale Tickets (Reminders Sent)
| Bug | Days Stale | Assignee |
|-----|------------|----------|
| OCPBUGS-33333 | 12 days | @developer |

### Blocked-Edges Ready for PR
| Bug | Files Generated |
|-----|-----------------|
| OCPBUGS-67890 | 4.18.13-SomeRisk.yaml, 4.18.14-SomeRisk.yaml |

### Fix Versions Available
| Bug | Fix Version | Action Needed |
|-----|-------------|---------------|
| OCPBUGS-44444 | 4.18.20 | Add fixedIn to blocked-edges |
```

### Automation Boundaries

**The agent CAN do autonomously:**
- Create Impact Statement Request tickets (HIGH confidence team mapping only)
- Link tickets
- Update labels (except final `UpdateRecommendationsBlocked`)
- Send reminder comments on stale tickets
- Generate blocked-edges YAML files

**The agent will SKIP (no Jira changes, report only):**
- Bugs where team slug confidence is MEDIUM/LOW - just report for human to handle
- Bugs with incomplete or unclear impact statements

**The agent CANNOT do without human confirmation:**
- Merge blocked-edges PRs (requires human review)
- Add `UpdateRecommendationsBlocked` label (only after PR merge confirmed)
- Close or resolve any tickets

---

## Skill 1: Request Impact Statement

### When to Use

Use this skill when you find bugs with the `UpgradeBlocker` label that need an Impact Statement Request.

### Step 1: Find Suspect Bugs

Search for bugs in the Suspect Queue using `jira_search`:

```
jql: "project = OCPBUGS AND labels in (UpgradeBlocker) AND labels not in (ImpactStatementRequested, ImpactStatementProposed, UpdateRecommendationsBlocked) AND status not in (Closed, Post, Verified)"
```

### Step 2: Analyze the Bug

For each bug found:
1. **Read the bug** using `jira_get_issue` with:
   - `issue_key`: The bug key (e.g., `OCPBUGS-12345` or `MCO-1834`)
   - `fields`: `*all` to get all details
   - `comment_limit`: `50` to read discussion

2. **Analyze for impact**:
   - What versions are affected?
   - What cluster configurations trigger the issue?
   - How severe is the impact (data loss, upgrade failure, degradation)?
   - Is there a known workaround?

3. **Check linked issues**: Look for related bugs or fixes in progress

### Step 3: Determine the Team Slug

Most UpgradeBlocker bugs are in the `OCPBUGS` project. You need to determine which team's Jira project to create the Impact Statement Request ticket in.

**Analysis approach (in order of reliability):**

1. **Check the Component field** (most reliable if present):
   - If the bug has a Component like "HyperShift", "Machine Config Operator", "Networking / cluster-network-operator", etc.
   - Map the component to a team slug using the **OCPBUGS Component → Team Slug Mapping** table in [team_mappings.md](./team_mappings.md)

2. **Analyze the bug title and description** (if component does not help):
   - Look for keywords indicating the affected area
   - Check the Affects Version/s and Fix Version/s fields
   - Review any linked issues for context

3. **Confidence assessment**:
   - **High confidence**: Component field matches a known mapping → proceed
   - **Medium confidence**: Component is ambiguous or missing, but analysis suggests a team → ask user to confirm
   - **Low confidence**: Cannot determine → must ask user

**If uncertain or low confidence**, ask the user:
> "I found bug {ISSUE_KEY} with the following details:
> - Component: {COMPONENT or 'Not specified'}
> - Title: {TITLE}
> - Affects: {AFFECTS_VERSIONS}
> 
> Based on my analysis, this appears to be related to {ANALYSIS_REASON}. 
> Which team's Jira project should I create the Impact Statement Request in? 
> Suggested: {SUGGESTED_SLUG} (confidence: {HIGH/MEDIUM/LOW})"

### Step 4: Create Impact Statement Request Ticket

Create a NEW ticket in the team's Jira project using `jira_create_issue`:

```yaml
project_key: "<TEAM_SLUG>"  # e.g., MCO, SDN, COS
summary: "Impact Statement Request for <ORIGINAL_ISSUE_KEY>"
issue_type: "Task"  # or "Story" depending on project
description: |
  ## Impact Statement Request

  This ticket tracks the impact statement for [<ORIGINAL_ISSUE_KEY>](https://issues.redhat.com/browse/<ORIGINAL_ISSUE_KEY>).

  ---

  We're asking the following questions to evaluate whether or not <ORIGINAL_ISSUE_KEY> warrants changing update recommendations from either the previous X.Y or X.Y.Z.
  The ultimate goal is to avoid recommending an update which introduces new risk or reduces cluster functionality in any way.
  In the absence of a declared update risk (the status quo), there is some risk that the existing fleet updates into the at-risk releases.
  Depending on the bug and estimated risk, leaving the update risk undeclared may be acceptable.

  The expectation is that the assignee answers these questions.

  ---

  ### Which 4.y.z to 4.y'.z' updates increase vulnerability?

  * **reasoning**: This allows us to populate `from` and `to` in conditional update recommendations for "the $SOURCE_RELEASE to $TARGET_RELEASE update is exposed."
  * **example**: Customers upgrading from any 4.y (or specific 4.y.z) to 4.(y+1).z'. Use `oc adm upgrade` to show your current cluster version.

  ### Which types of clusters?

  * **reasoning**: This allows us to populate `matchingRules` in conditional update recommendations for "clusters like $THIS".
  * **example**: GCP clusters with thousands of namespaces, approximately 5% of the subscribed fleet. Check your vulnerability with `oc ...` or the following PromQL `count (...) > 0`.

  ---

  **The two questions above are sufficient to declare an initial update risk.** In the absence of a response within 7 days, we may declare a conditional update risk based on our current understanding.

  ---

  If you can, answers to the following questions will make the conditional risk declaration more actionable for customers.

  ### What is the impact? Is it serious enough to warrant removing update recommendations?

  * **reasoning**: This allows us to populate `name` and `message` for "...because if you update, $THESE_CONDITIONS may cause $THESE_UNFORTUNATE_SYMPTOMS".
  * **example**: Around 2 minute disruption in edge routing for 10% of clusters.
  * **example**: Up to 90 seconds of API downtime.
  * **example**: etcd loses quorum and you have to restore from backup.

  ### How involved is remediation?

  * **reasoning**: This helps administrators recover their cluster.
  * **example**: Issue resolves itself after five minutes.
  * **example**: Admin can run a single `oc ...` command.
  * **example**: Admin must SSH to hosts, restore from backups.

  ### Is this a regression?

  * **reasoning**: We only qualify update recommendations if the update increases exposure.
  * **example**: No, it has always been like this we just never noticed.
  * **example**: Yes, from 4.y.z to 4.y+1.z.
additional_fields:
  labels:
    - "ImpactStatementRequested"
```

### Step 5: Link the New Ticket to the Original Bug

Link the newly created Impact Statement Request ticket to the original bug using `jira_create_issue_link`:

```yaml
link_type: "Blocks"  # or "Relates" depending on workflow
inward_issue_key: "<NEW_TICKET_KEY>"   # The Impact Statement Request ticket
outward_issue_key: "<ORIGINAL_BUG_KEY>"  # The original bug with UpgradeBlocker
```

### Step 6: Update the Original Bug Labels

Update the original bug to indicate an impact statement has been requested using `jira_update_issue`:

```yaml
issue_key: "<ORIGINAL_BUG_KEY>"
fields:
  labels:
    - "UpgradeBlocker"
    - "ImpactStatementRequested"
```

### Step 7: Confirmation

Report to the user:
> "Created Impact Statement Request ticket {NEW_TICKET_KEY} in project {TEAM_SLUG}, linked to {ORIGINAL_BUG_KEY}. 
> The component team will answer the impact questions in the new ticket.
> Monitor the [Component Dev Queue](https://issues.redhat.com/issues/?jql=labels%20in%20(ImpactStatementRequested)) for their response."

---

## Skill 2: Create Blocked-Edges from Impact Statement

### When to Use

Use this skill when bugs have the `ImpactStatementProposed` label, meaning the component team has answered the impact questions and it's ready for graph-admin action.

### Step 1: Find Ready Bugs

Search for bugs in the Graph-Admin Queue using `jira_search`:

```
jql: "project = OCPBUGS AND labels in (ImpactStatementProposed) AND status not in (Closed, Post, Verified)"
```

### Step 2: Read the Impact Statement

For each bug:
1. **Read the full issue** using `jira_get_issue` with:
   - `issue_key`: The bug key
   - `fields`: `*all`
   - `comment_limit`: `100` to read all discussion including impact statement answers

2. **Extract the answers**:
   - **Affected versions**: From → To (from "Which updates increase vulnerability?")
   - **Cluster types**: PromQL or "all clusters" (from "Which types of clusters?")
   - **Impact description**: What goes wrong (from "What is the impact?")
   - **Remediation**: How to fix (from "How involved is remediation?")
   - **Is regression**: Yes/No (from "Is this a regression?")
   - **Fixed-in version**: If the bug has a fix version

### Step 3: Generate Blocked-Edges YAML

Based on the impact statement answers, generate the YAML files.

#### File Naming Convention
```
<version>-<RiskName>.yaml
```

#### Required Fields

| Field | Source | Example |
|-------|--------|---------|
| `to` | Affected target version | `4.16.47` |
| `from` | Regex from "Which updates increase vulnerability?" | `4[.]15[.].*` |
| `url` | The Jira issue URL | `https://issues.redhat.com/browse/MCO-1834` |
| `name` | Descriptive PascalCase identifier | `RuncShareProcessNamespace` |
| `message` | From "What is the impact?" | "Pods may fail to start..." |
| `matchingRules` | From "Which types of clusters?" | See below |

#### Matching Rules

**If the answer specifies cluster types** (cloud provider, config, etc.), use PromQL:

```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      <PromQL from impact statement>
```

**If the answer says "all clusters"**, use Always:

```yaml
matchingRules:
- type: Always
```

#### Optional Fields

| Field | When to Use |
|-------|-------------|
| `fixedIn` | Only on the **last** affected version, when a fix version is known |

### Step 4: Present the Proposal

Output the generated YAML files to the user:

```yaml
# File: 4.16.47-RiskName.yaml
to: 4.16.47
from: <regex based on impact statement>
url: https://issues.redhat.com/browse/<ISSUE_KEY>
name: <PascalCaseRiskName>
message: <impact description>
matchingRules:
- type: <PromQL or Always>
  # ... PromQL if applicable
```

### Step 5: Update the Bug Labels

After the blocked-edges PR is merged, update the bug:

1. **Update labels** using `jira_update_issue`:
   ```yaml
   issue_key: "<ISSUE_KEY>"
   fields:
     labels:
       - "UpgradeBlocker"
       - "UpdateRecommendationsBlocked"
   ```
   (Remove `ImpactStatementProposed` when adding `UpdateRecommendationsBlocked`)

2. **Add a comment** using `jira_add_comment`:
   ```yaml
   issue_key: "<ISSUE_KEY>"
   comment: |
     Update recommendations have been blocked via: <PR_URL>
     
     Blocked edges added for versions: <list of versions>
   ```

---

## Common PromQL Patterns for Matching Rules

Use these patterns based on the "Which types of clusters?" answer:

### Cloud Provider Detection
```yaml
promql: |
  (
    group by (type) (cluster_infrastructure_provider{_id="",type="Azure"})
    or
    0 * group by (type) (cluster_infrastructure_provider{_id=""})
  )
```

### HyperShift / Hosted Clusters
```yaml
promql: |
  group by (_id, invoker) (cluster_installer{_id="",invoker="hypershift"})
  or
  0 * group by (_id, invoker) (cluster_installer{_id=""})
```

### Managed Clusters (ROSA, ARO)
```yaml
promql: |
  group by (_id) (sre:telemetry:managed_labels{_id=""})
```

### Specific Operator Installed
```yaml
promql: |
  group(csv_succeeded{_id="", name=~"sriov-network-operator[.].*"})
  or
  0 * group(csv_count{_id=""})
```

### Bare Metal / None Platform
```yaml
promql: |
  group by (_id, type) (cluster_infrastructure_provider{_id="",type=~"None|BareMetal"})
  or on (_id)
  0 * group by (_id, type) (cluster_infrastructure_provider{_id=""})
```

---

## Quick Reference: Jira MCP Tools

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `jira_search` | Find bugs by JQL | `jql`, `fields`, `limit` |
| `jira_get_issue` | Read bug details | `issue_key`, `fields`, `comment_limit` |
| `jira_create_issue` | Create new ticket | `project_key`, `summary`, `issue_type`, `description`, `additional_fields` |
| `jira_add_comment` | Add comment to bug | `issue_key`, `comment` |
| `jira_update_issue` | Update labels/fields | `issue_key`, `fields` |
| `jira_create_issue_link` | Link two issues | `link_type`, `inward_issue_key`, `outward_issue_key` |

---

## References

- [Update-Blocker Lifecycle Enhancement](https://github.com/openshift/enhancements/tree/master/enhancements/update/update-blocker-lifecycle)
- [Cincinnati Graph Data - Block Edges](https://github.com/openshift/cincinnati-graph-data#block-edges)
- [Suspect Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(upgradeblocker)%20AND%20labels%20not%20in%20(ImpactStatementRequested%2C%20ImpactStatementProposed%2C%20UpdateRecommendationsBlocked))
- [Component Dev Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(ImpactStatementRequested))
- [Graph-Admin Queue](https://issues.redhat.com/issues/?jql=project%20%3D%20OCPBUGS%20AND%20labels%20in%20(ImpactStatementProposed))
