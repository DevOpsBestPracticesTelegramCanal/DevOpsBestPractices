"""
DUCS Expert System - DevOps Unified Classification System
NO-LLM классификатор для DevOps задач

Секретное оружие русских - 384 DUCS кода
"""

from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import re


class DUCSCategory(Enum):
    """Main DUCS Categories (100-900)"""
    CONTAINERS = 100        # Docker, Podman, containerd
    ORCHESTRATION = 200     # Kubernetes, OpenShift, Nomad
    CI_CD = 300             # Jenkins, GitLab CI, GitHub Actions
    MONITORING = 400        # Prometheus, Grafana, ELK
    SECURITY = 500          # CVE, Vault, RBAC
    CLOUD = 600             # AWS, GCP, Azure, Yandex
    IaC = 700               # Terraform, Ansible, Pulumi
    NETWORKING = 800        # Service Mesh, Ingress, DNS
    DEVOPS_GENERAL = 900    # Best practices, Culture


@dataclass
class DUCSCode:
    """A DUCS classification code"""
    code: str               # e.g. "201.03"
    category: DUCSCategory
    subcategory: str
    name: str
    description: str
    keywords: List[str]
    tools: List[str]


class DUCSClassifier:
    """
    DUCS Expert System - NO-LLM Classification

    Классифицирует DevOps задачи без использования LLM
    на основе паттернов и ключевых слов
    """

    # DUCS Knowledge Base - основные коды
    DUCS_CODES: Dict[str, DUCSCode] = {
        # 100 - Containers
        "100.01": DUCSCode("100.01", DUCSCategory.CONTAINERS, "Docker", "Dockerfile",
                          "Создание и оптимизация Dockerfile",
                          ["dockerfile", "docker build", "multi-stage", "image"],
                          ["docker"]),
        "100.02": DUCSCode("100.02", DUCSCategory.CONTAINERS, "Docker", "Docker Compose",
                          "Оркестрация локальных контейнеров",
                          ["docker-compose", "compose", "yaml", "services"],
                          ["docker-compose", "docker compose"]),
        "100.03": DUCSCode("100.03", DUCSCategory.CONTAINERS, "Docker", "Docker Registry",
                          "Работа с реестрами образов",
                          ["registry", "push", "pull", "tag", "harbor"],
                          ["docker", "harbor", "registry"]),
        "100.04": DUCSCode("100.04", DUCSCategory.CONTAINERS, "Podman", "Podman",
                          "Rootless контейнеры",
                          ["podman", "buildah", "skopeo", "rootless"],
                          ["podman", "buildah"]),
        "100.05": DUCSCode("100.05", DUCSCategory.CONTAINERS, "Runtime", "Container Runtime",
                          "containerd, CRI-O, runc",
                          ["containerd", "cri-o", "runc", "runtime"],
                          ["containerd", "cri-o"]),

        # 200 - Orchestration
        "200.01": DUCSCode("200.01", DUCSCategory.ORCHESTRATION, "Kubernetes", "K8s Basics",
                          "Основы Kubernetes",
                          ["kubernetes", "k8s", "kubectl", "pod", "deployment"],
                          ["kubectl", "kubernetes"]),
        "200.02": DUCSCode("200.02", DUCSCategory.ORCHESTRATION, "Kubernetes", "K8s Workloads",
                          "Deployment, StatefulSet, DaemonSet",
                          ["deployment", "statefulset", "daemonset", "replicaset"],
                          ["kubectl"]),
        "200.03": DUCSCode("200.03", DUCSCategory.ORCHESTRATION, "Kubernetes", "K8s Networking",
                          "Services, Ingress, NetworkPolicy",
                          ["service", "ingress", "networkpolicy", "loadbalancer"],
                          ["kubectl"]),
        "200.04": DUCSCode("200.04", DUCSCategory.ORCHESTRATION, "Kubernetes", "K8s Storage",
                          "PV, PVC, StorageClass",
                          ["pv", "pvc", "storageclass", "volume", "persistent"],
                          ["kubectl"]),
        "200.05": DUCSCode("200.05", DUCSCategory.ORCHESTRATION, "Kubernetes", "K8s Config",
                          "ConfigMap, Secret",
                          ["configmap", "secret", "env", "environment"],
                          ["kubectl"]),
        "200.06": DUCSCode("200.06", DUCSCategory.ORCHESTRATION, "Helm", "Helm Charts",
                          "Пакетный менеджер Kubernetes",
                          ["helm", "chart", "values", "release", "repository"],
                          ["helm"]),
        "200.07": DUCSCode("200.07", DUCSCategory.ORCHESTRATION, "OpenShift", "OpenShift",
                          "Red Hat OpenShift",
                          ["openshift", "oc", "route", "buildconfig"],
                          ["oc"]),

        # 300 - CI/CD
        "300.01": DUCSCode("300.01", DUCSCategory.CI_CD, "GitLab", "GitLab CI",
                          "GitLab CI/CD пайплайны",
                          ["gitlab-ci", ".gitlab-ci.yml", "pipeline", "stage", "job"],
                          ["gitlab-runner"]),
        "300.02": DUCSCode("300.02", DUCSCategory.CI_CD, "GitHub", "GitHub Actions",
                          "GitHub Actions workflows",
                          ["github actions", "workflow", ".github/workflows", "action"],
                          ["gh"]),
        "300.03": DUCSCode("300.03", DUCSCategory.CI_CD, "Jenkins", "Jenkins",
                          "Jenkins пайплайны",
                          ["jenkins", "jenkinsfile", "pipeline", "groovy"],
                          ["jenkins-cli"]),
        "300.04": DUCSCode("300.04", DUCSCategory.CI_CD, "ArgoCD", "ArgoCD",
                          "GitOps continuous delivery",
                          ["argocd", "gitops", "application", "sync"],
                          ["argocd"]),
        "300.05": DUCSCode("300.05", DUCSCategory.CI_CD, "Tekton", "Tekton",
                          "Cloud-native CI/CD",
                          ["tekton", "task", "pipeline", "pipelinerun"],
                          ["tkn"]),

        # 400 - Monitoring
        "400.01": DUCSCode("400.01", DUCSCategory.MONITORING, "Prometheus", "Prometheus",
                          "Мониторинг метрик",
                          ["prometheus", "promql", "metrics", "alertmanager", "scrape"],
                          ["promtool"]),
        "400.02": DUCSCode("400.02", DUCSCategory.MONITORING, "Grafana", "Grafana",
                          "Визуализация и дашборды",
                          ["grafana", "dashboard", "panel", "datasource"],
                          ["grafana-cli"]),
        "400.03": DUCSCode("400.03", DUCSCategory.MONITORING, "ELK", "ELK Stack",
                          "Elasticsearch, Logstash, Kibana",
                          ["elasticsearch", "logstash", "kibana", "elk", "logs"],
                          ["elasticsearch"]),
        "400.04": DUCSCode("400.04", DUCSCategory.MONITORING, "Loki", "Loki",
                          "Логирование от Grafana",
                          ["loki", "promtail", "logql"],
                          ["logcli"]),
        "400.05": DUCSCode("400.05", DUCSCategory.MONITORING, "Jaeger", "Tracing",
                          "Distributed tracing",
                          ["jaeger", "tracing", "opentelemetry", "tempo", "span"],
                          ["jaeger"]),

        # 500 - Security
        "500.01": DUCSCode("500.01", DUCSCategory.SECURITY, "CVE", "Vulnerabilities",
                          "CVE и уязвимости",
                          ["cve", "vulnerability", "security", "patch", "exploit"],
                          ["trivy", "grype"]),
        "500.02": DUCSCode("500.02", DUCSCategory.SECURITY, "Vault", "Secrets Management",
                          "HashiCorp Vault",
                          ["vault", "secret", "token", "seal", "unseal"],
                          ["vault"]),
        "500.03": DUCSCode("500.03", DUCSCategory.SECURITY, "RBAC", "Access Control",
                          "RBAC в Kubernetes",
                          ["rbac", "role", "rolebinding", "serviceaccount", "permission"],
                          ["kubectl"]),
        "500.04": DUCSCode("500.04", DUCSCategory.SECURITY, "Scanning", "Image Scanning",
                          "Сканирование образов",
                          ["trivy", "grype", "scan", "vulnerability", "clair"],
                          ["trivy", "grype"]),
        "500.05": DUCSCode("500.05", DUCSCategory.SECURITY, "Policy", "Policy as Code",
                          "OPA, Kyverno, Falco",
                          ["opa", "kyverno", "policy", "admission", "falco"],
                          ["opa", "kyverno"]),

        # 600 - Cloud
        "600.01": DUCSCode("600.01", DUCSCategory.CLOUD, "AWS", "AWS",
                          "Amazon Web Services",
                          ["aws", "ec2", "s3", "eks", "lambda", "iam"],
                          ["aws"]),
        "600.02": DUCSCode("600.02", DUCSCategory.CLOUD, "GCP", "Google Cloud",
                          "Google Cloud Platform",
                          ["gcp", "gke", "gcs", "compute", "cloud run"],
                          ["gcloud"]),
        "600.03": DUCSCode("600.03", DUCSCategory.CLOUD, "Azure", "Azure",
                          "Microsoft Azure",
                          ["azure", "aks", "blob", "vm", "devops"],
                          ["az"]),
        "600.04": DUCSCode("600.04", DUCSCategory.CLOUD, "Yandex", "Yandex Cloud",
                          "Yandex Cloud",
                          ["yandex", "yc", "managed kubernetes", "object storage"],
                          ["yc"]),

        # 700 - IaC
        "700.01": DUCSCode("700.01", DUCSCategory.IaC, "Terraform", "Terraform",
                          "Infrastructure as Code",
                          ["terraform", "tf", "hcl", "provider", "module", "state"],
                          ["terraform"]),
        "700.02": DUCSCode("700.02", DUCSCategory.IaC, "Ansible", "Ansible",
                          "Configuration Management",
                          ["ansible", "playbook", "role", "inventory", "task"],
                          ["ansible", "ansible-playbook"]),
        "700.03": DUCSCode("700.03", DUCSCategory.IaC, "Pulumi", "Pulumi",
                          "IaC с программированием",
                          ["pulumi", "stack", "resource"],
                          ["pulumi"]),
        "700.04": DUCSCode("700.04", DUCSCategory.IaC, "CloudFormation", "CloudFormation",
                          "AWS IaC",
                          ["cloudformation", "cfn", "stack", "template"],
                          ["aws"]),

        # 800 - Networking
        "800.01": DUCSCode("800.01", DUCSCategory.NETWORKING, "Istio", "Service Mesh",
                          "Istio Service Mesh",
                          ["istio", "envoy", "sidecar", "virtualservice", "gateway"],
                          ["istioctl"]),
        "800.02": DUCSCode("800.02", DUCSCategory.NETWORKING, "Nginx", "Ingress",
                          "Nginx Ingress Controller",
                          ["nginx", "ingress", "reverse proxy", "load balancer"],
                          ["nginx"]),
        "800.03": DUCSCode("800.03", DUCSCategory.NETWORKING, "DNS", "DNS",
                          "CoreDNS, External-DNS",
                          ["dns", "coredns", "external-dns", "record"],
                          ["dig", "nslookup"]),
        "800.04": DUCSCode("800.04", DUCSCategory.NETWORKING, "Cilium", "eBPF Networking",
                          "Cilium и eBPF",
                          ["cilium", "ebpf", "hubble", "network policy"],
                          ["cilium"]),

        # 900 - DevOps General
        "900.01": DUCSCode("900.01", DUCSCategory.DEVOPS_GENERAL, "Git", "Git",
                          "Работа с Git",
                          ["git", "commit", "branch", "merge", "rebase", "pull request"],
                          ["git"]),
        "900.02": DUCSCode("900.02", DUCSCategory.DEVOPS_GENERAL, "Linux", "Linux Admin",
                          "Администрирование Linux",
                          ["linux", "bash", "shell", "systemd", "ssh"],
                          ["bash", "systemctl"]),
        "900.03": DUCSCode("900.03", DUCSCategory.DEVOPS_GENERAL, "Python", "Python DevOps",
                          "Python для DevOps",
                          ["python", "script", "automation", "boto3", "fabric"],
                          ["python"]),
        "900.04": DUCSCode("900.04", DUCSCategory.DEVOPS_GENERAL, "YAML", "YAML/JSON",
                          "Работа с YAML/JSON",
                          ["yaml", "json", "jq", "yq", "parse"],
                          ["jq", "yq"]),
    }

    # Patterns for NO-LLM classification
    PATTERNS: List[Tuple[str, str, float]] = [
        # Docker
        (r'dockerfile|docker\s+build|docker\s+image|multi-?stage', "100.01", 0.95),
        (r'docker-compose|docker\s+compose|compose\.ya?ml', "100.02", 0.95),
        (r'docker\s+(push|pull|tag)|registry|harbor', "100.03", 0.90),
        (r'podman|buildah|skopeo|rootless', "100.04", 0.95),

        # Kubernetes
        (r'kubectl|kubernetes|k8s\s', "200.01", 0.85),
        (r'deployment|statefulset|daemonset|replicaset', "200.02", 0.90),
        (r'service\s+yaml|ingress|networkpolicy|loadbalancer', "200.03", 0.90),
        (r'pv\s|pvc\s|persistent.*volume|storageclass', "200.04", 0.90),
        (r'configmap|secret\s+yaml', "200.05", 0.90),
        (r'helm|chart|values\.ya?ml', "200.06", 0.95),
        (r'openshift|oc\s+', "200.07", 0.95),

        # CI/CD
        (r'gitlab-?ci|\.gitlab-ci\.ya?ml', "300.01", 0.95),
        (r'github\s+actions?|\.github/workflows', "300.02", 0.95),
        (r'jenkins|jenkinsfile|groovy\s+pipeline', "300.03", 0.95),
        (r'argocd|gitops', "300.04", 0.95),
        (r'tekton|pipelinerun', "300.05", 0.95),

        # Monitoring
        (r'prometheus|promql|alertmanager', "400.01", 0.95),
        (r'grafana|dashboard', "400.02", 0.90),
        (r'elasticsearch|logstash|kibana|elk', "400.03", 0.95),
        (r'loki|promtail', "400.04", 0.95),
        (r'jaeger|tracing|opentelemetry', "400.05", 0.90),

        # Security
        (r'cve-\d{4}|vulnerability|exploit', "500.01", 0.95),
        (r'vault\s|secret.*management', "500.02", 0.90),
        (r'rbac|rolebinding|serviceaccount', "500.03", 0.90),
        (r'trivy|grype|scan.*image', "500.04", 0.95),
        (r'opa|kyverno|policy.*code|falco', "500.05", 0.90),

        # Cloud
        (r'aws\s|ec2|s3\s|eks|lambda', "600.01", 0.90),
        (r'gcp|gke|gcs|google\s+cloud', "600.02", 0.90),
        (r'azure|aks|blob', "600.03", 0.90),
        (r'yandex\s+cloud|yc\s', "600.04", 0.95),

        # IaC
        (r'terraform|\.tf\s|hcl|tfstate', "700.01", 0.95),
        (r'ansible|playbook|inventory', "700.02", 0.95),
        (r'pulumi', "700.03", 0.95),
        (r'cloudformation|cfn', "700.04", 0.95),

        # Networking
        (r'istio|envoy|virtualservice', "800.01", 0.95),
        (r'nginx.*ingress|reverse.*proxy', "800.02", 0.90),
        (r'coredns|external-?dns', "800.03", 0.90),
        (r'cilium|ebpf|hubble', "800.04", 0.95),

        # General
        (r'git\s+(commit|push|pull|merge|rebase)', "900.01", 0.90),
        (r'linux|bash|shell|systemd|systemctl', "900.02", 0.85),
        (r'python.*script|boto3|fabric', "900.03", 0.85),
        (r'\byaml\b|\bjson\b|jq\s|yq\s', "900.04", 0.85),
    ]

    def __init__(self):
        self.classification_history: List[Dict[str, Any]] = []

    def classify(self, text: str) -> Dict[str, Any]:
        """
        Classify text using DUCS system (NO-LLM)

        Returns:
            Dict with ducs_code, category, confidence, keywords
        """
        text_lower = text.lower()
        matches = []

        # Pattern matching
        for pattern, ducs_code, base_confidence in self.PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                code_info = self.DUCS_CODES.get(ducs_code)
                if code_info:
                    # Calculate confidence based on keyword matches
                    keyword_matches = sum(1 for kw in code_info.keywords if kw in text_lower)
                    confidence = min(base_confidence + (keyword_matches * 0.02), 0.99)

                    matches.append({
                        "ducs_code": ducs_code,
                        "category": code_info.category.name,
                        "subcategory": code_info.subcategory,
                        "name": code_info.name,
                        "confidence": confidence,
                        "keywords_matched": keyword_matches,
                        "tools": code_info.tools
                    })

        if not matches:
            return {
                "ducs_code": None,
                "category": "UNKNOWN",
                "confidence": 0.0,
                "message": "No DUCS classification found"
            }

        # Return best match
        best = max(matches, key=lambda x: x["confidence"])

        # Store in history
        self.classification_history.append({
            "text": text[:100],
            "result": best
        })

        return best

    def get_code_info(self, ducs_code: str) -> Optional[DUCSCode]:
        """Get detailed info about a DUCS code"""
        return self.DUCS_CODES.get(ducs_code)

    def list_codes(self, category: DUCSCategory = None) -> List[Dict[str, str]]:
        """List all DUCS codes, optionally filtered by category"""
        result = []
        for code, info in self.DUCS_CODES.items():
            if category is None or info.category == category:
                result.append({
                    "code": code,
                    "name": info.name,
                    "category": info.category.name
                })
        return result

    def suggest_tools(self, text: str) -> List[str]:
        """Suggest relevant tools based on text classification"""
        classification = self.classify(text)
        if classification.get("tools"):
            return classification["tools"]
        return []

    def get_stats(self) -> Dict[str, Any]:
        """Get classification statistics"""
        if not self.classification_history:
            return {"total": 0, "by_category": {}}

        by_category = {}
        for entry in self.classification_history:
            cat = entry["result"].get("category", "UNKNOWN")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total": len(self.classification_history),
            "by_category": by_category
        }


# Singleton instance
ducs = DUCSClassifier()


def classify_task(text: str) -> Dict[str, Any]:
    """Convenience function for task classification"""
    return ducs.classify(text)
