**Note**: This project uses the open AGENTS.md standard. AGENTS.md files are symlinked to CLAUDE.md files in the same directory for interoperability with Claude Code. Any agent instructions or memory features should be saved to AGENTS.md files instead of CLAUDE.md files.
# CLAUDE.md

This file provides guidance to AI code assistants when working with code in this repository.

## Repository Overview

This repository manages the Cincinnati graph for OpenShift updates. Cincinnati is an update protocol that facilitates automatic updates for OpenShift clusters. The repository defines:

- **Update channels** (candidate, fast, stable) for different OpenShift versions
- **Blocked update edges** to prevent problematic upgrades
- **Update risks** with conditional warnings based on cluster configuration

Changes merged to master are automatically consumed by the Cincinnati update service.

## Key Directories

- `channels/` - Channel definitions (candidate-X.Y, fast-X.Y, stable-X.Y)
- `blocked-edges/` - YAML files blocking or warning about specific upgrade paths
- `internal-channels/` - Internal channel configurations
- `build-suggestions/` - Release build suggestions
- `raw/` - Custom metadata for old releases (modern releases include metadata in images)
- `hack/` - Python and shell scripts for maintenance and validation

## Common Commands

### Validation
```bash
# Validate blocked-edges configuration (runs in CI)
./hack/validate-blocked-edges.py
```

### Analysis and Reporting
```bash
# Show recommended feeder promotions for releases
./hack/stabilization-changes.py

# Display edges for a specific channel
./hack/generate-weekly-report.py

# Show update graph edges
./hack/show-edges.py

# List risk declarations with fixedIn
./hack/exposure-length.sh
```

### Release Management
```bash
# Open a new minor release (creates candidate-X.Y and build-suggestions)
./hack/release-open.sh

# Create files for GA release (fast, stable, EUS channels)
./hack/release-ga.sh

# Stabilize updates from X.(Y-1) to X.Y
./hack/release-stable-minor.sh

# Mark release as end of maintenance
./hack/release-end-of-maintenance.sh
```

## Architecture

### Channel Promotion Model

Releases follow a staged promotion path proving stability at each level:

1. `candidate-X.Y` - New releases first appear here
2. `fast-X.Y` - Promoted after proving stable in candidate
3. `stable-X.Y` - Promoted after delay in fast channel

Channels use **feeder** relationships defined in channel YAML:
- `feeder.name` - Source channel for promotion
- `feeder.delay` - ISO 8601 duration (e.g., `PT48H` for 48 hours)
- `feeder.errata` - Set to `public` to allow errata-based promotion
- `feeder.filter` - Regex to exclude certain releases
- `tombstones` - List of releases that should not be promoted further

### Blocked Edges and Risks

Blocked-edges files (schema version 1.1.0) support conditional update recommendations:

**Required fields:**
- `to` - Target release version
- `from` - Regex matching source versions (receives architecture suffix like `+amd64`)

**Optional fields for declaring risks:**
- `url` - URI documenting the issue (Jira, KCS article)
- `name` - PascalCase identifier (e.g., `NonZonalAzureMachineSetScaling`)
- `message` - Human-readable description
- `matchingRules` - Array of conditions evaluated in order:
  - `type: PromQL` - Use PromQL queries to target specific configurations
  - `type: Always` - Universal risk affecting all clusters
- `fixedIn` - Release version where issue is fixed
- `autoExtend` - URI tracking fix status for auto-extension

**PromQL Patterns:**

Infrastructure provider detection:
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      (
        group by (type) (cluster_infrastructure_provider{_id="",type="Azure"})
        or
        0 * group by (type) (cluster_infrastructure_provider{_id=""})
      )
```

Managed cluster detection:
```yaml
matchingRules:
- type: PromQL
  promql:
    promql: |
      group by (_id) (sre:telemetry:managed_labels{_id=""})
```

### Release Naming

- Architecture-agnostic: `4.16.32` applies to all architectures
- Architecture-specific: `4.16.32+amd64` applies only to amd64
- Regex patterns must account for architecture suffixes (e.g., `[+].*$`)

### Schema Versioning

The `version` file contains semantic version of repository schema (currently `1.1.0`). Consumers supporting x.y.0 can safely consume when:
- Major version matches exactly
- Minor version is less than or equal to understood version

## Skills

This repository has a custom `/propose-risk` skill for creating upgrade risk declarations:

```bash
/propose-risk <jira-issue-id>
```

The skill fetches the Jira issue, analyzes impact, and proposes complete YAML files for blocked-edges with:
- Appropriate `from` regex patterns excluding already-affected versions
- PromQL queries targeting specific affected configurations
- Proper `fixedIn` placement (only in last affected patch version)
- Unique PascalCase risk names

## Workflow

1. Create topic branch from master
2. Make changes (add/edit channel or blocked-edges files)
3. Run `./hack/validate-blocked-edges.py`
4. Submit PR (reviewed via Prow workflow)
5. Merge to master (Cincinnati auto-consumes changes)

## Commit Message Format

```
<subsystem>: <what changed>

<why this change was made>

<footer>
```

Subsystem examples: `channels`, `blocked-edges`, `scripts`, `hack`
Subject line: max 70 characters
Body: wrap at 80 characters
