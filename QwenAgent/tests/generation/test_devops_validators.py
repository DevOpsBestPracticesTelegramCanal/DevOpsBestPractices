"""
Tests for DevOps external validators (Week 16-17).

All subprocess calls are mocked — no real tools needed.
Week 17: ansible-lint, shellcheck, helm lint, docker-compose, per-rule timeouts.
"""

import json
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from code_validator.rules.devops_validators import (
    YamllintValidator,
    KubevalValidator,
    KubeLinterValidator,
    TflintValidator,
    CheckovValidator,
    ActionlintValidator,
    AnsibleLintValidator,
    ShellCheckValidator,
    HelmLintValidator,
    DockerComposeValidator,
    detect_content_type,
    devops_external_rules,
    kubernetes_rules,
    terraform_rules,
    github_actions_rules,
    ansible_rules,
    helm_rules,
    bash_rules,
    docker_compose_rules,
    yaml_rules,
    rules_for_content_type,
)
from code_validator.rules.base import RuleSeverity
from code_validator.rules.external_validators import ExternalRule, SUBPROCESS_TIMEOUT


# -----------------------------------------------------------------------
# Sample content
# -----------------------------------------------------------------------

KUBERNETES_MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
"""

TERRAFORM_CONFIG = """\
resource "aws_instance" "web" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"

  tags = {
    Name = "HelloWorld"
  }
}

variable "region" {
  default = "us-east-1"
}
"""

GITHUB_ACTIONS_WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo "Hello"
"""

GENERIC_YAML = """\
server:
  host: 0.0.0.0
  port: 8080
logging:
  level: info
"""

PYTHON_CODE = """\
def hello():
    return "world"

class Foo:
    pass
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "app.py"]
"""

ANSIBLE_PLAYBOOK = """\
- name: Update web servers
  hosts: webservers
  become: yes
  tasks:
    - name: Ensure apache is at the latest version
      ansible.builtin.yum:
        name: httpd
        state: latest
"""

ANSIBLE_TASKS_FILE = """\
- name: install common packages
  apt:
    name: "{{ item }}"
    state: present
  loop:
    - curl
    - git
  gather_facts: no
"""

ANSIBLE_BUILTIN_ONLY = """\
- name: Copy config
  ansible.builtin.template:
    src: template.j2
    dest: /etc/config
"""

HELM_TEMPLATE = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-app
spec:
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
"""

BASH_SCRIPT = """\
#!/bin/bash
set -euo pipefail

function deploy() {
    local env="${1:-staging}"
    if [[ "$env" == "production" ]]; then
        echo "Deploying to production"
    fi
    for service in api web worker; do
        docker-compose up -d "$service"
    done
}

deploy "$@"
"""

BASH_NO_SHEBANG = """\
function cleanup() {
    local tmp_dir="${TMPDIR:-/tmp}"
    if [[ -d "$tmp_dir/build" ]]; then
        rm -rf "$tmp_dir/build"
    fi
    for f in *.log; do
        echo "Cleaning $f"
    done
}
"""

DOCKER_COMPOSE_FILE = """\
services:
  web:
    image: nginx:1.25
    ports:
      - "80:80"
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
"""

DOCKER_COMPOSE_WITH_BUILD = """\
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
"""


# -----------------------------------------------------------------------
# detect_content_type
# -----------------------------------------------------------------------

class TestDetectContentType:

    def test_terraform(self):
        assert detect_content_type(TERRAFORM_CONFIG) == "terraform"

    def test_dockerfile(self):
        assert detect_content_type(DOCKERFILE) == "dockerfile"

    def test_kubernetes(self):
        assert detect_content_type(KUBERNETES_MANIFEST) == "kubernetes"

    def test_github_actions(self):
        assert detect_content_type(GITHUB_ACTIONS_WORKFLOW) == "github_actions"

    def test_python(self):
        assert detect_content_type(PYTHON_CODE) == "python"

    def test_generic_yaml(self):
        assert detect_content_type(GENERIC_YAML) == "yaml"

    def test_empty(self):
        assert detect_content_type("") == "unknown"

    def test_unknown(self):
        assert detect_content_type("just some random text without structure") == "unknown"

    def test_terraform_with_module(self):
        code = 'module "vpc" {\n  source = "./modules/vpc"\n}'
        assert detect_content_type(code) == "terraform"

    def test_terraform_with_provider(self):
        code = 'provider "aws" {\n  region = "us-east-1"\n}'
        assert detect_content_type(code) == "terraform"

    def test_ansible_playbook(self):
        assert detect_content_type(ANSIBLE_PLAYBOOK) == "ansible"

    def test_ansible_tasks_with_gather_facts(self):
        assert detect_content_type(ANSIBLE_TASKS_FILE) == "ansible"

    def test_ansible_builtin_module(self):
        assert detect_content_type(ANSIBLE_BUILTIN_ONLY) == "ansible"

    def test_helm_template_values(self):
        assert detect_content_type(HELM_TEMPLATE) == "helm"

    def test_helm_with_include(self):
        code = "{{- include \"mychart.labels\" . | nindent 4 }}\napiVersion: v1\nkind: ConfigMap"
        assert detect_content_type(code) == "helm"

    def test_helm_with_range(self):
        code = "{{- range .Values.ingress.hosts }}\n- host: {{ .host }}\n{{- end }}"
        assert detect_content_type(code) == "helm"

    def test_helm_with_toyaml(self):
        code = "resources:\n{{- toYaml .Values.resources | nindent 12 }}"
        assert detect_content_type(code) == "helm"

    def test_bash_with_shebang(self):
        assert detect_content_type(BASH_SCRIPT) == "bash"

    def test_bash_shebang_sh(self):
        code = "#!/bin/sh\necho hello"
        assert detect_content_type(code) == "bash"

    def test_bash_shebang_usr_bin(self):
        code = "#!/usr/bin/bash\nset -e\necho done"
        assert detect_content_type(code) == "bash"

    def test_bash_without_shebang_strong_patterns(self):
        assert detect_content_type(BASH_NO_SHEBANG) == "bash"

    def test_docker_compose_with_image(self):
        assert detect_content_type(DOCKER_COMPOSE_FILE) == "docker_compose"

    def test_docker_compose_with_build(self):
        assert detect_content_type(DOCKER_COMPOSE_WITH_BUILD) == "docker_compose"

    def test_docker_compose_is_not_k8s(self):
        """Docker Compose with services: should not be detected as kubernetes."""
        code = "services:\n  web:\n    image: nginx\n    ports:\n      - '80:80'\n"
        assert detect_content_type(code) == "docker_compose"

    def test_helm_takes_priority_over_kubernetes(self):
        """Helm templates with apiVersion/kind should be helm, not kubernetes."""
        assert detect_content_type(HELM_TEMPLATE) == "helm"

    def test_docker_compose_version_only_is_yaml(self):
        """Docker Compose with only version: but no services: is just yaml."""
        code = "version: '3.8'\nlogging:\n  level: debug\n"
        assert detect_content_type(code) == "yaml"


# -----------------------------------------------------------------------
# YamllintValidator
# -----------------------------------------------------------------------

class TestYamllintValidator:

    def test_clean_yaml(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = YamllintValidator().check(GENERIC_YAML)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        output = "file.yaml:3:1: [error] trailing spaces (trailing-spaces)\nfile.yaml:5:1: [warning] too many blank lines (empty-lines)"
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = YamllintValidator().check(GENERIC_YAML)
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.messages) >= 1

    def test_warnings_only(self, monkeypatch):
        output = "file.yaml:5:1: [warning] too many blank lines (empty-lines)"
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = YamllintValidator().check(GENERIC_YAML)
        assert result.passed is True

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("yamllint not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = YamllintValidator().check(GENERIC_YAML)
        assert result.passed is True
        assert "not installed" in result.messages[0]


# -----------------------------------------------------------------------
# KubevalValidator
# -----------------------------------------------------------------------

class TestKubevalValidator:

    def test_valid_manifest(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubevalValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is True
        assert result.score == 1.0

    def test_invalid_manifest(self, monkeypatch):
        output = json.dumps([{
            "filename": "test.yaml",
            "kind": "Deployment",
            "status": "invalid",
            "errors": ["spec.replicas: Invalid type. Expected: integer, given: string"],
        }])
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubevalValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is False
        assert result.score < 1.0

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("kubeval not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = KubevalValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is True

    def test_bad_json(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="not json", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubevalValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is False
        assert "unparseable" in result.messages[0]


# -----------------------------------------------------------------------
# KubeLinterValidator
# -----------------------------------------------------------------------

class TestKubeLinterValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubeLinterValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is True

    def test_with_reports(self, monkeypatch):
        output = json.dumps({
            "Reports": [
                {
                    "Check": "no-read-only-root-fs",
                    "Diagnostic": {"Message": "container has no read-only root filesystem"},
                },
                {
                    "Check": "run-as-non-root",
                    "Diagnostic": {"Message": "container is running as root"},
                },
            ]
        })
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubeLinterValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is False
        assert len(result.messages) == 2

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("kube-linter not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = KubeLinterValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is True

    def test_bad_json(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="{bad", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = KubeLinterValidator().check(KUBERNETES_MANIFEST)
        assert result.passed is False


# -----------------------------------------------------------------------
# TflintValidator
# -----------------------------------------------------------------------

class TestTflintValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = TflintValidator().check(TERRAFORM_CONFIG)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_issues(self, monkeypatch):
        output = json.dumps({
            "issues": [
                {
                    "rule": {"name": "aws_instance_invalid_type", "severity": "error"},
                    "message": "\"t2.super\" is an invalid value as instance_type",
                },
                {
                    "rule": {"name": "terraform_naming_convention", "severity": "warning"},
                    "message": "variable name should be snake_case",
                },
            ]
        })
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = TflintValidator().check(TERRAFORM_CONFIG)
        assert result.passed is False
        assert len(result.messages) == 2

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("tflint not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = TflintValidator().check(TERRAFORM_CONFIG)
        assert result.passed is True

    def test_bad_json(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout="broken", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = TflintValidator().check(TERRAFORM_CONFIG)
        assert result.passed is False

    def test_warnings_only_pass(self, monkeypatch):
        output = json.dumps({
            "issues": [
                {
                    "rule": {"name": "terraform_naming_convention", "severity": "warning"},
                    "message": "variable name should be snake_case",
                },
            ]
        })
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = TflintValidator().check(TERRAFORM_CONFIG)
        assert result.passed is True  # only warnings


# -----------------------------------------------------------------------
# CheckovValidator
# -----------------------------------------------------------------------

class TestCheckovValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = CheckovValidator().check(TERRAFORM_CONFIG)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_failures(self, monkeypatch):
        output = json.dumps({
            "results": {
                "failed_checks": [
                    {"check_id": "CKV_AWS_79", "check_name": "Ensure IMDSv2 is enabled"},
                    {"check_id": "CKV_AWS_88", "check_name": "Ensure no public IP"},
                ],
                "passed_checks": [],
            }
        })
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = CheckovValidator().check(TERRAFORM_CONFIG)
        assert result.passed is False
        assert len(result.messages) == 2
        assert "CKV_AWS_79" in result.messages[0]

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("checkov not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = CheckovValidator().check(TERRAFORM_CONFIG)
        assert result.passed is True

    def test_bad_json(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="not json", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = CheckovValidator().check(TERRAFORM_CONFIG)
        assert result.passed is False

    def test_list_output_format(self, monkeypatch):
        """checkov sometimes returns a list of dicts."""
        output = json.dumps([{
            "results": {
                "failed_checks": [
                    {"check_id": "CKV_AWS_1", "check_name": "Ensure encryption"},
                ],
                "passed_checks": [],
            }
        }])
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = CheckovValidator().check(TERRAFORM_CONFIG)
        assert result.passed is False
        assert "CKV_AWS_1" in result.messages[0]


# -----------------------------------------------------------------------
# ActionlintValidator
# -----------------------------------------------------------------------

class TestActionlintValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ActionlintValidator().check(GITHUB_ACTIONS_WORKFLOW)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        errors = [
            {"message": "unknown action \"actions/checkout@v99\"", "line": 9, "column": 7},
            {"message": "unexpected key \"foobar\"", "line": 3, "column": 1},
        ]
        output = "\n".join(json.dumps(e) for e in errors)
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ActionlintValidator().check(GITHUB_ACTIONS_WORKFLOW)
        assert result.passed is False
        assert len(result.messages) == 2

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("actionlint not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = ActionlintValidator().check(GITHUB_ACTIONS_WORKFLOW)
        assert result.passed is True

    def test_bad_output(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="plain error text", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ActionlintValidator().check(GITHUB_ACTIONS_WORKFLOW)
        assert result.passed is False
        assert len(result.messages) >= 1


# -----------------------------------------------------------------------
# Factory functions
# -----------------------------------------------------------------------

class TestFactoryFunctions:

    def test_devops_external_rules_returns_10(self):
        rules = devops_external_rules()
        assert len(rules) == 10
        names = [r.name for r in rules]
        assert "ansible-lint" in names
        assert "shellcheck" in names
        assert "helm-lint" in names
        assert "docker-compose" in names

    def test_kubernetes_rules(self):
        rules = kubernetes_rules()
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "kubeval" in names
        assert "kube-linter" in names

    def test_terraform_rules(self):
        rules = terraform_rules()
        names = [r.name for r in rules]
        assert "tflint" in names
        assert "checkov" in names

    def test_github_actions_rules(self):
        rules = github_actions_rules()
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "actionlint" in names

    def test_ansible_rules_includes_ansible_lint(self):
        rules = ansible_rules()
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "ansible-lint" in names
        assert len(rules) == 2

    def test_helm_rules(self):
        rules = helm_rules()
        names = [r.name for r in rules]
        assert "helm-lint" in names
        assert len(rules) == 1

    def test_bash_rules(self):
        rules = bash_rules()
        names = [r.name for r in rules]
        assert "shellcheck" in names
        assert len(rules) == 1

    def test_docker_compose_rules(self):
        rules = docker_compose_rules()
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "docker-compose" in names
        assert len(rules) == 2

    def test_yaml_rules(self):
        rules = yaml_rules()
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert len(rules) == 1


# -----------------------------------------------------------------------
# rules_for_content_type
# -----------------------------------------------------------------------

class TestRulesForContentType:

    def test_kubernetes(self):
        rules = rules_for_content_type("kubernetes")
        names = [r.name for r in rules]
        assert "kubeval" in names

    def test_terraform(self):
        rules = rules_for_content_type("terraform")
        names = [r.name for r in rules]
        assert "tflint" in names
        assert "checkov" in names

    def test_unknown_returns_empty(self):
        assert rules_for_content_type("unknown") == []

    def test_python_returns_empty(self):
        # Python validators are handled separately
        assert rules_for_content_type("python") == []

    def test_github_actions(self):
        rules = rules_for_content_type("github_actions")
        names = [r.name for r in rules]
        assert "actionlint" in names

    def test_ansible(self):
        rules = rules_for_content_type("ansible")
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "ansible-lint" in names

    def test_helm(self):
        rules = rules_for_content_type("helm")
        names = [r.name for r in rules]
        assert "helm-lint" in names

    def test_bash(self):
        rules = rules_for_content_type("bash")
        names = [r.name for r in rules]
        assert "shellcheck" in names

    def test_docker_compose(self):
        rules = rules_for_content_type("docker_compose")
        names = [r.name for r in rules]
        assert "docker-compose" in names
        assert "yamllint" in names


# -----------------------------------------------------------------------
# Registry integration
# -----------------------------------------------------------------------

class TestRegistryIntegration:

    def test_devops_validators_in_registry(self):
        """DevOps validators should be importable and in the registry."""
        from code_validator.rules.python_validators import _RULE_REGISTRY
        # Week 16 validators
        assert "yamllint" in _RULE_REGISTRY
        assert "kubeval" in _RULE_REGISTRY
        assert "kube-linter" in _RULE_REGISTRY
        assert "tflint" in _RULE_REGISTRY
        assert "checkov" in _RULE_REGISTRY
        assert "actionlint" in _RULE_REGISTRY

    def test_week17_validators_in_registry(self):
        """Week 17 validators should also be in the registry."""
        from code_validator.rules.python_validators import _RULE_REGISTRY
        assert "ansible-lint" in _RULE_REGISTRY
        assert "shellcheck" in _RULE_REGISTRY
        assert "helm-lint" in _RULE_REGISTRY
        assert "docker-compose" in _RULE_REGISTRY

    def test_registry_returns_correct_classes(self):
        from code_validator.rules.python_validators import _RULE_REGISTRY
        assert _RULE_REGISTRY["ansible-lint"] is AnsibleLintValidator
        assert _RULE_REGISTRY["shellcheck"] is ShellCheckValidator
        assert _RULE_REGISTRY["helm-lint"] is HelmLintValidator
        assert _RULE_REGISTRY["docker-compose"] is DockerComposeValidator

    def test_build_rules_for_devops_names(self):
        from code_validator.rules.python_validators import build_rules_for_names
        rules = build_rules_for_names(["yamllint", "kubeval", "tflint"])
        assert len(rules) == 3
        names = [r.name for r in rules]
        assert "yamllint" in names
        assert "kubeval" in names
        assert "tflint" in names

    def test_build_rules_for_week17_names(self):
        from code_validator.rules.python_validators import build_rules_for_names
        rules = build_rules_for_names(["ansible-lint", "shellcheck", "helm-lint", "docker-compose"])
        assert len(rules) == 4
        names = [r.name for r in rules]
        assert "ansible-lint" in names
        assert "shellcheck" in names


# -----------------------------------------------------------------------
# Validator weights
# -----------------------------------------------------------------------

class TestValidatorWeights:

    def test_yamllint_weight(self):
        assert YamllintValidator().weight == 1.5

    def test_kubeval_weight(self):
        assert KubevalValidator().weight == 2.0

    def test_kube_linter_weight(self):
        assert KubeLinterValidator().weight == 1.5

    def test_tflint_weight(self):
        assert TflintValidator().weight == 2.0

    def test_checkov_weight(self):
        assert CheckovValidator().weight == 2.5

    def test_actionlint_weight(self):
        assert ActionlintValidator().weight == 2.0

    def test_ansible_lint_weight(self):
        assert AnsibleLintValidator().weight == 2.0

    def test_shellcheck_weight(self):
        assert ShellCheckValidator().weight == 2.0

    def test_helm_lint_weight(self):
        assert HelmLintValidator().weight == 1.5

    def test_docker_compose_weight(self):
        assert DockerComposeValidator().weight == 1.5


# -----------------------------------------------------------------------
# Per-rule timeout (Week 17)
# -----------------------------------------------------------------------

class TestPerRuleTimeout:

    def test_default_timeout(self):
        """ExternalRule default timeout matches global constant."""
        assert ExternalRule.timeout == SUBPROCESS_TIMEOUT

    def test_ansible_lint_timeout(self):
        v = AnsibleLintValidator()
        assert v.timeout == 15
        assert v.effective_timeout == 15

    def test_shellcheck_timeout(self):
        v = ShellCheckValidator()
        assert v.timeout == 5
        assert v.effective_timeout == 5

    def test_helm_lint_timeout(self):
        v = HelmLintValidator()
        assert v.timeout == 15

    def test_docker_compose_timeout(self):
        v = DockerComposeValidator()
        assert v.timeout == 10

    def test_week16_validators_use_default_timeout(self):
        """Week 16 validators should use the default SUBPROCESS_TIMEOUT."""
        for cls in (YamllintValidator, KubevalValidator, KubeLinterValidator,
                    TflintValidator, CheckovValidator, ActionlintValidator):
            v = cls()
            assert v.timeout == SUBPROCESS_TIMEOUT, f"{cls.__name__} should use default timeout"


# -----------------------------------------------------------------------
# AnsibleLintValidator (Week 17)
# -----------------------------------------------------------------------

class TestAnsibleLintValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        output = (
            "/tmp/test.yml:5: [E403] Package installs should not use latest\n"
            "/tmp/test.yml:3: [E301] Commands should not change things\n"
        )
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.messages) == 2

    def test_warnings_only_pass(self, monkeypatch):
        output = "/tmp/test.yml:7: [W204] Lines should be no longer than 160 chars\n"
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is True  # only warnings
        assert result.score < 1.0

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("ansible-lint not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is True
        assert "not installed" in result.messages[0]

    def test_no_parseable_output(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is True
        assert result.score == 0.9

    def test_mixed_errors_and_warnings(self, monkeypatch):
        output = (
            "/tmp/test.yml:5: [E403] Package installs should not use latest\n"
            "/tmp/test.yml:7: [W204] Lines should be no longer than 160 chars\n"
            "/tmp/test.yml:9: [E301] Commands should not change things\n"
        )
        proc = subprocess.CompletedProcess(args=[], returncode=2, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = AnsibleLintValidator().check(ANSIBLE_PLAYBOOK)
        assert result.passed is False
        assert len(result.messages) == 3
        assert result.severity == RuleSeverity.ERROR

    def test_file_suffix(self):
        assert AnsibleLintValidator()._file_suffix() == ".yml"


# -----------------------------------------------------------------------
# ShellCheckValidator (Week 17)
# -----------------------------------------------------------------------

class TestShellCheckValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        issues = [
            {"level": "error", "code": 2086, "message": "Double quote to prevent globbing", "line": 5},
            {"level": "warning", "code": 2034, "message": "x appears unused", "line": 3},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is False
        assert result.score < 1.0
        assert "SC2086" in result.messages[0]

    def test_warnings_only(self, monkeypatch):
        issues = [
            {"level": "warning", "code": 2034, "message": "x appears unused", "line": 3},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is True  # only warnings
        assert result.score < 1.0

    def test_style_only(self, monkeypatch):
        issues = [
            {"level": "style", "code": 2006, "message": "Use $(...) notation", "line": 2},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is True
        assert result.score == 0.9

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("shellcheck not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is True
        assert "not installed" in result.messages[0]

    def test_bad_json(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="not json {", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is False
        assert "unparseable" in result.messages[0]

    def test_unexpected_format(self, monkeypatch):
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps({"unexpected": True}), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = ShellCheckValidator().check(BASH_SCRIPT)
        assert result.passed is False
        assert "unexpected" in result.messages[0]

    def test_file_suffix(self):
        assert ShellCheckValidator()._file_suffix() == ".sh"


# -----------------------------------------------------------------------
# HelmLintValidator (Week 17)
# -----------------------------------------------------------------------

class TestHelmLintValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HelmLintValidator().check(HELM_TEMPLATE)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_warnings(self, monkeypatch):
        output = "[WARNING] templates/: chart directory is missing Chart.yaml\n"
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HelmLintValidator().check(HELM_TEMPLATE)
        assert result.passed is True
        assert result.score == 0.9

    def test_with_errors(self, monkeypatch):
        output = "[ERROR] templates/: parse error in template\n[WARNING] chart missing description\n"
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=output, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HelmLintValidator().check(HELM_TEMPLATE)
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.messages) >= 1

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("helm not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = HelmLintValidator().check(HELM_TEMPLATE)
        assert result.passed is True
        assert "not installed" in result.messages[0]

    def test_creates_chart_structure(self, monkeypatch):
        """Verify that check() creates Chart.yaml and values.yaml."""
        created_files = []
        original_run = subprocess.run

        def mock_run(cmd, **kw):
            # Inspect the chart directory
            if cmd[0] == "helm":
                chart_dir = cmd[-1]
                if os.path.isdir(chart_dir):
                    for root, dirs, files in os.walk(chart_dir):
                        for f in files:
                            created_files.append(os.path.join(root, f))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        HelmLintValidator().check(HELM_TEMPLATE)

        filenames = [os.path.basename(f) for f in created_files]
        assert "Chart.yaml" in filenames
        assert "values.yaml" in filenames
        assert "template.yaml" in filenames

    def test_file_suffix(self):
        assert HelmLintValidator()._file_suffix() == ".yaml"


# -----------------------------------------------------------------------
# DockerComposeValidator (Week 17)
# -----------------------------------------------------------------------

class TestDockerComposeValidator:

    def test_clean(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = DockerComposeValidator().check(DOCKER_COMPOSE_FILE)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="services.web.ports contains an invalid type\n"
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = DockerComposeValidator().check(DOCKER_COMPOSE_FILE)
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.messages) >= 1

    def test_v2_fallback_to_v1(self, monkeypatch):
        """If docker compose (v2) fails with FileNotFoundError, fall back to docker-compose (v1)."""
        call_count = [0]

        def mock_run(cmd, **kw):
            call_count[0] += 1
            if cmd[0] == "docker" and cmd[1] == "compose":
                raise FileNotFoundError("docker not found")
            # docker-compose v1 succeeds
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = DockerComposeValidator().check(DOCKER_COMPOSE_FILE)
        assert result.passed is True
        assert call_count[0] == 2  # v2 failed, v1 succeeded

    def test_both_not_installed(self, monkeypatch):
        def mock_run(cmd, **kw):
            raise FileNotFoundError("not found")
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = DockerComposeValidator().check(DOCKER_COMPOSE_FILE)
        assert result.passed is True
        assert "not installed" in result.messages[0]

    def test_errors_from_stderr(self, monkeypatch):
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="service 'db' refers to undefined volume 'pgdata'\nsyntax error at line 5\n"
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = DockerComposeValidator().check(DOCKER_COMPOSE_FILE)
        assert result.passed is False
        assert len(result.messages) == 2

    def test_file_suffix(self):
        assert DockerComposeValidator()._file_suffix() == ".yaml"
