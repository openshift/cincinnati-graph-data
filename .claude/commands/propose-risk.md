---
description: Propose an upgrade risk based on a Jira issue
---

You are helping create a new upgrade risk declaration based on a Jira issue.

## Arguments

Usage: `/propose-risk <jira-issue>`

- `$1` - Jira issue ID (e.g., `MCO-1834`, `CORENET-6196`, `OCPBUGS-12345`)

Example: `/propose-risk MCO-1834`

## Task

Your goal is to propose a complete, well-formed upgrade risk YAML file for the blocked-edges directory based on the Jira issue.

### Step 1: Research the Jira Issue

1. Extract the Jira issue URL: `https://issues.redhat.com/browse/$1`

2. Review the Jira issue's impact statement and linked bugs:
   - The impact statement often contains crucial details about affected versions, scope, and severity
   - Look for linked/related bugs in the Jira issue that provide additional context
   - Linked bugs may reveal:
     - Specific infrastructure providers affected (AWS, GCP, Azure, etc.)
     - Configuration requirements that trigger the issue
     - Customer impact and reproduction scenarios
     - Version information for `fixedIn` field

### Step 2: Propose the Risk Declaration

When a risk affects multiple versions, propose the risk declarations in **ascending order** based on the `to` field (lowest version first, highest version last). For example, if a risk affects 4.16.47, 4.16.48, 4.17.40, propose them in that order: 4.16.47 → 4.16.48 → 4.17.40.

Based on the Jira issue, your OpenShift knowledge, and patterns from similar risks, create a proposal with:

**Required Fields:**
- `to`: Target release version (you'll need to infer or ask the user for the affected version)
- `from`: Source version pattern (regex like `4[.]18[.].*` for upgrades from 4.18.x)
- `url`: Jira issue URL
- `name`: CamelCase risk identifier extracted from Jira title/summary
  - Check for name conflicts - Search blocked-edges to ensure this name isn't already used (e.g., `grep -l "name: RiskName" blocked-edges/*.yaml`)
  - If the name already exists, you must create a different, unique name for this new risk
  - Risk names must be unique identifiers; reusing an existing name is only valid when extending that same risk to new versions
- `message`: Human-readable description of the issue and impact

**Optional but Recommended:**
- `matchingRules`: Conditional update rules based on cluster characteristics
  - **PREFER PromQL** - Use PromQL queries to target specific affected configurations:
    - Infrastructure provider detection (AWS, GCP, Azure, etc.)
    - Cluster configuration detection (IPsec, managed vs self-managed, etc.)
    - Component state detection (operator presence, feature flags, etc.)
  - **Use `Always` ONLY when:**
    - The risk affects ALL clusters regardless of configuration, OR
    - A PromQL query cannot be created for the affected subset
  - Avoid unnecessary warnings by being specific with PromQL
- `fixedIn`: Release version where the issue is fixed (if known from Jira)
  - Only set `fixedIn` in the LAST affected patch version for a given release
  - Example: If issue affects 4.16.3, 4.16.4, and 4.16.5 (fixed in 4.16.6), only the 4.16.5 risk file should have `fixedIn: 4.16.6`
  - Earlier affected versions (4.16.3, 4.16.4) should NOT include the `fixedIn` field
- `autoExtend`: Tracking URI if the risk should be automatically extended

### Step 3: Generate Proposal

Present the proposal to the user in this format:

For each minor version group, display only:
- The **first** affected version (e.g., 4.16.47)
- The **last** affected version **only if** it includes the `fixedIn` field (e.g., 4.16.50 with fixedIn: 4.16.51)

#### Proposed Risk Declaration

**Risk details:**
- Issue: $1
- URL: `<jira-url>`
- Component: `<component-name>`
- Affected versions: List all affected versions (e.g., 4.16.47-50, 4.17.40-42)

**Proposed YAML for 4.16.47:**
```yaml
to: 4.16.47
from: 4[.](15[.].*|16[.]([1-3]?[0-9]|4[0-6]))
url: <jira-url>
name: <CamelCaseRiskName>
message: |
  <Human-readable description of the issue>
matchingRules:
- type: <PromQL|Always>
  promql:
    promql: |
      <PromQL query if applicable>
```

**Proposed YAML for 4.16.50** (if fixedIn applies):
```yaml
to: 4.16.50
from: 4[.](15[.].*|16[.]([1-3]?[0-9]|4[0-6]))
fixedIn: 4.16.51
url: <jira-url>
name: <CamelCaseRiskName>
message: |
  <Human-readable description of the issue>
matchingRules:
- type: <PromQL|Always>
  promql:
    promql: |
      <PromQL query if applicable>
```

**Note:** Versions 4.16.48, 4.16.49 use the same YAML as 4.16.47 (only `to` field changes).

**Reasoning:**
- Explain why you chose these values
- Explain the matchingRules logic (if PromQL)
- Note any assumptions made

**Next steps:**
1. Review and adjust the proposed values
2. Check for sensitive information
3. Plan to create files for all affected versions: `blocked-edges/<version>-<RiskName>.yaml`
4. If approved by the user, create all the files
5. Run validation: `./hack/validate-blocked-edges.py`
6. Test the PromQL query if applicable

## Guidelines for Risk Creation

### Name Guidelines
- Use PascalCase (CamelCase with first letter capitalized)
- Be descriptive but concise
- Examples: `InvalidArchitectureValueOfMachinesetsAnnotation`, `RuncShareProcessNamespace`, `IPsecLargeClusterConnectivity`

### Message Guidelines
- **Length**: Typically 1-2 sentences (~100-250 characters)
- Describe the failure mode and impact clearly
- Start with component context if relevant

### PromQL Guidelines
Common patterns for matchingRules:

**Infrastructure provider detection:**
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      (
        group by (type) (cluster_infrastructure_provider{_id="",type="AWS|GCP"})
        or
        0 * group by (type) (cluster_infrastructure_provider{_id=""})
      )
```

**Managed cluster detection:**
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      group by (_id) (sre:telemetry:managed_labels{_id=""})
```

**Operator presence detection:**
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      topk(1,
        group by (_id, name) (cluster_operator_conditions{_id="",name="<operator-name>"})
        or
        0 * group by (_id, name) (cluster_operator_conditions{_id=""})
      )
```

**Feature flag or configuration detection:**
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      (
        group by (ipsec) (label_replace(max_over_time(ovnkube_controller_ipsec_enabled{_id=""}[1h]), "ipsec", "enabled", "", "") == 1)
        or on (_id)
        0 * group by (ipsec) (label_replace(max_over_time(ovnkube_controller_ipsec_enabled{_id=""}[1h]), "ipsec", "disabled", "", "") == 0)
      )
```

**Universal risk:**
```yaml
matchingRules:
- type: Always
```

### From Pattern Guidelines

The `from` field specifies which source versions trigger the upgrade warning when upgrading to the `to` version.

#### Core Principles

1. **Warn only for unaffected → affected upgrades**
   - Don't warn for affected → affected (user already has the issue)
   - Focus warnings on new risk exposures

2. **Warn from immediate previous minor at most**
   - For `to: 4.16.x`, use `4[.]15[.].*` at most

3. **Reuse the same regex for all affected versions in same minor**
   - Create the regex once for the first affected version
   - Apply it identically to all subsequent versions in that minor

#### Creating `from` Patterns

**Step 1:** List all affected versions grouped by minor:
```
4.16: [47, 48, 49, 50]
4.17: [40, 41, 42]
4.18: [23, 24, 25, 26]
```

**Step 2:** For each minor, determine unaffected patches in same/previous minor:
- 4.16.47: unaffected = 4.15.* + 4.16.0-46
- 4.17.40: unaffected = 4.16.0-46 (not 47-50!) + 4.17.0-39
- 4.18.23: unaffected = 4.17.0-39 (not 40-42!) + 4.18.0-22

**Step 3:** Create regex for first affected version in each minor:
```yaml
# For 4.16.47, 4.16.48, 4.16.49, 4.16.50
from: 4[.](15[.].*|16[.]([1-3]?[0-9]|4[0-6]))

# For 4.17.40, 4.17.41, 4.17.42
from: 4[.](16[.]([1-3]?[0-9]|4[0-6])|17[.]([1-3]?[0-9]))

# For 4.18.23, 4.18.24, 4.18.25, 4.18.26
from: 4[.](17[.]([1-3]?[0-9])|18[.](1?[0-9]|2[0-2]))
```

**Key:** Exclude previously affected versions (4.16.47-50 not in 4.17.40 pattern, etc.)

#### Regex Pattern Reference

**Compact ranges using `?`:**
- `[1-3]?[0-9]` = 0-39
- `[1-4]?[0-9]|5[0-6]` = 0-56

**Common patterns:**
- All patches: `4[.]18[.].*`
- Range 0-46: `4[.]16[.]([1-3]?[0-9]|4[0-6])`
- Small range: `4[.]19[.][0-7]`
- Multi-minor: `4[.](15[.].*|16[.]([1-3]?[0-9]|4[0-6]))`

## Notes

- Use your knowledge of OpenShift components and telemetry to create accurate PromQL queries
- If uncertain about any field, present options to the user
- Validate that the PromQL syntax follows existing patterns
- Check if similar risks exist for reference