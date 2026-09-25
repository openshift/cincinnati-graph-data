# Team Slug Mappings for OpenShift Risk Tickets

This document maps Jira project keys (team slugs) to their associated OpenShift components and areas. Use this to determine where to file upgrade risk tickets based on the component affected by a bug.

**Important**: Most UpgradeBlocker bugs are filed in the `OCPBUGS` project. The Component field on the bug tells you which team owns it.

---

## OCPBUGS Component → Team Slug Mapping

When a bug is in `OCPBUGS`, use the Component field to determine which team's project to create the Impact Statement Request in:

| OCPBUGS Component | Team Slug | Confidence |
|-------------------|-----------|------------|
| HyperShift | `HOSTEDCP` or `CNTRLPLANE` | High |
| Machine Config Operator | `MCO` | High |
| Networking / cluster-network-operator | `SDN` | High |
| Networking / ovn-kubernetes | `SDN` | High |
| Networking / multus | `CORENET` | High |
| Console | `CONSOLE` | High |
| etcd | `ETCD` | High |
| Storage | `STOR` | High |
| Storage / vsphere-csi-driver | `STOR` | High |
| Image Registry | `IR` | High |
| Cloud Compute / Cluster API | `OCPCLOUD` | High |
| Cloud Compute / Machine Config Operator | `MCO` | High |
| Cloud Compute / Azure | `OCPCLOUD` | High |
| Cloud Compute / AWS | `OCPCLOUD` | High |
| Cloud Compute / GCP | `OCPCLOUD` | High |
| Node | `OCPNODE` | High |
| Installer | `CORS` | Medium |
| Installer / OpenStack | `OSASINFRA` | High |
| OLM | `OPRUN` | High |
| kube-apiserver | `API` | High |
| authentication | `AUTH` | High |
| oauth-server | `AUTH` | High |
| Routing | `NE` | High |
| Ingress | `NE` | High |
| Bare Metal Hardware Provisioning | `METAL` | High |
| Release | `OTA` | High |
| Cluster Version Operator | `OTA` | High |
| RHCOS | `COS` | High |
| MCO | `MCO` | High |
| (No component) | Ask user | Low |

**Notes on ambiguous components:**
- **HyperShift**: Could be `HOSTEDCP` (NodePool issues) or `CNTRLPLANE` (control plane issues) - ask if unclear
- **Installer**: Could be `CORS` (general) or platform-specific like `OSASINFRA` (OpenStack)
- If component is missing or not in this list, analyze the bug content and ask user

---

## Primary Team Mappings

| Team Slug | Full Name | Components / Areas | Example Risk Names |
|-----------|-----------|-------------------|-------------------|
| **API** | API Server | Kubernetes API, ServiceAccounts, Certificates, API server operations | `ServiceAccountContentionSecretCreation`, `EarlyAPICertRotation` |
| **AUTH** | Authentication | OAuth, Identity Providers, Authentication | `OAuthServerDownIfSpaceInIDPName` |
| **CCO** | Cloud Credential Operator | Cloud credentials, Mint mode, Passthrough mode | `GCPMintModeRoleAdmin` |
| **CNF** | Cloud Native Functions | MetalLB, BGP, BFD, SR-IOV (networking focus for telco) | `MetallbBgpBfdFrrRpm` |
| **CNTRLPLANE** | Control Plane (HyperShift) | HyperShift, Hosted Clusters, Control Plane operators | `HyperShiftRedundantRouter`, `HyperShiftClusterVersionOperatorMetrics` |
| **CONSOLE** | Web Console | OpenShift Console, UI components | `ConsoleEnabledTargetDownAlert` |
| **CORENET** | Core Networking | OVN, Network policies, Core networking features | `WhereaboutsControllerCreateContainerError` |
| **COS** | CoreOS | RHCOS, OS updates, Bootc, NVMe, Kernel, Symlinks | `NVMeSymlinkRegeneration`, `RHELKernelHighLoadIOWait` |
| **ETCD** | Etcd | Etcd cluster, Backups, etcd operator | `EtcdBackupMountPointStuck` |
| **HOSTEDCP** | Hosted Control Plane | HyperShift NodePools, Hosted cluster networking | `HyperShiftNodePoolSkewBinaryDownload`, `HyperShiftKubeAPIPort443` |
| **IR** | Image Registry | In-cluster image registry, Registry operator | `AzureRegistryImagePreservation`, `AzureRegistryImageMigrationUserProvisioned` |
| **MCO** | Machine Config Operator | Machine configs, OS updates, Node configuration, rpm-ostree | `AWSOldBootImagesLackAfterburn`, `MachineConfigRenderingChurn`, `OSUpdateFailureDueToImagePullPolicy` |
| **METAL** | Bare Metal | Bare metal provisioning, Ironic | `BrokenBaremetalProvisioning` |
| **NE** | Network Edge | Ingress, HAProxy, Router, Edge networking | `IngressDegradedOnRouterReloads` |
| **NHE** | Node Hardware Enablement | SR-IOV operator, Hardware enablement for nodes | `SRIOVFailedToConfigureVF` |
| **OCPBUGS** | OCP Bugs (General) | General OpenShift bugs (legacy, less specific) | `OVNNetworkPolicyLongName`, `PodmanTermStorageCorruption` |
| **OCPCLOUD** | OCP Cloud Providers | Cloud-specific issues (AWS, Azure, GCP integrations), MachineSets | `NonZonalAzureMachineSetScaling`, `NoCloudConfConfigMap` |
| **OCPNODE** | OCP Node | Node operations, Kubelet, SELinux | `KubeletStartFailingFromRestoreconTimeout` |
| **OPNET** | OpenStack Networking | Azure/OpenStack networking, Accelerated networking | `AcceleratedNetworkingRace` |
| **OPRUN** | Operator Runtime (OLM) | Operator Lifecycle Manager, CSV states | `OLMOperatorsInFailedState` |
| **OSASINFRA** | OpenStack Infrastructure | OpenStack CSI, Availability zones, Cinder | `OpenStackAvailabilityZoneOutOfRange` |
| **OTA** | Over-The-Air Updates | Cincinnati, Update service, CVO metrics, Pre-release risks | `PreRelease`, `HyperShiftClusterVersionOperatorMetrics` |
| **RUN** | Runtime (Container Runtime) | runc, CRI-O, Container runtime | `RuncShareProcessNamespace` |
| **SDN** | Software Defined Networking | OVN-Kubernetes, SDN, IPsec, Localnet | `OVNIPsecConnectivity`, `OVNLocalnetWithNoSubnets` |
| **STOR** | Storage | CSI drivers, vSphere storage, NFS, Persistent volumes | `VSphereStorageMountIssues` |

## How to Determine the Team Slug

When proposing a risk or creating a Jira ticket, follow this decision tree:

### 1. Check the Bug's Existing Jira Key
If the source bug already has a Jira key (e.g., `MCO-1834`), use the same project key for the risk ticket.

### 2. Identify by Component Area

**Cluster Infrastructure & Cloud:**
- AWS/Azure/GCP MachineSet issues → `OCPCLOUD`
- Cloud credentials/Mint mode → `CCO`
- OpenStack infrastructure → `OSASINFRA`
- Bare metal provisioning → `METAL`

**Networking:**
- OVN/SDN/IPsec/Network policies → `SDN`
- Ingress/Router/HAProxy → `NE`
- Core network (Whereabouts, etc.) → `CORENET`
- MetalLB/BGP → `CNF`

**Node & OS:**
- RHCOS/OS updates/Kernel → `COS`
- Machine configs/rpm-ostree → `MCO`
- Kubelet/SELinux/Node issues → `OCPNODE`
- SR-IOV/Hardware enablement → `NHE`

**Control Plane:**
- HyperShift/Hosted clusters → `CNTRLPLANE` or `HOSTEDCP`
- Etcd issues → `ETCD`
- API server/ServiceAccounts → `API`

**Operators & Runtime:**
- OLM/Operators → `OPRUN`
- Container runtime (runc, CRI-O) → `RUN`

**Storage & Registry:**
- CSI drivers/PV issues → `STOR`
- Image registry → `IR`

**Authentication & Console:**
- OAuth/IDP → `AUTH`
- Web console → `CONSOLE`

**Updates & Cincinnati:**
- Update service/CVO → `OTA`

### 3. When Uncertain

If you cannot determine the appropriate team:
1. Check if the bug affects a specific operator - look at the component field
2. Ask the user: *"I couldn't determine the team slug for component '{X}'. Which project key should I use?"*


## Notes

- **OCPBUGS** is a legacy catch-all project; prefer more specific projects when available
- **CNTRLPLANE** vs **HOSTEDCP**: Both handle HyperShift; use `CNTRLPLANE` for control plane operators, `HOSTEDCP` for NodePool/hosted networking issues
- **SDN** vs **CORENET**: Use `SDN` for OVN-Kubernetes specifics, `CORENET` for general networking infrastructure

